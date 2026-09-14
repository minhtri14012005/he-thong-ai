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
    """Khởi tạo CSDL khi khởi động server"""
    init_db()


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