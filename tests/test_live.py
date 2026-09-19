import json
import asyncio
from contextlib import closing
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np

from core.live_tracker import LiveTracker
from core.live_zones import validate_zones, find_zone
from core.engine import HighAccuracyFaceEngine
from db import connection
from services.live_events import LiveEventRecorder
from services.stream_service import StreamService, ThreadedCameraReader


def detection(pid=1, x=0, embedding=None):
    return dict(bbox=[x, 0, x+60, 60], person_id=pid, name=f'Person {pid}' if pid else 'Unknown',
                confidence=0.8, quality_ok=True, embedding=embedding, quality_reason='',
                face_pixels=60, sharpness=100.0)


class TrackerTests(unittest.TestCase):
    def test_multiple_people_confirm_only_after_three_observations(self):
        tracker = LiveTracker()
        for now in (1, 1.1):
            results = tracker.update([detection(), detection(2, 100)], now)
            self.assertFalse(any(r['confirmed'] for r in results))
        results = tracker.update([detection(), detection(2, 100)], 1.2)
        self.assertEqual([r['person_id'] for r in results if r['confirmed']], [1, 2])

    def test_unknown_or_blurred_never_inherits_confirmation(self):
        tracker = LiveTracker()
        for now in (1, 1.1, 1.2):
            tracker.update([detection()], now)
        for det, now in ((detection(None), 1.3), ({**detection(), 'quality_ok': False}, 1.4)):
            result = tracker.update([det], now)[0]
            self.assertFalse(result['confirmed'])
            self.assertEqual(result['name'], 'Unknown')

    def test_occlusion_is_lost_not_a_fresh_detection(self):
        tracker = LiveTracker()
        for now in (1, 1.1, 1.2):
            tracker.update([detection()], now)
        result = tracker.update([], 1.3)[0]
        self.assertEqual(result['state'], 'lost')
        self.assertFalse(result['confirmed'])
        self.assertEqual(tracker.update([], 3), [])

    def test_identity_change_needs_own_votes(self):
        tracker = LiveTracker()
        for now in (1, 1.1, 1.2):
            tracker.update([detection()], now)
        results = tracker.update([detection(2)], 1.3)
        self.assertFalse(any(r['confirmed'] for r in results))

    def test_appearance_conflict_does_not_reuse_track(self):
        tracker = LiveTracker()
        first = tracker.update([detection(embedding=np.array([1., 0.]))], 1)[0]
        second = tracker.update([detection(None, embedding=np.array([0., 1.]))], 1.1)[0]
        self.assertNotEqual(first['track_id'], second['track_id'])

    def test_votes_expire_by_time(self):
        tracker = LiveTracker()
        for now in (1, 2.4, 3.8):
            self.assertFalse(tracker.update([detection()], now)[0]['confirmed'])

    def test_movement_prediction_continues_track(self):
        tracker = LiveTracker()
        first = tracker.update([detection(x=0)], 1)[0]
        tracker.update([detection(x=30)], 1.1)
        third = tracker.update([detection(x=90)], 1.3)[0]
        self.assertEqual(first['track_id'], third['track_id'])
        self.assertTrue(third['confirmed'])


class MatchingTests(unittest.TestCase):
    def engine(self, rows):
        engine = HighAccuracyFaceEngine.__new__(HighAccuracyFaceEngine)
        engine.live_rows = rows
        engine.live_matrix = np.stack([r[3]/np.linalg.norm(r[3]) for r in rows])
        return engine

    def test_margin_is_between_people_not_two_samples_of_same_person(self):
        engine = self.engine([(1,'A',True,np.array([1.,0.])), (1,'A',True,np.array([.99,.01])),
                              (2,'B',True,np.array([0.,1.]))])
        self.assertEqual(engine.match_live_face(np.array([1.,0.]))[0], 1)

    def test_disabled_best_match_is_not_assigned_to_next_person(self):
        engine = self.engine([(1,'A',False,np.array([1.,0.])), (2,'B',True,np.array([.8,.6]))])
        self.assertIsNone(engine.match_live_face(np.array([1.,0.]))[0])


    def test_ambiguous_identities_are_rejected(self):
        engine = self.engine([(1,'A',True,np.array([1.,0.])), (2,'B',True,np.array([.99,.01]))])
        self.assertIsNone(engine.match_live_face(np.array([1.,0.]))[0])


