"""One capture and inference worker per active source, shared by all viewers."""
import os
import time
import threading
import zlib
from collections import deque
import cv2
import numpy as np
from config import (IPHONE_CAM_WIDTH, IPHONE_CAM_HEIGHT, WEBCAM_WIDTH, WEBCAM_HEIGHT,
                    DEFAULT_AUTO_ZOOM, LIVE_CAMERA_STALE_SECONDS, LIVE_TARGET_AI_FPS)
from core.engine import get_ai_engine
from core.hardware import get_camera_device_index
from core.live_tracker import LiveTracker
from core.live_zones import load_zones, find_zone
from core.zoom import SmoothZoomController
from services.live_events import LiveEventRecorder
from utils.text_utils import remove_accents


class ThreadedCameraReader:
    def __init__(self, source='iphone', ip='', video_path=None):
        self.source, self.ip, self.video_path = source, ip, video_path
        self.cap = None
        self.lock = threading.Lock()
        self.latest_frame = None
        self.sequence = 0
        self.captured_at = self.captured_mono = 0.0
        self.capture_fps = 0.0
        self.is_running = False
        self.thread = None
        self._stop = threading.Event()
        self._init_capture()

    def _init_capture(self):
        if self.source == 'file':
            if self.video_path and os.path.isfile(self.video_path):
                self.cap = cv2.VideoCapture(self.video_path)
        elif self.source == 'ip_cam':
            url = self.ip.strip()
            if not url.startswith(('http://', 'https://', 'rtsp://')):
                url = f'http://{url}:4747/video'
            self.cap = cv2.VideoCapture(url)
        else:
            index = get_camera_device_index(self.source)
            for _ in range(3):
                self.cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
                if self.cap.isOpened():
                    break
                self.cap.release()
                time.sleep(0.12)
            if self.cap and self.cap.isOpened():
                if self.source == 'iphone':
                    width, height = IPHONE_CAM_WIDTH, IPHONE_CAM_HEIGHT
                else:
                    width, height = WEBCAM_WIDTH, WEBCAM_HEIGHT
                    self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        if self.cap and self.cap.isOpened():
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.is_running = True
            self.thread = threading.Thread(target=self._capture_loop, daemon=True)
            self.thread.start()

    def _capture_loop(self):
        cap = self.cap
        last_hash, count, start = None, 0, time.monotonic()
        file_fps = cap.get(cv2.CAP_PROP_FPS) or 25
        try:
            while not self._stop.is_set():
                success, frame = cap.read()
                if not success:
                    if self.source == 'file':
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    self._stop.wait(0.02)
                    continue
                now = time.monotonic()
                # Some virtual cameras repeat the same buffer after disconnection.
                signature = zlib.adler32(frame)
                if signature != last_hash:
                    with self.lock:
                        self.latest_frame = frame
                        self.sequence += 1
                        self.captured_at, self.captured_mono = time.time(), now
                    last_hash = signature
                    count += 1
                if now - start >= 1.0:
                    self.capture_fps = count / (now - start)
                    count, start = 0, now
                self._stop.wait(1.0 / max(1, file_fps) if self.source == 'file' else 0.002)
        finally:
            self.is_running = False
            cap.release()

    def packet(self):
        with self.lock:
            return (None if self.latest_frame is None else self.latest_frame.copy(),
                    self.sequence, self.captured_at, self.captured_mono)

    def read(self):
        frame, _, _, captured_mono = self.packet()
        return frame is not None and time.monotonic() - captured_mono <= LIVE_CAMERA_STALE_SECONDS, frame

    def is_opened(self):
        return self.is_running and self.cap is not None and self.cap.isOpened()

    def stop(self):
        self._stop.set()
        if self.thread:
            self.thread.join(timeout=2.0)
        if not self.thread and self.cap:
            self.cap.release()
        self.is_running = False


