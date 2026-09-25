import asyncio
import json
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI
from core.gallery import GallerySnapshot
from core.engine import HighAccuracyFaceEngine
from db import connection
from db.jobs_repo import (create_video_job, get_video_job, get_video_detections_since, get_job_summary,
                         mark_interrupted_video_jobs, set_video_job_details, serialize_video_detection)
from db.jobs_repo import get_video_snapshots_since
from services.video_worker import analyze_video_background, needs_dense_sampling
from services.video_events import VideoEventRecorder
from routers.analysis import router


def gallery():
    return GallerySnapshot([(1, 'A', True, np.array([1.,0.])),
                            (2, 'B', True, np.array([0.,1.])),
                            (3, 'Off', False, np.array([-1.,0.]))])


def face(pid=1, x=5, confirmed=True):
    return dict(person_id=pid, name='A' if pid == 1 else 'B', confidence=.9,
                bbox=[x,5,x+50,55], quality_ok=True, embedding=None,
                confirmed=confirmed, state='confirmed' if confirmed else 'pending', track_id=pid,
                first_seen_mono=0.0, zone='Door')


class GalleryTests(unittest.TestCase):
    def test_snapshot_urls_support_legacy_clients_without_double_slash(self):
        for path in ('static/snapshots/face.jpg', '/static/snapshots/face.jpg', '//static/snapshots/face.jpg'):
            result = serialize_video_detection({'snapshot_path':path, 'scene_path':None})
            self.assertEqual(result['snapshot_path'],'static/snapshots/face.jpg')
            # Old frontend prepends '/', new frontend normalizes either form.
            self.assertEqual('/'+result['snapshot_path'],'/static/snapshots/face.jpg')

    def test_snapshot_survives_source_changes_and_keeps_disabled_competitors(self):
        vector = np.array([1.,0.])
        rows = [(1,'A',True,vector), (2,'Off',False,np.array([0.,1.]))]
        snapshot = GallerySnapshot(rows)
        fingerprint = snapshot.audit()['gallery_sha256']
        vector[:] = [0,1]
        rows[0] = (1,'Renamed',False,vector)
        self.assertEqual(snapshot.match(np.array([1.,0.]))[:2], (1,'A'))
        self.assertIsNone(snapshot.match(np.array([0.,1.]))[0])
        self.assertEqual(snapshot.watchlist, [{'id':1,'name':'A','sample_count':1}])
        self.assertEqual(snapshot.audit()['gallery_sha256'], fingerprint)
        with self.assertRaises(ValueError):
            snapshot.matrix[0,0] = 2

    def test_motion_and_pending_increase_sampling(self):
        self.assertTrue(needs_dense_sampling([face()], [], []))
        self.assertTrue(needs_dense_sampling([face()], [{'state':'pending'}], [face()]))
        self.assertTrue(needs_dense_sampling([face(x=80)], [], [face()]))
        self.assertFalse(needs_dense_sampling([face()], [{'state':'confirmed'}], [face()]))

    def test_classroom_scans_every_tile_and_fast_rotates_one(self):
        engine = HighAccuracyFaceEngine.__new__(HighAccuracyFaceEngine)
        engine.inference_lock = threading.RLock()
        class Detector:
            def __init__(self): self.sizes = []
            def detect(self, frame, input_size):
                self.sizes.append(input_size)
                return np.empty((0,5)), None
        detector = Detector()
        engine.app = SimpleNamespace(det_model=detector)
        frame = np.zeros((1080,1920,3), dtype=np.uint8)
        self.assertEqual(engine.process_frame_video(frame, gallery(), 'classroom'), [])
        self.assertEqual(detector.sizes, [(1280,1280)]+[(960,960)]*6)
        detector.sizes.clear()
        engine.process_frame_video(frame, gallery(), 'fast')
        self.assertEqual(detector.sizes, [(1280,1280),(640,640)])


class FakeCapture:
    def __init__(self, frames, declared_count=None, fps=10, opened=True, missing_pts=False):
        self.frames = frames
        self.count = len(frames) if declared_count is None else declared_count
        self.index = 0
        self.fps, self.opened, self.missing_pts = fps, opened, missing_pts
        self.released = False
    def isOpened(self): return self.opened
    def read(self):
        if self.index >= len(self.frames): return False, None
        frame = self.frames[self.index]
        self.index += 1
        return True, frame
    def get(self, prop):
        import cv2
        return {cv2.CAP_PROP_FPS:self.fps, cv2.CAP_PROP_FRAME_COUNT:self.count,
                cv2.CAP_PROP_POS_MSEC:0 if self.missing_pts else max(0,self.index-1)*100}.get(prop,0)
    def release(self): self.released = True


class VideoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patches = [patch.object(connection,'DB_PATH',str(Path(self.temp.name)/'test.db')),
            patch('services.video_events.SNAPSHOT_DIR',self.temp.name),
            patch('routers.analysis.VIDEO_UPLOAD_DIR',self.temp.name)]
        for p in self.patches: p.start()
        connection.init_db()
        create_video_job('job','test.mp4','/test.mp4', mode='classroom')
        self.frame = np.full((80,160,3),127,dtype=np.uint8)
    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.temp.cleanup()
    def frames(self, count):
        result = []
        for index in range(count):
            frame = self.frame.copy()
            frame[0,0,0] = index % 256
            result.append(frame)
        return result
    def run_worker(self, capture, results=None, before_scan=None):
        class Engine:
            calls = 0
            def process_frame_video(inner, frame, snapshot, mode, tile):
                inner.calls += 1
                if before_scan: before_scan(inner.calls)
                return results(frame) if results else [face(), face(2,x=90)]
        engine = Engine()
        with patch('services.video_worker.cv2.VideoCapture',return_value=capture), patch('services.video_worker.get_ai_engine',return_value=engine):
            analyze_video_background('job','test.mp4', gallery=gallery())
        return engine

    def test_multi_person_early_notifications_then_single_appearance_each(self):
        def inspect_early(call):
            if call == 4:
                self.assertEqual(len(get_video_detections_since('job')),2)
                self.assertEqual(get_video_job('job')['status'],'processing')
        capture = FakeCapture(self.frames(30))
        self.run_worker(capture, before_scan=inspect_early)
        rows = get_video_detections_since('job')
        self.assertEqual(len(rows),2)
        self.assertTrue(all(r['timestamp_sec'] >= .4 for r in rows))
        self.assertTrue(all(r['last_seen_sec'] > 2 for r in rows))
        self.assertTrue(all(Path(self.temp.name,Path(r['scene_path']).name).exists() for r in rows))
        job = get_video_job('job')
        self.assertEqual(job['status'],'completed')
        self.assertEqual(job['processed_frames'],30)
        self.assertLess(job['scanned_frames'],30)
        self.assertEqual(len(json.loads(job['settings_json'])['watchlist']),2)
        self.assertTrue(capture.released)
        samples = get_video_snapshots_since('job')
        for row in rows:
            person_samples = [s for s in samples if s['detection_id'] == row['id']]
            self.assertGreaterEqual(len(person_samples), 1)
            self.assertAlmostEqual(person_samples[-1]['timestamp_sec'], row['last_seen_sec'])

    def test_one_off_match_does_not_create_event(self):
        def results(frame):
            return [face()] if frame[0,0,0] == 0 else []
        self.run_worker(FakeCapture(self.frames(30)), results)
        self.assertEqual(get_video_detections_since('job'),[])

    def test_identical_video_buffers_do_not_confirm(self):
        engine = self.run_worker(FakeCapture([self.frame]*30))
        self.assertEqual(engine.calls,1)
        self.assertEqual(get_video_detections_since('job'),[])

    def test_zero_frame_metadata_still_scans_to_eof(self):
        self.run_worker(FakeCapture(self.frames(15),declared_count=0))
        self.assertEqual(get_video_job('job')['status'],'completed')
        self.assertEqual(get_video_job('job')['total_frames'],15)

    def test_missing_timestamps_have_warning_and_monotonic_events(self):
        self.run_worker(FakeCapture(self.frames(15),missing_pts=True))
        self.assertTrue(get_video_job('job')['warning_message'])
        self.assertGreater(get_video_job('job')['scanned_until_sec'],1)

    def test_empty_or_truncated_video_is_not_success(self):
        self.run_worker(FakeCapture([]))
        self.assertEqual(get_video_job('job')['status'],'error')
        self.run_worker(FakeCapture(self.frames(10),declared_count=100))
        self.assertEqual(get_video_job('job')['status'],'error')
        self.assertTrue(get_video_job('job')['error_message'])

    def test_engine_initialization_failure_is_reported(self):
        with patch('services.video_worker.get_ai_engine',side_effect=RuntimeError('model failed')):
            analyze_video_background('job','test.mp4',gallery=gallery())
        self.assertEqual(get_video_job('job')['status'],'error')
        self.assertIn('model failed',get_video_job('job')['error_message'])

    def test_occlusion_does_not_extend_last_seen_and_reentry_creates_new_event(self):
        recorder = VideoEventRecorder('job')
        recorder.record([face()],self.frame,1)
        recorder.record([face()],self.frame,2)
        recorder.record([{**face(),'state':'lost','confirmed':False}],self.frame,4)
        self.assertEqual(get_video_detections_since('job')[0]['last_seen_sec'],2)
        recorder.record([face()],self.frame,8)
        self.assertEqual(len(get_video_detections_since('job')),2)
        self.assertEqual(get_job_summary('job')['summary'][0]['last_seen'],8)

    def test_failed_evidence_write_does_not_log(self):
        with patch('services.video_events.cv2.imwrite',return_value=False):
            with self.assertRaises(OSError):
                VideoEventRecorder('job').record([face()],self.frame,1)
        self.assertEqual(get_video_detections_since('job'),[])

    def test_periodic_and_final_photos_keep_one_appearance_and_actual_last_frame(self):
        import cv2
        recorder = VideoEventRecorder('job')
        recorder.record([face()], self.frame, 1)
        recorder.record([face()], self.frame, 2.1)
        self.assertEqual(get_video_snapshots_since('job'), [])
        recorder.record([face()], np.full_like(self.frame, 160), 3.05)
        interval = get_video_snapshots_since('job')[0]
        self.assertEqual(interval['kind'], 'interval')
        self.assertEqual(interval['timestamp_sec'], 3.05)
        recorder.record([{**face(), 'zone':'Desks', 'confidence':.85}], np.full_like(self.frame, 180), 4.2)
        recorder.record([{**face(), 'state':'lost', 'confirmed':False}], np.full_like(self.frame, 250), 5.5)
        self.assertEqual(len(get_video_snapshots_since('job')), 1)
        recorder.flush(9.3)
        recorder.flush()
        rows, samples = get_video_detections_since('job'), get_video_snapshots_since('job')
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[-1]['kind'], 'last')
        self.assertEqual(samples[-1]['timestamp_sec'], 4.2)
        self.assertEqual(samples[-1]['zone'], 'Desks')
        self.assertEqual(samples[-1]['confidence'], .85)
        self.assertTrue(all(s['detection_id'] == rows[0]['id'] for s in samples))
        last_face = cv2.imread(str(Path(self.temp.name, Path(samples[-1]['snapshot_path']).name)))
        self.assertAlmostEqual(float(last_face.mean()), 180, delta=1)
        self.assertEqual(rows[0]['last_seen_sec'], 4.2)
        self.assertEqual(get_video_snapshots_since('job', interval['id']), samples[1:])
        self.assertEqual(get_video_snapshots_since('job', max_detection_id=0), [])
        self.assertEqual(get_video_snapshots_since('another-job'), [])
        self.assertEqual(get_job_summary('job')['snapshots'], samples)
        self.assertEqual(recorder.events, {})

    def test_short_appearance_saves_last_photo_and_exact_interval_does_not_duplicate(self):
        recorder = VideoEventRecorder('job')
        recorder.record([face()], self.frame, 1)
        recorder.record([face()], self.frame, 1.3)
        recorder.flush()
        self.assertEqual([s['timestamp_sec'] for s in get_video_snapshots_since('job')], [1.3])
        recorder.record([face()], self.frame, 8)
        recorder.record([face()], self.frame, 10)
        recorder.flush()
        self.assertEqual([s['timestamp_sec'] for s in get_video_snapshots_since('job')], [1.3, 10])
        self.assertEqual(len(get_video_detections_since('job')), 2)

    def test_poll_cursor_does_not_skip_photos_for_an_appearance_created_mid_poll(self):
        recorder = VideoEventRecorder('job')
        recorder.record([face()], self.frame, 1)
        first_id = get_video_detections_since('job')[0]['id']
        recorder.record([face(), face(2, x=90)], self.frame, 2)
        recorder.record([face(2, x=90)], self.frame, 4)
        recorder.record([face()], self.frame, 4.1)
        # The second person's sample commits before another sample for the first person.
        self.assertEqual(get_video_snapshots_since('job', max_detection_id=first_id), [])
        samples = get_video_snapshots_since('job')
        self.assertEqual([s['person_id'] for s in samples], [2, 1])
        latest_id = get_video_detections_since('job')[-1]['id']
        self.assertEqual(get_video_snapshots_since('job', max_detection_id=latest_id), samples)

    def test_extra_photo_failure_preserves_first_photo_and_cleans_partial_files(self):
        recorder = VideoEventRecorder('job')
        recorder.record([face()], self.frame, 1)
        original_files = set(Path(self.temp.name).glob('*.jpg'))
        with patch('services.video_events.add_video_snapshot', side_effect=RuntimeError('database failed')):
            with self.assertRaisesRegex(RuntimeError, 'database failed'):
                recorder.record([face()], self.frame, 3)
        self.assertEqual(set(Path(self.temp.name).glob('*.jpg')), original_files)
        self.assertEqual(get_video_snapshots_since('job'), [])
        self.assertEqual(len(get_video_detections_since('job')), 1)
        recorder.flush()
        self.assertEqual(len(get_video_snapshots_since('job')), 1)

    def test_restart_marks_unfinished_jobs_without_losing_events(self):
        VideoEventRecorder('job').record([face()],self.frame,1)
        create_video_job('done','done.mp4','/done.mp4')
        set_video_job_details('done',status='completed')
        mark_interrupted_video_jobs()
        self.assertEqual(get_video_job('job')['status'],'error')
        self.assertTrue(get_video_job('job')['error_message'])
        self.assertEqual(len(get_video_detections_since('job')),1)
        self.assertEqual(get_video_job('done')['status'],'completed')

    def test_upload_api_snapshots_enabled_watchlist_and_validates_inputs(self):
        app = FastAPI(); app.include_router(router)
        with closing(connection.get_db()) as conn, conn:
            conn.execute("INSERT INTO persons (id,name,search_enabled) VALUES (1,'A',1),(2,'Off',0)")
            for pid, vector in ((1,[1.,0.]),(2,[0.,1.])):
                conn.execute('INSERT INTO face_embeddings(person_id,embedding) VALUES (?,?)',(pid,json.dumps(vector)))
        async def check():
            async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
                with patch('routers.analysis.analyze_video_background') as worker:
                    response = await client.post('/api/analyze_video', files={'file':('test.mp4',b'fake video')}, data={'mode':'classroom'})
                    self.assertEqual(response.status_code,200,response.text)
                    body = response.json()
                    self.assertEqual([p['name'] for p in body['watchlist']],['A'])
                    self.assertEqual(worker.call_args.kwargs['gallery'].watchlist[0]['name'],'A')
                    saved = get_video_job(body['job_id'])
                    self.assertEqual(json.loads(saved['settings_json'])['watchlist'][0]['id'],1)
                invalid = await client.post('/api/analyze_video',files={'file':('a.mp4',b'x')},data={'mode':'wrong'})
                self.assertEqual(invalid.status_code,422)
                invalid = await client.post('/api/analyze_video',files={'file':('a.mp4',b'x')},data={'zones_json':'invalid'})
                self.assertEqual(invalid.status_code,422)
                empty = await client.post('/api/analyze_video',files={'file':('a.mp4',b'')})
                self.assertEqual(empty.status_code,400)
                with closing(connection.get_db()) as conn, conn: conn.execute('UPDATE persons SET search_enabled=0')
                disabled = await client.post('/api/analyze_video',files={'file':('a.mp4',b'x')})
                self.assertEqual(disabled.status_code,400)
                events = await client.get('/api/video_analysis/job/events')
                self.assertEqual(events.status_code,200)
                self.assertIn('appearance_updates',events.json())
                recorder = VideoEventRecorder('job')
                recorder.record([face()], self.frame, 1)
                recorder.record([face()], self.frame, 3)
                recorder.record([face()], self.frame, 3.5)
                recorder.flush()
                events = (await client.get('/api/video_analysis/job/events')).json()
                self.assertEqual(len(events['new_detections']), 1)
                self.assertEqual(len(events['new_snapshots']), 2)
                params = {'last_id': events['last_id'], 'last_snapshot_id': events['last_snapshot_id']}
                next_events = (await client.get('/api/video_analysis/job/events', params=params)).json()
                self.assertEqual(next_events['new_detections'], [])
                self.assertEqual(next_events['new_snapshots'], [])
                summary = (await client.get('/api/video_analysis/job/summary')).json()
                self.assertEqual(len(summary['snapshots']), 2)
        asyncio.run(check())


if __name__ == '__main__':
    unittest.main()
