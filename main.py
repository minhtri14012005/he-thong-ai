import os
import cv2
import numpy as np
import tempfile
import time
import uuid
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Form, Request, Query
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import config
from database import (
    init_db, save_person_embedding, log_detection, get_db,
    get_person_embeddings, delete_single_embedding
)
from ai_engine import get_ai_engine

app = FastAPI(title="Hệ Thống Nhận Diện Người")

# Xác định đường dẫn gốc và khởi tạo thư mục static/uploads
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Mount thư mục static để phục vụ tải ảnh thumbnail từ Web
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

TEMP_DIR = tempfile.mkdtemp()
uploaded_video_path = None
is_paused = False


@app.on_event("startup")
def startup_event():
    init_db()


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/control_stream")
def control_stream(action: str = Query(...)):
    global is_paused, uploaded_video_path
    if action == "pause":
        is_paused = True
    elif action == "resume":
        is_paused = False
    elif action == "stop":
        uploaded_video_path = None
        is_paused = False
    return {"status": "success", "is_paused": is_paused}


@app.get("/api/logs")
def get_detection_logs_api():
    db = get_db()
    logs = db.execute(
        "SELECT person_name, confidence, strftime('%H:%M:%S', detected_at) as time_str FROM detection_logs ORDER BY id DESC LIMIT 30"
    ).fetchall()

    result = [{"name": l["person_name"], "confidence": f"{l['confidence'] * 100:.1f}%", "time": l["time_str"] or ""} for l in logs]
    return JSONResponse(content={"logs": result})


@app.get("/api/persons")
def get_persons_api():
    db = get_db()
    persons = db.execute("SELECT id, name, created_at FROM persons").fetchall()
    result = []
    for p in persons:
        p_id, name, created_at = p["id"], p["name"], p["created_at"]
        count = db.execute("SELECT COUNT(*) FROM face_embeddings WHERE person_id = ?", (p_id,)).fetchone()[0]
        result.append({"id": p_id, "name": name, "sample_count": count, "created_at": created_at})
    return JSONResponse(content={"persons": result})


# Route 1: Nhận person_id từ Query Parameter (ví dụ: /api/person_embeddings?person_id=9)
@app.get("/api/person_embeddings")
def get_person_embeddings_query(person_id: int = Query(...)):
    """API lấy danh sách mẫu ảnh theo Query Param"""
    try:
        embeddings = get_person_embeddings(person_id)
        return JSONResponse(content={"embeddings": embeddings})
    except Exception as e:
        print(f"Lỗi khi lấy embeddings: {e}")
        return JSONResponse(status_code=500, content={"message": str(e)})


# Route 2: Nhận person_id từ Path Parameter (ví dụ: /api/person_embeddings/9)
@app.get("/api/person_embeddings/{person_id}")
def get_person_embeddings_path(person_id: int):
    """API lấy danh sách mẫu ảnh theo Path Param"""
    try:
        embeddings = get_person_embeddings(person_id)
        return JSONResponse(content={"embeddings": embeddings})
    except Exception as e:
        print(f"Lỗi khi lấy embeddings: {e}")
        return JSONResponse(status_code=500, content={"message": str(e)})


@app.delete("/api/embeddings/{embedding_id}")
def delete_embedding_api(embedding_id: int):
    delete_single_embedding(embedding_id)
    get_ai_engine().reload_known_faces()
    return {"status": "success", "message": "Đã xóa 1 mẫu ảnh thành công!"}


