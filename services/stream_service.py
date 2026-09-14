import os
import time
import cv2
import numpy as np

from core.engine import get_ai_engine
from core.hardware import get_camera_device_index
from db.logs_repo import log_detection
from utils.text_utils import remove_accents


class StreamService:
    """
    Quản lý luồng video thời gian thực từ Webcam, iPhone (Iriun), IP Cam hoặc Video File:
    - Điều khiển trạng thái Stream: Pause / Resume / Stop.
    - Xử lý nhận diện khuôn mặt qua AI Engine.
    - Áp dụng bộ điều khiển Auto-Zoom mượt mà và vẽ bounding box, nhãn không dấu.
    - Debounce ghi log chống spam CSDL.
    """
    def __init__(self):
        self.is_paused = False
        self.uploaded_video_path = None

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False

    def stop(self):
        self.is_paused = False
        self.uploaded_video_path = None

    def set_uploaded_video(self, path: str):
        self.uploaded_video_path = path
        self.is_paused = False

    def generate_video_stream(self, source: str = "webcam", ip: str = "", auto_zoom: bool = False):
        self.is_paused = False

        if source == "file":
            if not self.uploaded_video_path or not os.path.exists(self.uploaded_video_path):
                return
            cap = cv2.VideoCapture(self.uploaded_video_path)
        elif source == "iphone":
            target_idx = get_camera_device_index("iphone")
            cap = cv2.VideoCapture(target_idx, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap = cv2.VideoCapture(target_idx)
        elif source == "ip_cam":
            cam_url = ip.strip() if ip.strip() else "192.168.1.15"
            if not (cam_url.startswith("http://") or cam_url.startswith("https://") or cam_url.startswith("rtsp://")):
                cam_url = f"http://{cam_url}:4747/video"
            cap = cv2.VideoCapture(cam_url)
        else:  # source == "webcam" (Laptop Webcam)
            target_idx = get_camera_device_index("webcam")
            cap = cv2.VideoCapture(target_idx, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap = cv2.VideoCapture(target_idx)

        if not cap.isOpened():
            err_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            msg = f"Khong the ket noi: {source}"
            cv2.putText(err_frame, msg, (30, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            encode_success, buffer = cv2.imencode('.jpg', err_frame)
            if encode_success:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            return

        ai_engine = get_ai_engine()
        last_frame = None
        frame_count = 0
        process_every_n_frames = 2
        cached_results = []
        last_live_logged_time = {}  # person_name -> timestamp_sec để debounce chống spam dồn ứ bảng log

        fps = cap.get(cv2.CAP_PROP_FPS)
        target_frame_time = 1.0 / (fps if fps > 0 and fps <= 60 else 30)

        try:
            while True:
                start_time = time.time()

                if self.is_paused:
                    if last_frame is not None:
                        encode_success, buffer = cv2.imencode('.jpg', last_frame)
                        if encode_success:
                            yield (b'--frame\r\n'
                                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
                    time.sleep(0.1)
                    continue

                success, frame = cap.read()
                if not success:
                    if source == "file":
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    else:
                        break

                frame_count += 1

                if frame_count % process_every_n_frames == 0:
                    try:
                        cached_results = ai_engine.process_frame(frame)
                    except Exception as e:
                        print(f"Lỗi AI: {e}")

                # Áp dụng cơ chế Auto-Zoom (khi có người ở xa -> zoom in, không có người -> zoom out về toàn cảnh)
                display_frame, adj_results, is_zooming = ai_engine.apply_auto_zoom(frame, cached_results, enabled=auto_zoom)

                for res in adj_results:
                    bbox = res["bbox"]
                    name = res["name"]
                    conf = res["confidence"]

                    color = (0, 255, 0) if name != "Unknown" else (0, 0, 255)
                    cv2.rectangle(display_frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), color, 2)

                    # Hiển thị không dấu trên khung hình OpenCV để không bị lỗi dấu ??
                    clean_name = remove_accents(name) if name != "Unknown" else "Unknown"
                    label = f"{clean_name} ({conf * 100:.1f}%)" if name != "Unknown" else "Unknown"
                    cv2.putText(display_frame, label, (bbox[0], max(10, bbox[1] - 10)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

                    # Ghi log có debounce: cách ít nhất 3.0 giây giữa 2 lần log của cùng 1 người
                    if name != "Unknown":
                        now = time.time()
                        last_time = last_live_logged_time.get(name, 0.0)
                        if now - last_time >= 3.0:
                            last_live_logged_time[name] = now
                            try:
                                log_detection(name, float(conf))
                            except Exception as e:
                                print(f"Lỗi log: {e}")

                if is_zooming and auto_zoom:
                    # Hiển thị biểu tượng báo hiệu Auto-Zoom đang kích hoạt
                    cv2.putText(display_frame, "[ AUTO-ZOOM ACTIVE ]", (15, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 215, 255), 2)

                last_frame = display_frame.copy()
                encode_success, buffer = cv2.imencode('.jpg', display_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if not encode_success:
                    continue

                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

                if source == "file":
                    elapsed = time.time() - start_time
                    sleep_time = target_frame_time - elapsed
                    if sleep_time > 0:
                        time.sleep(sleep_time)

        finally:
            cap.release()


# Global Singleton StreamService instance
stream_service = StreamService()
