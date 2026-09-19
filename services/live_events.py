"""Appearance events written from fresh confirmed AI results, never rendering."""
import os
import uuid
from datetime import datetime
import cv2
from config import SNAPSHOT_DIR, LIVE_REENTRY_SECONDS
from db.connection import get_db


def timestamp(epoch):
    return datetime.fromtimestamp(epoch).isoformat(sep=' ', timespec='milliseconds')


class LiveEventRecorder:
    def __init__(self):
        self.events = {}

    def record(self, detections, frame, source, captured_at):
        # One event per identity even if duplicate tracks survive in this frame.
        confirmed = {}
        for det in detections:
            if det.get('confirmed') and det.get('state') == 'confirmed':
                pid = det['person_id']
                if pid not in confirmed or det['confidence'] > confirmed[pid]['confidence']:
                    confirmed[pid] = det
        for pid, det in confirmed.items():
            key = (source, pid)
            previous = self.events.get(key)
            continuing = previous and captured_at - previous['last_seen'] <= LIVE_REENTRY_SECONDS
            conn = get_db()
            paths = []
            try:
                if continuing:
                    previous['last_seen'] = captured_at
                    if captured_at - previous['last_written'] < 1.0:
                        continue
                    # Persist latest evidence time even when no new appearance is created.
                    cursor = conn.execute('''UPDATE detection_logs SET last_seen_at=?,
                        last_zone=? WHERE id=? AND person_id=? AND source=?''',
                        (timestamp(captured_at), det.get('zone'), previous['id'], pid, source))
                    if cursor.rowcount:
                        conn.commit()
                        previous['last_seen'] = captured_at
                        previous['last_written'] = captured_at
                        continue
                os.makedirs(SNAPSHOT_DIR, exist_ok=True)
                token = 'live_' + uuid.uuid4().hex
                scene_path = os.path.join(SNAPSHOT_DIR, token + '.jpg')
                face_path = os.path.join(SNAPSHOT_DIR, token + '_face.jpg')
                x1, y1, x2, y2 = det['bbox']
                crop = frame[max(0, y1):min(frame.shape[0], y2), max(0, x1):min(frame.shape[1], x2)]
                if not crop.size:
                    raise ValueError('Không có ảnh khuôn mặt để lưu bằng chứng')
                for path, img in ((scene_path, frame), (face_path, crop)):
                    paths.append(path)
                    if not cv2.imwrite(path, img):
                        raise OSError('Không lưu được ảnh bằng chứng')
                cursor = conn.execute('''INSERT INTO detection_logs
                    (person_id, person_name, confidence, detected_at, source, zone, last_zone,
                     first_seen_at, last_seen_at, snapshot_path, face_path, track_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (pid, det['name'], det['confidence'], timestamp(captured_at), source,
                     det.get('zone', 'Toàn cảnh'), det.get('zone', 'Toàn cảnh'), timestamp(det.get('first_seen_at', captured_at)),
                     timestamp(captured_at), '/static/snapshots/' + token + '.jpg',
                     '/static/snapshots/' + token + '_face.jpg', det['track_id']))
                conn.commit()
                self.events[key] = {'id': cursor.lastrowid, 'last_seen': captured_at, 'last_written': captured_at}
            except Exception:
                conn.rollback()
                for path in paths:
                    if os.path.isfile(path):
                        os.remove(path)
                raise
            finally:
                conn.close()
        self.events = {k: v for k, v in self.events.items()
                       if captured_at - v['last_seen'] <= LIVE_REENTRY_SECONDS}
