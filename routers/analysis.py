import os
import uuid
import json
from typing import Literal
from fastapi import APIRouter, UploadFile, File, BackgroundTasks, Query, Form, HTTPException
from fastapi.responses import JSONResponse

from config import VIDEO_UPLOAD_DIR
from db.jobs_repo import (
    create_video_job,
    get_video_job,
    get_video_detections_since,
    get_job_summary, get_video_appearance_updates, get_video_snapshots_since
)
from services.video_worker import analyze_video_background, video_settings
from core.gallery import GallerySnapshot
from core.live_zones import validate_zones
from db.persons_repo import load_live_gallery

router = APIRouter(prefix="/api", tags=["Video Analysis"])


@router.post("/analyze_video")
async def analyze_video_api(background_tasks: BackgroundTasks, file: UploadFile = File(...),
                            mode: Literal['fast', 'detailed', 'classroom'] = Form('detailed'),
                            zones_json: str = Form('[]')):
    """Upload video và khởi chạy phân tích nền siêu tốc"""
    mode = 'detailed' if mode == 'classroom' else mode
    try:
        zones = validate_zones(json.loads(zones_json))
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=f'Vùng video không hợp lệ: {exc}')
    gallery = GallerySnapshot(load_live_gallery())
    if not gallery.watchlist:
        raise HTTPException(status_code=400, detail='Bật tìm kiếm và thêm ảnh mẫu cho ít nhất một người trước khi phân tích.')
    save_path = None
    try:
        job_id = uuid.uuid4().hex
        filename = file.filename or 'video.mp4'
        ext = os.path.splitext(filename)[1].lower() or '.mp4'
        if ext not in ('.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v'):
            raise HTTPException(status_code=415, detail='Định dạng video chưa được hỗ trợ')
        save_filename = f"{job_id}{ext}"
        save_path = os.path.join(VIDEO_UPLOAD_DIR, save_filename)

        with open(save_path, "wb") as buffer:
            while chunk := await file.read(8 * 1024 * 1024):
                buffer.write(chunk)
        if os.path.getsize(save_path) == 0:
            raise HTTPException(status_code=400, detail='File video rỗng')

        video_url = f"/static/uploaded_videos/{save_filename}"
        settings = video_settings(gallery, mode, zones)
        create_video_job(job_id=job_id, filename=filename, video_url=video_url, mode=mode, settings=settings)

        # Chạy tác vụ phân tích AI không chặn main thread
        background_tasks.add_task(analyze_video_background, job_id, save_path, mode=mode, gallery=gallery, zones=zones)

        return {
            "status": "success",
            "job_id": job_id,
            "filename": filename,
            "mode": mode,
            "watchlist": gallery.watchlist,
            "video_url": video_url,
            "message": "Đã bắt đầu phân tích video trong nền."
        }
    except Exception as e:
        if save_path and os.path.isfile(save_path):
            os.remove(save_path)
        if isinstance(e, HTTPException):
            raise
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})
    finally:
        await file.close()


@router.get("/video_analysis/{job_id}/events")
def get_video_analysis_events(job_id: str, last_id: int = Query(0, ge=0),
                              last_snapshot_id: int = Query(0, ge=0)):
    """Lấy danh sách các phát hiện mới từ frame AI vừa quét để đẩy realtime ra Web"""
    job = get_video_job(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"message": "Không tìm thấy job phân tích"})

    new_detections = get_video_detections_since(job_id, last_id)
    current_max_id = max([d["id"] for d in new_detections], default=last_id)
    snapshots = get_video_snapshots_since(job_id, last_snapshot_id, current_max_id)

    return {
        "status": job["status"],
        "progress": job["progress"],
        "processed_frames": job["processed_frames"],
        "total_frames": job["total_frames"],
        "scanned_frames": job['scanned_frames'],
        "scanned_until_sec": job['scanned_until_sec'],
        "elapsed_sec": job['elapsed_sec'],
        "error_message": job['error_message'],
        "warning_message": job['warning_message'],
        "mode": job['mode'],
        "appearance_updates": get_video_appearance_updates(job_id),
        "new_detections": new_detections,
        "new_snapshots": snapshots,
        "last_snapshot_id": max([s['id'] for s in snapshots], default=last_snapshot_id),
        "last_id": current_max_id
    }


@router.get("/video_analysis/{job_id}/summary")
def get_video_analysis_summary(job_id: str):
    """Lấy toàn bộ lịch sử và tổng kết phát hiện của video"""
    job = get_video_job(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"message": "Không tìm thấy job phân tích"})

    summary_data = get_job_summary(job_id)
    return {
        "job": job,
        "summary": summary_data["summary"],
        "all_detections": summary_data["all_detections"],
        "snapshots": summary_data["snapshots"]
    }