class StreamService:
    def __init__(self):
        self.is_paused = False
        self.uploaded_video_path = None
        self.auto_zoom_enabled = DEFAULT_AUTO_ZOOM
        self.current_source = self.current_ip = None
        self.active_reader = None
        self.retired_reader = None
        self.camera_lock = threading.RLock()
        self.state_lock = threading.Lock()
        self.worker = None
        self.worker_stop = threading.Event()
        self.generation = 0
        self.confirmation_revision = 0
        self.zones = load_zones()
        self.recorder = LiveEventRecorder()
        self.state = {'detections': [], 'ai_fps': 0.0, 'ai_ms': 0.0, 'error': None,
                      'processed_mono': 0.0, 'providers': {}}

    def pause(self):
        with self.state_lock:
            self.is_paused = True
            self.confirmation_revision += 1

    def resume(self):
        self.is_paused = False

    def _stop_locked(self):
        self.worker_stop.set()
        self.generation += 1
        if self.worker:
            self.worker.join(timeout=3.0)
        if self.active_reader:
            self.active_reader.stop()
            self.retired_reader = self.active_reader
        self.active_reader = None
        self.current_source = self.current_ip = None
        with self.state_lock:
            self.state.update(detections=[], ai_fps=0.0, ai_ms=0.0, processed_mono=0.0)

    def stop(self):
        with self.camera_lock:
            self._stop_locked()
            self.is_paused = False

    def set_auto_zoom(self, enabled):
        self.auto_zoom_enabled = bool(enabled)
        return self.auto_zoom_enabled

    def set_uploaded_video(self, path):
        self.stop()
        self.uploaded_video_path = path

    def switch_camera_source(self, source='iphone', ip=''):
        if source not in ('iphone', 'webcam', 'ip_cam', 'file'):
            raise ValueError('Nguồn camera không hợp lệ')
        with self.camera_lock:
            if (self.active_reader and self.active_reader.is_opened()
                    and self.current_source == source and self.current_ip == ip
                    and self.worker and self.worker.is_alive()):
                self.resume()
                return True
            self._stop_locked()
            if self.worker and self.worker.is_alive():
                raise RuntimeError('AI đang hoàn tất lượt quét trước; hãy kết nối lại sau vài giây')
            if self.retired_reader and self.retired_reader.thread and self.retired_reader.thread.is_alive():
                raise RuntimeError('Camera cũ chưa giải phóng xong; hãy kiểm tra Iriun và kết nối lại')
            time.sleep(0.12)
            reader = ThreadedCameraReader(source, ip, self.uploaded_video_path)
            if not reader.is_opened():
                reader.stop()
                with self.state_lock:
                    self.state['error'] = 'Không mở được camera. Kiểm tra Iriun và kết nối.'
                return False
            self.active_reader = reader
            self.current_source, self.current_ip = source, ip
            self.is_paused = False
            self.worker_stop = threading.Event()
            with self.state_lock:
                self.state['error'] = None
            self.worker = threading.Thread(target=self._ai_loop,
                args=(reader, self.worker_stop, self.generation, source), daemon=True)
            self.worker.start()
            return True

    def _ai_loop(self, reader, stop_event, generation, source):
        try:
            engine = get_ai_engine()
            with self.state_lock:
                self.state['providers'] = engine.runtime_providers()
            tracker, last_sequence, tile, gallery_version = LiveTracker(), -1, 0, -1
            completions = deque(maxlen=20)
            while not stop_event.is_set():
                if self.is_paused:
                    tracker = LiveTracker()
                    completions.clear()
                    stop_event.wait(0.05)
                    continue
                frame, sequence, captured_at, captured_mono = reader.packet()
                if frame is None or time.monotonic() - captured_mono > LIVE_CAMERA_STALE_SECONDS:
                    tracker = LiveTracker()
                    completions.clear()
                    with self.state_lock:
                        self.state['detections'] = []
                    stop_event.wait(0.05)
                    continue
                if sequence == last_sequence:
                    stop_event.wait(0.01)
                    continue
                last_sequence = sequence
                started = time.monotonic()
                try:
                    with engine.inference_lock:
                        revision = (engine.gallery_version, self.confirmation_revision)
                        if gallery_version != revision:
                            tracker = LiveTracker()
                            gallery_version = revision
                        raw = engine.process_frame_live(frame, tile)
                    tile += 1
                    if stop_event.is_set() or generation != self.generation or self.is_paused:
                        continue
                    if time.monotonic() - captured_mono > LIVE_CAMERA_STALE_SECONDS:
                        with self.state_lock:
                            self.state.update(detections=[], error='AI xử lý chậm: bỏ kết quả đã quá cũ')
                        continue
                    detections = tracker.update(raw, captured_mono)
                    for det in detections:
                        det['zone'] = find_zone(det['bbox'], frame.shape, self.zones)
                        det['first_seen_at'] = captured_at - (captured_mono - det.pop('first_seen_mono', captured_mono))
                    with self.state_lock:
                        if stop_event.is_set() or self.is_paused or revision != (engine.gallery_version, self.confirmation_revision):
                            continue
                        self.recorder.record(detections, frame, source, captured_at)
                        elapsed = max(1e-6, time.monotonic() - started)
                        completions.append(time.monotonic())
                        measured_fps = ((len(completions)-1)/(completions[-1]-completions[0])
                                        if len(completions) > 1 else 0.0)
                        self.state.update(detections=detections, ai_ms=round(elapsed*1000, 1),
                            ai_fps=round(measured_fps, 1),
                            processed_mono=captured_mono, error=None)
                except Exception as exc:
                    with self.state_lock:
                        self.state.update(error=str(exc), detections=[])
                    stop_event.wait(0.2)
                stop_event.wait(max(0, 1.0/LIVE_TARGET_AI_FPS - (time.monotonic()-started)))
        except Exception as exc:
            with self.state_lock:
                self.state.update(error=str(exc), detections=[])

    def status(self):
        reader = self.active_reader
        with self.state_lock:
            state = {**self.state, 'detections': list(self.state['detections'])}
        now = time.monotonic()
        age = now - reader.captured_mono if reader and reader.captured_mono else None
        fresh = bool(reader and reader.is_opened() and age is not None and age <= LIVE_CAMERA_STALE_SECONDS)
        ai_fresh = bool(state['processed_mono'] and now - state['processed_mono'] <= LIVE_CAMERA_STALE_SECONDS)
        if not fresh or not ai_fresh or self.is_paused:
            state['detections'] = []
            state['ai_fps'] = 0.0
        shape = reader.latest_frame.shape if reader and reader.latest_frame is not None else None
        state.update(source=self.current_source, paused=self.is_paused, connected=fresh,
                     resolution=[shape[1], shape[0]] if shape else None,
                     capture_fps=round(reader.capture_fps, 1) if fresh else 0,
                     frame_age_ms=round(age*1000) if age is not None else None,
                     zones=self.zones, auto_zoom=self.auto_zoom_enabled)
        state.pop('processed_mono', None)
        return state

    def generate_video_stream(self, source='iphone', ip='', auto_zoom=None):
        if auto_zoom is not None:
            self.set_auto_zoom(auto_zoom)
        if not (self.active_reader and self.current_source == source and self.current_ip == ip):
            if not self.switch_camera_source(source, ip):
                return
        reader, generation = self.active_reader, self.generation
        zoom = SmoothZoomController()
        last_frame = None
        while reader is self.active_reader and generation == self.generation:
            started = time.monotonic()
            valid, frame = reader.read()
            if self.is_paused and last_frame is not None:
                display = last_frame.copy()
                cv2.putText(display, 'TAM DUNG - KHONG GHI LOG', (20, 35),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 190, 255), 2)
            elif valid:
                detections = self.status()['detections']
                display, adjusted, _ = zoom.update_and_zoom(frame, detections, self.auto_zoom_enabled)
                for original, drawn in zip(detections, adjusted):
                    x1, y1, x2, y2 = drawn['bbox']
                    state = original['state']
                    color = (0, 210, 0) if state == 'confirmed' else (0, 190, 255)
                    if state == 'lost':
                        color = (140, 140, 140)
                    label = (original['name'] if state == 'confirmed' else
                             ('Tam mat dau' if state == 'lost' else 'Dang xac nhan' if state == 'pending'
                              else original.get('quality_reason') or 'Unknown'))
                    cv2.rectangle(display, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(display, remove_accents(label), (x1, max(15, y1-8)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
                if not self.auto_zoom_enabled:
                    for zone in self.zones:
                        h, w = display.shape[:2]
                        x1, y1, x2, y2 = zone['rect']
                        cv2.rectangle(display, (int(x1*w), int(y1*h)), (int(x2*w), int(y2*h)), (200, 160, 0), 1)
                        cv2.putText(display, remove_accents(zone['name']), (int(x1*w)+4, int(y1*h)+18),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 160, 0), 1)
                last_frame = display.copy()
            else:
                display = np.zeros((720, 1280, 3), dtype=np.uint8)
                cv2.putText(display, 'Mat tin hieu / dang cho camera', (40, 100),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 190, 255), 2)
            h, w = display.shape[:2]
            scale = min(1.0, 1280/w, 720/h)
            if scale < 1:
                display = cv2.resize(display, (int(w*scale), int(h*scale)))
            ok, buffer = cv2.imencode('.jpg', display, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n'
            time.sleep(max(0, 1/30 - (time.monotonic()-started)))


stream_service = StreamService()
