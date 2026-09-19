import os
import tempfile
from fastapi import APIRouter, UploadFile, File, Query, Body, HTTPException
from fastapi.responses import StreamingResponse
from config import DEFAULT_AUTO_ZOOM
from services.stream_service import stream_service
from core.live_zones import save_zones

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


@router.post("/api/switch_camera")
def switch_camera(source: str = Query("iphone"), ip: str = Query("")):
    """Chuyển đổi nguồn camera an toàn, giải phóng camera cũ trước khi mở camera mới"""
    try:
        success = stream_service.switch_camera_source(source=source, ip=ip)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if not success:
        raise HTTPException(status_code=503, detail="Không mở được camera. Kiểm tra kết nối Iriun.")
    return {"status": "success", "source": source}


@router.get('/api/live/status')
def live_status():
    return stream_service.status()


@router.put('/api/live/zones')
def update_live_zones(zones: list = Body(...)):
    try:
        stream_service.zones = save_zones(zones)
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {'zones': stream_service.zones}



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
def video_feed(source: str = Query("iphone"), ip: str = Query(""), auto_zoom: bool = Query(DEFAULT_AUTO_ZOOM)):
    """Endpoint sinh luồng MJPEG thời gian thực có áp dụng Auto-Zoom và AI Detection"""
    return StreamingResponse(
        stream_service.generate_video_stream(source=source, ip=ip, auto_zoom=auto_zoom),
        media_type='multipart/x-mixed-replace; boundary=frame'
    )
