import os
import tempfile
from fastapi import APIRouter, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from config import DEFAULT_AUTO_ZOOM
from services.stream_service import stream_service

router = APIRouter(tags=["Stream"])

TEMP_DIR = tempfile.mkdtemp()


@router.post("/api/control_stream")
def control_stream(action: str = Query(...)):
    """Điều khiển tạm dừng, tiếp tục hoặc dừng luồng video"""
    if action == "pause":
        stream_service.pause()
    elif action == "resume":
        stream_service.resume()
    elif action == "stop":
        stream_service.stop()
    return {"status": "success", "is_paused": stream_service.is_paused}


@router.post("/api/set_auto_zoom")
def set_auto_zoom(enabled: bool = Query(...)):
    """Điều khiển bật/tắt Auto-Zoom mềm trong thời gian thực mà không cần reload camera hay gián đoạn stream"""
    state = stream_service.set_auto_zoom(enabled)
    return {"status": "success", "auto_zoom": state}


@router.post("/api/upload_video")
async def upload_video_api(file: UploadFile = File(...)):
    """Upload video để phát trực tiếp trong tab Giám sát Camera"""
    try:
        suffix = os.path.splitext(file.filename)[1] or ".mp4"
        temp_path = os.path.join(TEMP_DIR, f"current_video{suffix}")

        with open(temp_path, "wb") as buffer:
            buffer.write(await file.read())

        stream_service.set_uploaded_video(temp_path)
        return {"status": "success", "message": "Tải video lên thành công!"}
    except Exception as e:
        return {"status": "error", "message": f"Lỗi tải video: {str(e)}"}


@router.get("/video_feed")
def video_feed(source: str = Query("webcam"), ip: str = Query(""), auto_zoom: bool = Query(DEFAULT_AUTO_ZOOM)):
    """Endpoint sinh luồng MJPEG thời gian thực có áp dụng Auto-Zoom và AI Detection"""
    return StreamingResponse(
        stream_service.generate_video_stream(source=source, ip=ip, auto_zoom=auto_zoom),
        media_type='multipart/x-mixed-replace; boundary=frame'
    )

