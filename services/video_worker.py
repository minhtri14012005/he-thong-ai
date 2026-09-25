"""Sequential video decoding, adaptive sampling and early confirmed events."""
import json
import math
import time
import zlib
import cv2
from config import (VIDEO_SCAN_PROFILES, VIDEO_BURST_HOLD_SECONDS, VIDEO_REENTRY_SECONDS,
                    LIVE_MIN_FACE_PIXELS, LIVE_MIN_SHARPNESS, LIVE_CONFIRM_HITS,
                    LIVE_CONFIRM_WINDOW, LIVE_CONFIRM_SECONDS, VIDEO_SNAPSHOT_INTERVAL_SECONDS)
from core.engine import get_ai_engine
from core.gallery import GallerySnapshot
from core.live_tracker import LiveTracker
from core.live_zones import find_zone, validate_zones
from core.tracker import compute_iou
from db.persons_repo import load_live_gallery
from db.jobs_repo import set_video_job_details
from services.video_events import VideoEventRecorder


def video_settings(gallery, mode, zones):
    return {**gallery.audit(), 'mode': mode, 'profile': dict(VIDEO_SCAN_PROFILES[mode]),
            'zones': zones, 'model': 'buffalo_l', 'min_face_pixels': LIVE_MIN_FACE_PIXELS,
            'min_sharpness': LIVE_MIN_SHARPNESS, 'confirm_hits': LIVE_CONFIRM_HITS,
            'confirm_window': LIVE_CONFIRM_WINDOW, 'confirm_seconds': LIVE_CONFIRM_SECONDS,
            'reentry_seconds': VIDEO_REENTRY_SECONDS,
            'snapshot_interval_seconds': VIDEO_SNAPSHOT_INTERVAL_SECONDS}


def needs_dense_sampling(raw, tracked, previous):
    if any(d['state'] == 'pending' for d in tracked):
        return True
    # New or displaced boxes include people outside the watchlist who may occlude a target.
    return any(not previous or max(compute_iou(d['bbox'], old['bbox']) for old in previous) < 0.65
               for d in raw)


def analyze_video_background(job_id, video_path, mode='detailed', gallery=None, zones=None):
    cap = None
    recorder = VideoEventRecorder(job_id)
    started = time.monotonic()
    decoded = scanned = total = 0
    timestamp = 0.0
    warnings = set()
    progress = 0
    try:
        mode = 'detailed' if mode == 'classroom' else mode
        profile = VIDEO_SCAN_PROFILES[mode]
        gallery = gallery if gallery is not None else GallerySnapshot(load_live_gallery())
        zones = validate_zones(zones or [])
        if not gallery.watchlist:
            raise ValueError('Chưa có người đang bật tìm kiếm với ảnh mẫu hợp lệ')
        set_video_job_details(job_id, status='processing', mode=mode, error_message=None,
                              settings_json=json.dumps(video_settings(gallery, mode, zones), ensure_ascii=False))
        engine = get_ai_engine()
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError('Không mở được video; hãy kiểm tra định dạng hoặc file bị lỗi')
        fps = cap.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps <= 0:
            fps = 25.0
            warnings.add('Không đọc được FPS; mốc thời gian dự phòng dùng 25 FPS.')
        count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        total = int(count) if math.isfinite(count) and count > 0 else 0
        set_video_job_details(job_id, source_fps=fps, total_frames=total,
                              duration_sec=total/fps if total else 0)
        tracker = LiveTracker()
        next_scan = 0.0
        burst_until = -1.0
        previous = []
        last_hash = None
        first_pts = previous_pts = None
        last_progress = 0.0
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            index = decoded
            decoded += 1
            pts = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if first_pts is None:
                first_pts = pts if math.isfinite(pts) and pts >= 0 else 0.0
            if index == 0:
                timestamp = 0.0
                set_video_job_details(job_id, frame_width=frame.shape[1], frame_height=frame.shape[0])
            elif math.isfinite(pts) and previous_pts is not None and pts > previous_pts and pts-first_pts > timestamp:
                timestamp = pts-first_pts
            else:
                timestamp = max(timestamp + 1.0/fps, index/fps)
                warnings.add('Có mốc thời gian thiếu hoặc không tăng; đã dùng FPS dự phòng cho các frame đó.')
            previous_pts = pts if math.isfinite(pts) else None
            if timestamp + 1e-6 >= next_scan:
                scanned += 1
                signature = zlib.adler32(frame)
                if signature != last_hash:
                    raw = engine.process_frame_video(frame, gallery, mode, scanned-1)
                    tracked = tracker.update(raw, timestamp)
                    for det in tracked:
                        det['zone'] = find_zone(det['bbox'], frame.shape, zones)
                    # Committed here, before later frames are decoded or the job completes.
                    recorder.record(tracked, frame, timestamp)
                    if needs_dense_sampling(raw, tracked, previous):
                        burst_until = timestamp + VIDEO_BURST_HOLD_SECONDS
                    previous = raw
                    last_hash = signature
                else:
                    tracker.update([], timestamp)
                    recorder.flush(timestamp)
                scan_fps = profile['burst_fps'] if timestamp <= burst_until else profile['sample_fps']
                next_scan = timestamp + 1.0/min(fps, scan_fps)
            progress = min(99, int(decoded/max(1,total)*100)) if total else 0
            if time.monotonic()-last_progress >= 0.3:
                set_video_job_details(job_id, progress=progress, processed_frames=decoded,
                    scanned_frames=scanned, scanned_until_sec=timestamp, elapsed_sec=time.monotonic()-started,
                    warning_message=' '.join(sorted(warnings)) or None)
                last_progress = time.monotonic()
        recorder.flush()
        if decoded == 0:
            raise ValueError('Video không có khung hình đọc được')
        if total and decoded < total-max(2, int(total*.02)):
            raise ValueError(f'Video kết thúc sớm: đọc được {decoded}/{total} frame. Kết quả hiện có chỉ là một phần.')
        set_video_job_details(job_id, status='completed', progress=100, processed_frames=decoded,
            total_frames=decoded, scanned_frames=scanned, scanned_until_sec=timestamp,
            duration_sec=timestamp+1.0/fps, elapsed_sec=time.monotonic()-started,
            warning_message=' '.join(sorted(warnings)) or None)
    except Exception as exc:
        set_video_job_details(job_id, status='error', progress=progress, error_message=str(exc),
            processed_frames=decoded, scanned_frames=scanned, scanned_until_sec=timestamp,
            elapsed_sec=time.monotonic()-started)
    finally:
        if cap is not None:
            cap.release()
