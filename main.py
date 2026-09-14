import os
import cv2
import numpy as np
import tempfile
import time
import uuid
import unicodedata
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Form, Request, Query, BackgroundTasks
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import config
from database import (
    init_db, save_person_embedding, log_detection, get_db,
    get_person_embeddings, delete_single_embedding,
    create_video_job, update_job_status, add_video_detection,
    get_video_job, get_video_detections_since, get_job_summary
)
from ai_engine import get_ai_engine, analyze_video_background

app = FastAPI(title="Hệ Thống Nhận Diện Người")

# Xác định đường dẫn gốc và khởi tạo thư mục tĩnh
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def remove_accents(input_str: str) -> str:
    """Loại bỏ dấu tiếng Việt cho nhãn vẽ OpenCV cv2.putText tránh lỗi font hiển thị dấu ??"""
    if not input_str:
        return ""
    nfkd_form = unicodedata.normalize('NFKD', input_str)
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)]).replace('đ', 'd').replace('Đ', 'D')

UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
SNAPSHOT_DIR = os.path.join(BASE_DIR, "static", "snapshots")
VIDEO_UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploaded_videos")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(SNAPSHOT_DIR, exist_ok=True)
os.makedirs(VIDEO_UPLOAD_DIR, exist_ok=True)

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
def get_detection_logs_api(person: Optional[str] = None):
    """API lấy nhật ký phát hiện: hỗ trợ dòng thời gian và phân nhóm theo từng người để chống chồng chéo"""
    db = get_db()

    # 1. Danh sách log dòng thời gian (có hỗ trợ lọc theo người)
    if isinstance(person, str) and person.strip() and person.strip() != "all":
        logs = db.execute(
            "SELECT id, person_name, confidence, strftime('%H:%M:%S', detected_at) as time_str, detected_at "
            "FROM detection_logs WHERE person_name = ? ORDER BY id DESC LIMIT 50",
            (person.strip(),)
        ).fetchall()
    else:
        logs = db.execute(
            "SELECT id, person_name, confidence, strftime('%H:%M:%S', detected_at) as time_str, detected_at "
            "FROM detection_logs ORDER BY id DESC LIMIT 50"
        ).fetchall()

    # 2. Phân nhóm theo từng người
    grouped_rows = db.execute("""
        SELECT 
            person_name,
            COUNT(*) as total_detections,
            MAX(confidence) as max_confidence,
            MAX(detected_at) as last_detected_at,
            strftime('%H:%M:%S', MAX(detected_at)) as last_seen_time
        FROM detection_logs
        GROUP BY person_name
        ORDER BY last_detected_at DESC
    """).fetchall()

    # Lấy ảnh đại diện (avatar) nếu có từ bảng persons & face_embeddings
    avatars = {}
    try:
        avatar_rows = db.execute("""
            SELECT p.name, f.image_path 
            FROM persons p 
            JOIN face_embeddings f ON p.id = f.person_id 
            WHERE f.image_path IS NOT NULL AND f.image_path != ''
            GROUP BY p.name
        """).fetchall()
        for r in avatar_rows:
            avatars[r['name']] = r['image_path']
    except Exception:
        pass

    # Lấy danh sách các lần gần nhất của riêng từng người
    people_groups = []
    for g in grouped_rows:
        p_name = g['person_name']
        p_logs = db.execute(
            "SELECT confidence, strftime('%H:%M:%S', detected_at) as time_str, detected_at "
            "FROM detection_logs WHERE person_name = ? ORDER BY id DESC LIMIT 10",
            (p_name,)
        ).fetchall()

        people_groups.append({
            "name": p_name,
            "total_count": g['total_detections'],
            "max_confidence": f"{g['max_confidence'] * 100:.1f}%",
            "last_seen": g['last_seen_time'],
            "last_detected_at": g['last_detected_at'],
            "avatar": avatars.get(p_name),
            "recent_logs": [
                {"confidence": f"{l['confidence'] * 100:.1f}%", "time": l["time_str"]}
                for l in p_logs
            ]
        })

    result_logs = [
        {"name": l["person_name"], "confidence": f"{l['confidence'] * 100:.1f}%", "time": l["time_str"] or ""}
        for l in logs
    ]

    return JSONResponse(content={
        "logs": result_logs,
        "people_groups": people_groups
    })


@app.delete("/api/logs")
def clear_detection_logs_api():
    """Xóa toàn bộ nhật ký phát hiện camera"""
    db = get_db()
    db.execute("DELETE FROM detection_logs")
    db.commit()
    return {"status": "success", "message": "Đã xóa toàn bộ nhật ký phát hiện!"}