class ScanTests(unittest.TestCase):
    def test_tiles_map_back_to_original_and_duplicate_faces_merge(self):
        engine = HighAccuracyFaceEngine.__new__(HighAccuracyFaceEngine)
        engine.inference_lock = threading.RLock()
        engine.live_matrix = np.array([[1., 0.]])
        engine.live_rows = [(1, 'A', True, np.array([1., 0.]))]
        class Detector:
            sizes = []
            def detect(self, frame, input_size):
                self.sizes.append(input_size)
                return (np.array([[20.,20.,100.,100.,.95]]),
                        np.array([[[40.,40.],[80.,40.],[60.,60.],[42.,80.],[78.,80.]]]))
        class Recognizer:
            shapes = []
            def get(self, frame, face):
                self.shapes.append(frame.shape)
                face.embedding = np.array([1.,0.])
        from types import SimpleNamespace
        detector, recognizer = Detector(), Recognizer()
        engine.app = SimpleNamespace(det_model=detector, models={'recognition':recognizer})
        frame = np.random.default_rng(1).integers(0,256,(1080,1920,3),dtype=np.uint8)
        merged = engine.process_frame_live(frame, 0)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['person_id'], 1)
        results = engine.process_frame_live(frame, 5)
        self.assertEqual(len(results), 2)
        self.assertIn([1076,452,1156,532], [r['bbox'] for r in results])
        self.assertEqual(detector.sizes, [(1280,1280),(640,640)]*2)
        self.assertTrue(all(s == frame.shape for s in recognizer.shapes))

        # Blurred regions cannot generate embeddings or identities.
        recognizer.shapes.clear()
        rejected = engine.process_frame_live(np.zeros_like(frame), 0)
        self.assertFalse(rejected[0]['quality_ok'])
        self.assertIsNone(rejected[0]['person_id'])
        self.assertEqual(recognizer.shapes, [])

