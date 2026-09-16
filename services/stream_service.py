import os
import time
import threading
import cv2
import numpy as np

from config import (
    IPHONE_CAM_WIDTH,
    IPHONE_CAM_HEIGHT,
    WEBCAM_WIDTH,
    WEBCAM_HEIGHT,
    DEFAULT_AUTO_ZOOM
)
from core.engine import get_ai_engine
from core.hardware import get_camera_device_index
from core.tracker import FaceTracker
from db.logs_repo import log_detection
from utils.text_utils import remove_accents


class ThreadedCameraReader:
    """
    Luồng đọc Camera phần cứng độc lập (Zero-lag Dedicated Capture Thread):
    - Khởi tạo camera với chuẩn DirectShow và MJPG để đạt độ phân giải cao (2K/1080p).
    - Liên tục đọc khung hình mới nhất vào RAM, tự động hủy bỏ các frame cũ.
    - Đảm bảo độ trễ camera luôn bằng 0ms, không bao giờ bị nghẽn bởi tiến trình AI.
    """
    def __init__(self, source: str = "webcam", ip: str = "", video_path: str = None):
        self.source = source
        self.ip = ip
        self.video_path = video_path

        self.cap = None
        self.is_running = False
        self.lock = threading.Lock()
        self.latest_frame = None
        self.grabbed = False
        self.thread = None

        self._init_capture()

    def _init_capture(self):
        if self.source == "file":
            if self.video_path and os.path.exists(self.video_path):
                self.cap = cv2.VideoCapture(self.video_path)
        elif self.source == "iphone":
            target_idx = get_camera_device_index("iphone")
            self.cap = cv2.VideoCapture(target_idx, cv2.CAP_DSHOW)
            if not self.cap.isOpened():
                self.cap = cv2.VideoCapture(target_idx)
            if self.cap.isOpened():
                # Kích hoạt MJPG để truyền mượt mà 2K / 1080p từ iPhone 13 qua Iriun
                self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, IPHONE_CAM_WIDTH)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, IPHONE_CAM_HEIGHT)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        elif self.source == "ip_cam":
            cam_url = self.ip.strip() if self.ip.strip() else "192.168.1.15"
            if not (cam_url.startswith("http://") or cam_url.startswith("https://") or cam_url.startswith("rtsp://")):
                cam_url = f"http://{cam_url}:4747/video"
            self.cap = cv2.VideoCapture(cam_url)
            if self.cap.isOpened():
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        else:  # source == "webcam"
            target_idx = get_camera_device_index("webcam")
            self.cap = cv2.VideoCapture(target_idx, cv2.CAP_DSHOW)
            if not self.cap.isOpened():
                self.cap = cv2.VideoCapture(target_idx)
            if self.cap.isOpened():
                self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, WEBCAM_WIDTH)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, WEBCAM_HEIGHT)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if self.cap and self.cap.isOpened():
            self.is_running = True
            self.thread = threading.Thread(target=self._capture_loop, daemon=True)
            self.thread.start()

    def _capture_loop(self):
        while self.is_running and self.cap and self.cap.isOpened():
            success, frame = self.cap.read()
            if not success:
                if self.source == "file":
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    time.sleep(0.01)
                    continue
                else:
                    time.sleep(0.02)
                    continue

            with self.lock:
                self.latest_frame = frame
                self.grabbed = True

            # Cho phép nhường CPU một khoảng cực nhỏ để các luồng khác không bị nghẽn
            time.sleep(0.002)

    def read(self):
        """Lấy khung hình mới nhất từ camera"""
        with self.lock:
            if not self.grabbed or self.latest_frame is None:
                return False, None
            return True, self.latest_frame.copy()

    def is_opened(self):
        return self.cap is not None and self.cap.isOpened()

    def stop(self):
        self.is_running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=0.5)
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None


