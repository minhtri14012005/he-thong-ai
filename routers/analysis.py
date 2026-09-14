import os
import uuid
from fastapi import APIRouter, UploadFile, File, BackgroundTasks, Query
from fastapi.responses import JSONResponse

from config import VIDEO_UPLOAD_DIR
from db.jobs_repo import (
    create_video_job,
    get_video_job,
    get_video_detections_since,
    get_job_summary
)
from services.video_worker import analyze_video_background

router = APIRouter(prefix="/api", tags=["Video Analysis"])


@router.post("/analyze_video")
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


@router.get("/video_analysis/{job_id}/events")
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
        "all_detections": summary_data["all_detections"]
    }
