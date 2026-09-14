"""
Facade module ai_engine.py để duy trì tính tương thích ngược (Backward Compatibility).
Toàn bộ thuật toán lõi AI, NMS, Zoom đã được module hóa chuẩn trong package `core/`,
và tiến trình nền phân tích video được module hóa trong package `services/`.
"""

from core import (
    nms_bboxes_kps,
    SmoothZoomController,
    HighAccuracyFaceEngine,
    get_ai_engine
)
from services import analyze_video_background

__all__ = [
    "nms_bboxes_kps",
    "SmoothZoomController",
    "HighAccuracyFaceEngine",
    "get_ai_engine",
    "analyze_video_background"
]