@app.post("/api/register")
async def register_person_api(name: str = Form(...), files: List[UploadFile] = File(...)):
    ai_engine = get_ai_engine()
    success_count = 0

    for file in files:
        contents = await file.read()
        if not contents:
            continue

        nparr = np.frombuffer(contents, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is not None:
            res = ai_engine.extract_face_embedding(img)
            if len(res) == 3:
                embedding, rel_path, msg = res
            else:
                embedding, msg = res
                rel_path = None

            if embedding is not None:
                if not rel_path:
                    ext = os.path.splitext(file.filename)[1] or ".jpg"
                    filename = f"{uuid.uuid4().hex}{ext}"
                    full_file_path = os.path.join(UPLOAD_DIR, filename)

                    with open(full_file_path, "wb") as f:
                        f.write(contents)

                    rel_path = f"static/uploads/{filename}"

                if save_person_embedding(name, embedding, rel_path):
                    success_count += 1

    if success_count > 0:
        ai_engine.reload_known_faces()
        return {"status": "success", "message": f"Đã lưu thành công {success_count} mẫu ảnh cho {name}"}
    return {"status": "error", "message": "Không thể trích xuất khuôn mặt từ các file đã chọn!"}


@app.put("/api/persons/rename")
def rename_person_api(person_id: int = Form(...), new_name: str = Form(...)):
    db = get_db()
    db.execute("UPDATE persons SET name = ? WHERE id = ?", (new_name, person_id))
    db.commit()
    get_ai_engine().reload_known_faces()
    return {"status": "success", "message": "Đã đổi tên thành công!"}


@app.delete("/api/persons/{person_id}")
def delete_person_api(person_id: int):
    db = get_db()
    rows = db.execute("SELECT image_path FROM face_embeddings WHERE person_id = ?", (person_id,)).fetchall()

    for r in rows:
        if r['image_path'] and os.path.exists(r['image_path']):
            try:
                os.remove(r['image_path'])
            except Exception:
                pass

    db.execute("DELETE FROM face_embeddings WHERE person_id = ?", (person_id,))
    db.execute("DELETE FROM persons WHERE id = ?", (person_id,))
    db.commit()
    get_ai_engine().reload_known_faces()
    return {"status": "success", "message": "Đã xóa người dùng khỏi hệ thống!"}


@app.post("/api/upload_video")
async def upload_video_api(file: UploadFile = File(...)):
    global uploaded_video_path, is_paused
    try:
        is_paused = False
        suffix = os.path.splitext(file.filename)[1] or ".mp4"
        temp_path = os.path.join(TEMP_DIR, f"current_video{suffix}")

        with open(temp_path, "wb") as buffer:
            buffer.write(await file.read())

        uploaded_video_path = temp_path
        return {"status": "success", "message": "Tải video lên thành công!"}
    except Exception as e:
        return {"status": "error", "message": f"Lỗi tải video: {str(e)}"}


def generate_video_stream(source: str = "webcam", ip: str = ""):
    global uploaded_video_path, is_paused
    is_paused = False

    if source == "file":
        if not uploaded_video_path or not os.path.exists(uploaded_video_path):
            return
        cap = cv2.VideoCapture(uploaded_video_path)
    elif source == "iphone":
        cam_ip = ip.strip() if ip.strip() else "192.168.1.15"
        cap = cv2.VideoCapture(f"http://{cam_ip}:4747/video")
    else:
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        return

    ai_engine = get_ai_engine()
    last_frame = None
    frame_count = 0
    process_every_n_frames = 2
    cached_results = []

    fps = cap.get(cv2.CAP_PROP_FPS)
    target_frame_time = 1.0 / (fps if fps > 0 and fps <= 60 else 30)

    try:
        while True:
            start_time = time.time()

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

            for res in cached_results:
                bbox = res["bbox"]
                name = res["name"]
                conf = res["confidence"]

                color = (0, 255, 0) if name != "Unknown" else (0, 0, 255)
                cv2.rectangle(frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), color, 2)
                label = f"{name} ({conf * 100:.1f}%)" if name != "Unknown" else "Unknown"
                cv2.putText(frame, label, (bbox[0], max(10, bbox[1] - 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

                if name != "Unknown" and frame_count % (process_every_n_frames * 5) == 0:
                    try:
                        log_detection(name, float(conf))
                    except Exception as e:
                        print(f"Lỗi log: {e}")

            last_frame = frame.copy()
            encode_success, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
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


@app.get("/video_feed")
def video_feed(source: str = Query("webcam"), ip: str = Query("")):
    return StreamingResponse(
        generate_video_stream(source=source, ip=ip),
        media_type='multipart/x-mixed-replace; boundary=frame'
    )