class StreamService:
    """
    Quản lý luồng video thời gian thực chuẩn công nghiệp cho phòng học:
    - Threaded Camera Reader: Đọc độc lập, triệt tiêu giật lag (Zero-lag).
    - Async GPU AI Worker: Suy luận trên NVIDIA RTX 4050 ở nền bất đồng bộ.
    - Face Tracker: Theo dõi IoU và làm mượt EMA, chống nhấp nháy khung bọc khi học sinh di chuyển.
    - Smooth Auto-Zoom: Tự động điều chỉnh góc nhìn cận cảnh học sinh.
    - Debounce Logging: Ghi nhận diện vào CSDL thông minh, không spam.
    """
    def __init__(self):
        self.is_paused = False
        self.uploaded_video_path = None
        self.auto_zoom_enabled = DEFAULT_AUTO_ZOOM

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False

    def stop(self):
        self.is_paused = False
        self.uploaded_video_path = None

    def set_auto_zoom(self, enabled: bool):
        """Cập nhật trạng thái Auto-Zoom trực tiếp tức thì (Zero-Lag, không ngắt stream camera)"""
        self.auto_zoom_enabled = bool(enabled)
        print(f"[StreamService] Trang thai Auto-Zoom cap nhat runtime: {self.auto_zoom_enabled}")
        return self.auto_zoom_enabled


    def set_uploaded_video(self, path: str):
        self.uploaded_video_path = path
        self.is_paused = False

    def generate_video_stream(self, source: str = "webcam", ip: str = "", auto_zoom: bool = None):
        self.is_paused = False
        if auto_zoom is not None:
            self.auto_zoom_enabled = bool(auto_zoom)

        reader = ThreadedCameraReader(source=source, ip=ip, video_path=self.uploaded_video_path)

        if not reader.is_opened():
            err_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            msg = f"Khong the ket noi: {source}"
            cv2.putText(err_frame, msg, (30, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            encode_success, buffer = cv2.imencode('.jpg', err_frame)
            if encode_success:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            return

        ai_engine = get_ai_engine()
        tracker = FaceTracker()

        # Biến chia sẻ giữa luồng AI Worker và luồng Render
        shared_state = {
            "current_detections": [],
            "is_ai_busy": False,
            "running": True
        }
        state_lock = threading.Lock()
        last_live_logged_time = {}  # person_name -> timestamp_sec debounce

        def ai_worker_loop():
            """Tiến trình nền thực thi mô hình AI trên GPU RTX 4050"""
            while shared_state["running"]:
                has_frame, frame = reader.read()
                if not has_frame or frame is None:
                    time.sleep(0.01)
                    continue

                try:
                    # Suy luận nhận diện trên GPU
                    raw_detections = ai_engine.process_frame(frame)

                    # Cập nhật bộ theo dõi khuôn mặt để làm mượt và chống nhấp nháy
                    tracked_faces = tracker.update(raw_detections)

                    with state_lock:
                        shared_state["current_detections"] = tracked_faces
                except Exception as e:
                    print(f"[AI Worker Error]: {e}")

                # Nhịp nghỉ cực ngắn giữa các lượt quét AI (~30-40 FPS trên GPU)
                time.sleep(0.01)

        # Khởi chạy luồng AI Worker
        ai_thread = threading.Thread(target=ai_worker_loop, daemon=True)
        ai_thread.start()

        target_fps = 30.0
        frame_delay = 1.0 / target_fps
        last_frame = None

        try:
            while True:
                loop_start = time.time()

                if self.is_paused:
                    if last_frame is not None:
                        encode_success, buffer = cv2.imencode('.jpg', last_frame)
                        if encode_success:
                            yield (b'--frame\r\n'
                                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
                    time.sleep(0.1)
                    continue

                has_frame, frame = reader.read()
                if not has_frame or frame is None:
                    time.sleep(0.01)
                    continue

                # Lấy kết quả nhận diện đã được làm mượt từ AI Worker
                with state_lock:
                    detections = list(shared_state["current_detections"])

                # Áp dụng cơ chế Auto-Zoom (khi có người ở xa -> zoom in, không có người -> zoom out)
                display_frame, adj_results, is_zooming = ai_engine.apply_auto_zoom(
                    frame, detections, enabled=self.auto_zoom_enabled
                )

                # Vẽ bounding box và nhãn tên nhận diện
                for res in adj_results:
                    bbox = res["bbox"]
                    name = res.get("name", "Unknown")
                    conf = res.get("confidence", 0.0)

                    color = (0, 255, 0) if name != "Unknown" else (0, 0, 255)
                    cv2.rectangle(display_frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), color, 2)

                    # Hiển thị không dấu trên khung hình OpenCV để không bị lỗi ký tự
                    clean_name = remove_accents(name) if name != "Unknown" else "Unknown"
                    label = f"{clean_name} ({conf * 100:.1f}%)" if name != "Unknown" else "Unknown"
                    cv2.putText(display_frame, label, (bbox[0], max(12, bbox[1] - 8)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2)

                    # Ghi log có debounce (ít nhất 3.0 giây giữa 2 lần log của cùng 1 người)
                    if name != "Unknown":
                        now = time.time()
                        last_time = last_live_logged_time.get(name, 0.0)
                        if now - last_time >= 3.0:
                            last_live_logged_time[name] = now
                            try:
                                log_detection(name, float(conf))
                            except Exception as e:
                                print(f"[Log Error]: {e}")

                if is_zooming and self.auto_zoom_enabled:
                    # Hiển thị trạng thái Auto-Zoom trên góc màn hình
                    cv2.putText(display_frame, "[ AUTO-ZOOM ACTIVE ]", (15, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 215, 255), 2)


                last_frame = display_frame.copy()

                # Nén JPEG chất lượng 82% để cân bằng hoàn hảo giữa độ nét và băng thông
                encode_success, buffer = cv2.imencode('.jpg', display_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
                if not encode_success:
                    continue

                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

                # Điều tiết tốc độ khung hình luồng MJPEG đạt 30 FPS mượt mà
                elapsed = time.time() - loop_start
                sleep_duration = frame_delay - elapsed
                if sleep_duration > 0:
                    time.sleep(sleep_duration)

        finally:
            shared_state["running"] = False
            reader.stop()
            if ai_thread.is_alive():
                ai_thread.join(timeout=0.5)


# Global Singleton StreamService instance
stream_service = StreamService()
