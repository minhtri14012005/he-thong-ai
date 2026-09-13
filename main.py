import cv2
import numpy as np
import os
import tempfile
import time
from fastapi import FastAPI, UploadFile, File, Form, Request, Query
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from database import init_db, save_person_embedding, log_detection
from ai_engine import get_ai_engine

app = FastAPI(title="Hệ Thống Nhận Diện Người")
templates = Jinja2Templates(directory="templates")

# Thư mục tạm lưu video tải lên
TEMP_DIR = tempfile.mkdtemp()
uploaded_video_path = None
is_paused = False


@app.on_event("startup")
def startup_event():
    init_db()


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/register")
async def register_person_api(name: str = Form(...), file: UploadFile = File(...)):
    """API Đăng ký khuôn mặt người mới"""
    try:
        contents = await file.read()
        nparr = np.frombuffer(contents, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            return {"status": "error", "message": "File ảnh tải lên không hợp lệ!"}

        ai_engine = get_ai_engine()
        embedding, msg = ai_engine.extract_face_embedding(img)

        if embedding is None:
            return {"status": "error", "message": msg}

        success = save_person_embedding(name, embedding)
        if success:
            ai_engine.reload_known_faces()
            return {"status": "success", "message": f"Đã lưu thành công dữ liệu khuôn mặt cho {name}"}
        else:
            return {"status": "error", "message": "Không thể lưu dữ liệu vào cơ sở dữ liệu!"}
    except Exception as e:
        return {"status": "error", "message": f"Lỗi hệ thống: {str(e)}"}


@app.post("/api/upload_video")
async def upload_video_api(file: UploadFile = File(...)):
    """API Lưu file video tải lên để phát real-time"""
    global uploaded_video_path, is_paused
    try:
        is_paused = False
        suffix = os.path.splitext(file.filename)[1] or ".mp4"
        temp_path = os.path.join(TEMP_DIR, f"current_video{suffix}")

        with open(temp_path, "wb") as buffer:
            buffer.write(await file.read())

        uploaded_video_path = temp_path
        return {"status": "success", "message": "Tải video lên thành công! Đang phát stream video..."}
    except Exception as e:
        return {"status": "error", "message": f"Lỗi tải video: {str(e)}"}


@app.post("/api/control_stream")
def control_stream(action: str = Query(...)):
    """API nhận lệnh Pause / Resume luồng phát"""
    global is_paused
    if action == "pause":
        is_paused = True
    elif action == "resume":
        is_paused = False
    return {"status": "success", "is_paused": is_paused}


def generate_video_stream(source: str = "webcam", ip: str = ""):
    """Tối ưu luồng stream AI: Skip frame AI để mượt video + Điều tiết FPS chuẩn"""
    global uploaded_video_path, is_paused
    is_paused = False

    if source == "file":
        if not uploaded_video_path or not os.path.exists(uploaded_video_path):
            return
        cap = cv2.VideoCapture(uploaded_video_path)
    elif source == "iphone":
        cam_ip = ip.strip() if ip.strip() else "192.168.1.15"
        camera_target = f"http://{cam_ip}:4747/video"
        cap = cv2.VideoCapture(camera_target)
    else:
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        return

    ai_engine = get_ai_engine()
    last_frame = None

    # Cấu hình tối ưu tốc độ phát Video
    frame_count = 0
    process_every_n_frames = 2  # Nhận diện AI mỗi 2 frame để không làm tụt FPS
    cached_results = []

    fps = cap.get(cv2.CAP_PROP_FPS)
    target_frame_time = 1.0 / (fps if fps > 0 and fps <= 60 else 30)

    try:
        while True:
            start_time = time.time()

            # Trạng thái Tạm Dừng (Pause)
            if is_paused:
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
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # Lặp lại video (Loop)
                    continue
                else:
                    break

            frame_count += 1

            # Xử lý AI theo chu kỳ frame_skip
            if frame_count % process_every_n_frames == 0:
                try:
                    cached_results = ai_engine.process_frame(frame)
                except Exception as e:
                    print(f"Lỗi AI: {e}")

            # Vẽ bounding box lên frame hiện tại
            for res in cached_results:
                bbox = res["bbox"]
                name = res["name"]
                conf = res["confidence"]

                color = (0, 255, 0) if name != "Unknown" else (0, 0, 255)
                cv2.rectangle(frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), color, 2)
                label = f"{name} ({conf * 100:.1f}%)" if name != "Unknown" else "Unknown"
                cv2.putText(frame, label, (bbox[0], max(10, bbox[1] - 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

                if name != "Unknown" and frame_count % process_every_n_frames == 0:
                    log_detection(name, conf)

            last_frame = frame.copy()
            encode_success, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if not encode_success:
                continue

            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

            # Giữ chuẩn thời gian thực (FPS compensation) khi đọc file video
            if source == "file":
                elapsed = time.time() - start_time
                sleep_time = target_frame_time - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

    finally:
        cap.release()


@app.get("/video_feed")
def video_feed(
        source: str = Query("webcam"),
        ip: str = Query("")
):
    return StreamingResponse(
        generate_video_stream(source=source, ip=ip),
        media_type='multipart/x-mixed-replace; boundary=frame'
    )