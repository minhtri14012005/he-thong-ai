from fastapi import APIRouter
from core.hardware import scan_available_cameras, get_camera_device_index

router = APIRouter(prefix="/api/cameras", tags=["Cameras"])


@router.get("")
def get_available_cameras():
    """Lấy danh sách camera DirectShow trên máy và index mặc định cho Laptop Webcam & iPhone"""
    devices = scan_available_cameras()
    return {
        "cameras": devices,
        "webcam_index": get_camera_device_index("webcam"),
        "iphone_index": get_camera_device_index("iphone")
    }