@app.get("/api/cameras")
def get_available_cameras():
    devices = []
    try:
        import comtypes
        comtypes.CoInitialize()
        from pygrabber.dshow_graph import FilterGraph
        devices = FilterGraph().get_input_devices()
    except Exception:
        pass
    finally:
        try:
            import comtypes
            comtypes.CoUninitialize()
        except Exception:
            pass

    return {
        "cameras": [{"index": i, "name": name} for i, name in enumerate(devices)],
        "webcam_index": get_camera_device_index("webcam"),
        "iphone_index": get_camera_device_index("iphone")
    }



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


def get_camera_device_index(source: str) -> int:
    """
    Tự động tìm chỉ số (index) camera DirectShow trên Windows.
    - 'iphone': tìm thiết bị có tên chứa 'iriun', fallback config.DEFAULT_IRIUN_INDEX (0)
    - 'webcam': tìm webcam laptop (bỏ qua iriun, obs, virtual), fallback config.DEFAULT_WEBCAM_INDEX (1)
    """
    devices = []
    try:
        import comtypes
        comtypes.CoInitialize()
        from pygrabber.dshow_graph import FilterGraph
        devices = FilterGraph().get_input_devices()
    except Exception as e:
        print(f"Lỗi quét camera: {e}")
    finally:
        try:
            import comtypes
            comtypes.CoUninitialize()
        except Exception:
            pass

    if source == "iphone":
        for idx, name in enumerate(devices):
            if "iriun" in name.lower():
                return idx
        return getattr(config, "DEFAULT_IRIUN_INDEX", 0)
    else:
        for idx, name in enumerate(devices):
            name_lower = name.lower()
            if not any(v in name_lower for v in ["iriun", "obs", "virtual"]):
                return idx
        return getattr(config, "DEFAULT_WEBCAM_INDEX", 1)


def generate_video_stream(source: str = "webcam", ip: str = "", auto_zoom: bool = False):
    global uploaded_video_path, is_paused
    is_paused = False

    if source == "file":
        if not uploaded_video_path or not os.path.exists(uploaded_video_path):
            return
        cap = cv2.VideoCapture(uploaded_video_path)
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


@app.get("/video_feed")
def video_feed(source: str = Query("webcam"), ip: str = Query(""), auto_zoom: bool = Query(False)):
    return StreamingResponse(
        generate_video_stream(source=source, ip=ip, auto_zoom=auto_zoom),
        media_type='multipart/x-mixed-replace; boundary=frame'
    )


# --- CÁC ENDPOINT PHÂN TÍCH VIDEO NHANH VÀ ĐẨY THÔNG BÁO REALTIME ---

@app.post("/api/analyze_video")
async def analyze_video_api(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """Upload video và khởi chạy phân tích nền siêu tốc"""
    try:
        job_id = uuid.uuid4().hex
        ext = os.path.splitext(file.filename)[1] or ".mp4"
        save_filename = f"{job_id}{ext}"
        save_path = os.path.join(VIDEO_UPLOAD_DIR, save_filename)

        with open(save_path, "wb") as buffer:
            buffer.write(await file.read())

        video_url = f"/static/uploaded_videos/{save_filename}"
        create_video_job(job_id=job_id, filename=file.filename, video_url=video_url)

        # Chạy tác vụ phân tích AI không chặn main thread
        background_tasks.add_task(analyze_video_background, job_id, save_path, sample_fps=2.0)

        return {
            "status": "success",
            "job_id": job_id,
            "filename": file.filename,
            "video_url": video_url,
            "message": "Đã bắt đầu phân tích video trong nền."
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@app.get("/api/video_analysis/{job_id}/events")
def get_video_analysis_events(job_id: str, last_id: int = Query(0)):
    """Lấy danh sách các phát hiện mới từ frame AI vừa quét để đẩy realtime ra Web"""
    job = get_video_job(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"message": "Không tìm thấy job phân tích"})

    new_detections = get_video_detections_since(job_id, last_id)
    current_max_id = max([d["id"] for d in new_detections], default=last_id)

    return {
        "status": job["status"],
        "progress": job["progress"],
        "processed_frames": job["processed_frames"],
        "total_frames": job["total_frames"],
        "new_detections": new_detections,
        "last_id": current_max_id
    }


@app.get("/api/video_analysis/{job_id}/summary")
def get_video_analysis_summary(job_id: str):
    """Lấy toàn bộ lịch sử và tổng kết phát hiện của video"""
    job = get_video_job(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"message": "Không tìm thấy job phân tích"})

    summary_data = get_job_summary(job_id)
    return {
        "job": job,
        "summary": summary_data["summary"],
        "all_detections": summary_data["all_detections"]
    }