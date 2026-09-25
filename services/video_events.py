"""Store confirmed appearances and evidence before reporting a new event."""
import os
import uuid
import cv2
from config import SNAPSHOT_DIR, VIDEO_REENTRY_SECONDS, VIDEO_SNAPSHOT_INTERVAL_SECONDS
from db.jobs_repo import add_video_detection, add_video_snapshot, update_video_appearance


def video_time(seconds):
    milliseconds = max(0, round(seconds * 1000))
    minutes, remainder = divmod(milliseconds, 60000)
    return f'{minutes:02d}:{remainder//1000:02d}.{remainder%1000:03d}'


class VideoEventRecorder:
    def __init__(self, job_id):
        self.job_id = job_id
        self.events = {}

    def record(self, detections, frame, timestamp_sec):
        self.flush(timestamp_sec)
        confirmed = {}
        for det in detections:
            if det.get('confirmed') and det.get('state') == 'confirmed' and det.get('person_id') is not None:
                pid = det['person_id']
                if pid not in confirmed or det['confidence'] > confirmed[pid]['confidence']:
                    confirmed[pid] = det
        created = 0
        for pid, det in confirmed.items():
            previous = self.events.get(pid)
            if previous:
                previous.update(last_seen=timestamp_sec, zone=det.get('zone', 'Toàn cảnh'),
                                latest_frame=frame, latest_det=det)
                if timestamp_sec - previous['last_snapshot'] >= VIDEO_SNAPSHOT_INTERVAL_SECONDS:
                    self._save_snapshot(previous, 'interval')
                continue
            paths = []
            try:
                paths, face_path, scene_path = self._write_evidence(det, frame)
                event_id = add_video_detection(
                    job_id=self.job_id, person_id=pid, person_name=det['name'],
                    confidence=det['confidence'], timestamp_sec=timestamp_sec,
                    timestamp_str=video_time(timestamp_sec), first_seen_sec=det.get('first_seen_mono', timestamp_sec),
                    snapshot_path=face_path, scene_path=scene_path,
                    zone=det.get('zone', 'Toàn cảnh'), track_id=det['track_id'],
                    confirmation_delay_sec=max(0, timestamp_sec-det.get('first_seen_mono', timestamp_sec)))
                self.events[pid] = dict(id=event_id, last_seen=timestamp_sec, written=timestamp_sec,
                                        zone=det.get('zone', 'Toàn cảnh'), last_snapshot=timestamp_sec)
                created += 1
            except Exception:
                for path in paths:
                    if os.path.isfile(path):
                        os.remove(path)
                raise
        self.flush(timestamp_sec)
        return created

    def flush(self, timestamp_sec=None):
        for pid, event in list(self.events.items()):
            finished = timestamp_sec is None or timestamp_sec - event['last_seen'] > VIDEO_REENTRY_SECONDS
            if finished and event['last_seen'] > event['last_snapshot'] + 1e-6:
                self._save_snapshot(event, 'last')
            if event['last_seen'] > event['written'] and (timestamp_sec is None or timestamp_sec-event['written'] >= 0.5):
                update_video_appearance(event['id'], event['last_seen'], event['zone'])
                event['written'] = event['last_seen']
            if finished:
                del self.events[pid]

    def _write_evidence(self, det, frame):
        token = f'{self.job_id}_{uuid.uuid4().hex}'
        face_name, scene_name = token + '_face.jpg', token + '_scene.jpg'
        x1, y1, x2, y2 = det['bbox']
        crop = frame[max(0, y1):min(frame.shape[0], y2), max(0, x1):min(frame.shape[1], x2)]
        if crop.size == 0:
            raise ValueError('Không có ảnh mặt để lưu bằng chứng')
        os.makedirs(SNAPSHOT_DIR, exist_ok=True)
        paths = []
        try:
            for name, image in ((face_name, crop), (scene_name, frame)):
                path = os.path.join(SNAPSHOT_DIR, name)
                paths.append(path)
                if not cv2.imwrite(path, image):
                    raise OSError('Không lưu được ảnh bằng chứng video')
        except Exception:
            for path in paths:
                if os.path.isfile(path):
                    os.remove(path)
            raise
        return paths, f'static/snapshots/{face_name}', f'static/snapshots/{scene_name}'

    def _save_snapshot(self, event, kind):
        # Keep just the latest confirmed frame per active person. Unknown/lost observations
        # never replace it, so the final evidence uses the actual last confirmed moment.
        det = event['latest_det']
        paths, face_path, scene_path = self._write_evidence(det, event['latest_frame'])
        try:
            add_video_snapshot(event['id'], event['last_seen'], video_time(event['last_seen']),
                               det['confidence'], face_path, scene_path, event['zone'], kind)
        except Exception:
            for path in paths:
                if os.path.isfile(path):
                    os.remove(path)
            raise
        event['last_snapshot'] = event['last_seen']
        event.pop('latest_frame', None)
        event.pop('latest_det', None)