class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp.name)/'test.db')
        self.patches = [patch.object(connection, 'DB_PATH', self.db_path),
                        patch('services.live_events.SNAPSHOT_DIR', self.temp.name)]
        for p in self.patches:
            p.start()
        connection.init_db()
        self.frame = np.ones((100, 200, 3), dtype=np.uint8) * 127

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def rows(self):
        with closing(connection.get_db()) as conn, conn:
            return conn.execute('SELECT * FROM detection_logs ORDER BY id').fetchall()

    def confirmed(self, pid=1):
        return {**detection(pid), 'confirmed':True, 'state':'confirmed', 'track_id':pid, 'zone':'Desks'}

    def test_events_update_last_seen_and_reentry_creates_new_event(self):
        recorder = LiveEventRecorder()
        recorder.record([self.confirmed(), self.confirmed(2)], self.frame, 'iphone', 100)
        recorder.record([self.confirmed()], self.frame, 'iphone', 102)
        self.assertEqual(len(self.rows()), 2)
        self.assertIn('42.', self.rows()[0]['last_seen_at'])
        recorder.record([self.confirmed()], self.frame, 'iphone', 120)
        self.assertEqual(len(self.rows()), 3)
        self.assertTrue(all(Path(self.temp.name, r['face_path'].split('/')[-1]).exists() for r in self.rows()))

    def test_lost_pending_unknown_never_log(self):
        recorder = LiveEventRecorder()
        recorder.record([{**self.confirmed(), 'state':'lost'},
                         {**self.confirmed(2), 'confirmed':False}], self.frame, 'iphone', 100)
        self.assertEqual(len(self.rows()), 0)

    def test_two_tracks_same_person_create_one_event_and_clear_recovers(self):
        recorder = LiveEventRecorder()
        recorder.record([self.confirmed(), self.confirmed()], self.frame, 'iphone', 100)
        self.assertEqual(len(self.rows()), 1)
        with closing(connection.get_db()) as conn, conn:
            conn.execute('DELETE FROM detection_logs')
        recorder.record([self.confirmed()], self.frame, 'iphone', 101)
        self.assertEqual(len(self.rows()), 1)

    def test_snapshot_failure_does_not_create_log(self):
        with patch('services.live_events.cv2.imwrite', return_value=False):
            with self.assertRaises(OSError):
                LiveEventRecorder().record([self.confirmed()], self.frame, 'iphone', 100)
        self.assertEqual(len(self.rows()), 0)

    def test_migration_preserves_legacy_rows_and_is_repeatable(self):
        # Reproduce the schema that predates this feature, not an already migrated DB.
        with closing(connection.get_db()) as conn, conn:
            conn.execute('DROP TABLE persons')
            conn.execute('DROP TABLE detection_logs')
            conn.execute('CREATE TABLE persons (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
            conn.execute('CREATE TABLE detection_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, person_name TEXT NOT NULL, confidence REAL NOT NULL, detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
        with closing(connection.get_db()) as conn, conn:
            conn.execute("INSERT INTO persons(name) VALUES ('Legacy')")
            conn.execute("INSERT INTO detection_logs(person_name, confidence) VALUES ('Legacy', .7)")
        connection.init_db()
        connection.init_db()
        self.assertEqual(len(self.rows()), 1)
        with closing(connection.get_db()) as conn, conn:
            self.assertEqual(conn.execute('SELECT search_enabled FROM persons').fetchone()[0], 1)

    def test_event_snapshot_zone_stays_fixed_when_person_moves(self):
        recorder = LiveEventRecorder()
        recorder.record([{**self.confirmed(), 'zone':'Door'}], self.frame, 'iphone', 100)
        recorder.record([{**self.confirmed(), 'zone':'Desks'}], self.frame, 'iphone', 102)
        row = self.rows()[0]
        self.assertEqual(row['zone'], 'Door')
        self.assertEqual(row['last_zone'], 'Desks')

    def test_api_logs_and_watchlist(self):
        from fastapi import FastAPI
        from httpx import AsyncClient, ASGITransport
        from routers.logs import router as logs_router
        from routers.persons import router as persons_router
        app = FastAPI()
        app.include_router(logs_router)
        app.include_router(persons_router)
        with closing(connection.get_db()) as conn, conn:
            conn.execute("INSERT INTO persons(name) VALUES ('A')")
        LiveEventRecorder().record([self.confirmed()], self.frame, 'iphone', 100)
        async def check():
            async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
                with patch('routers.persons.get_ai_engine'):
                    self.assertEqual((await client.get('/api/logs')).status_code, 200)
                    self.assertTrue((await client.get('/api/logs')).json()['logs'][0]['face_path'])
                    self.assertEqual((await client.put('/api/persons/1/search?enabled=false')).status_code, 200)
                    self.assertFalse((await client.get('/api/persons')).json()['persons'][0]['search_enabled'])
                    self.assertEqual((await client.put('/api/persons/999/search?enabled=false')).status_code, 404)
        asyncio.run(check())



class ZoneTests(unittest.TestCase):
    def test_normalized_zone_and_fallback(self):
        zones = validate_zones([{'name':'Door', 'rect':[0,0,.5,1]}])
        self.assertEqual(find_zone([0,0,40,40], (100,200,3), zones), 'Door')
        self.assertEqual(find_zone([150,0,190,40], (100,200,3), zones), 'Toàn cảnh')

    def test_invalid_zones(self):
        for rect in ([0,0,2,1], [0,0,0,1], [0,0,float('nan'),1]):
            with self.assertRaises(ValueError):
                validate_zones([{'name':'Invalid', 'rect':rect}])


class ServiceTests(unittest.TestCase):
    def test_same_capture_sequence_cannot_confirm_three_times(self):
        service = StreamService()
        stop = threading.Event()
        class Reader:
            def packet(self):
                return np.zeros((100,100,3), dtype=np.uint8), 1, time.time(), time.monotonic()
        class Engine:
            inference_lock = threading.RLock()
            gallery_version = 1
            calls = 0
            def runtime_providers(self): return {}
            def process_frame_live(self, frame, tile):
                self.calls += 1
                return [detection()]
        engine = Engine()
        with patch('services.stream_service.get_ai_engine', return_value=engine), patch.object(service.recorder, 'record') as record:
            thread = threading.Thread(target=service._ai_loop, args=(Reader(),stop,service.generation,'iphone'))
            thread.start()
            time.sleep(.35)
            stop.set()
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(engine.calls, 1)
            self.assertFalse(record.call_args[0][0][0]['confirmed'])

    def test_stale_camera_clears_confirmed_status(self):
        service = StreamService()
        class Reader:
            captured_mono = time.monotonic()-10
            latest_frame = np.zeros((100,200,3), dtype=np.uint8)
            capture_fps = 30
            def is_opened(self): return True
        service.active_reader = Reader()
        service.state.update(detections=[{'confirmed':True}], processed_mono=time.monotonic())
        self.assertFalse(service.status()['connected'])
        self.assertEqual(service.status()['detections'], [])

    def test_two_viewers_share_worker_and_closing_one_does_not_stop_camera(self):
        service = StreamService()
        class Reader:
            captured_mono = time.monotonic()
            latest_frame = np.zeros((100,200,3), dtype=np.uint8)
            capture_fps = 30
            def is_opened(self): return True
            def read(self): return True, self.latest_frame.copy()
        service.active_reader = Reader()
        service.current_source, service.current_ip = 'iphone', ''
        with patch('services.stream_service.threading.Thread') as thread:
            one = service.generate_video_stream()
            two = service.generate_video_stream()
            self.assertIn(b'Content-Type: image/jpeg', next(one))
            self.assertIn(b'Content-Type: image/jpeg', next(two))
            one.close()
            self.assertTrue(service.active_reader.is_opened())
            self.assertIn(b'Content-Type: image/jpeg', next(two))
            two.close()
            thread.assert_not_called()


if __name__ == '__main__':
    unittest.main()
