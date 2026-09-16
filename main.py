import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import BASE_DIR, UPLOAD_DIR, SNAPSHOT_DIR, VIDEO_UPLOAD_DIR
from db.connection import init_db
from routers import (
    cameras_router,
    logs_router,
    persons_router,
    stream_router,
    analysis_router
)

# Khởi tạo ứng dụng FastAPI
app = FastAPI(title="Hệ Thống Nhận Diện Người")

# Đảm bảo các thư mục static cần thiết luôn sẵn sàng
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(SNAPSHOT_DIR, exist_ok=True)
os.makedirs(VIDEO_UPLOAD_DIR, exist_ok=True)

# Mount thư mục static phục vụ hình ảnh, css, js
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


@app.on_event("startup")
def startup_event():
    """Khởi tạo CSDL và Warm-up mô hình AI khi khởi động server"""
    init_db()

    # Pre-warming mô hình AI trên GPU (Khởi tạo sẵn & JIT compilation để nhận diện tức thì ngay frame 1)
    print("\n" + "=" * 60)
    print("[Startup] Dang khoi tao va Warm-up mo hinh AI tren GPU/CPU...")
    try:
        import numpy as np
        from core.engine import get_ai_engine
        engine = get_ai_engine()
        # Chạy forward pass với dummy frame để CUDA cấp phát VRAM và biên dịch kernel sẵn
        dummy_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        engine.process_frame(dummy_frame)
        print("[Startup] >>> AI Engine Warm-up HOAN TAT! San sang nhan dien tuc thi.")
    except Exception as e:
        print(f"[Startup Warning] Loi khi warm-up AI Engine: {e}")
    print("=" * 60 + "\n")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """Trang chủ giao diện điều khiển giám sát AI"""
    return templates.TemplateResponse("index.html", {"request": request})


# Đăng ký các APIRouter module hóa
app.include_router(cameras_router)
app.include_router(logs_router)
app.include_router(persons_router)
app.include_router(stream_router)
app.include_router(analysis_router)


# --- Re-export các hàm phổ biến để duy trì tương thích ngược 100% ---
from utils.text_utils import remove_accents
from core.hardware import get_camera_device_index
from services.stream_service import stream_service

generate_video_stream = stream_service.generate_video_stream