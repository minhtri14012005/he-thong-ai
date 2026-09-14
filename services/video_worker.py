import os
import cv2
import uuid
from config import SNAPSHOT_DIR
from db.jobs_repo import update_job_status, add_video_detection
from core.engine import get_ai_engine


def analyze_video_background(
    job_id: str,
    video_path: str,
    sample_fps: float = 2.0,
    cooldown_sec: float = 1.5
):
    """
    Phân tích video nền siêu tốc:
    - Quét frame theo sample_fps (mặc định 2 khung hình / giây).
    - Không sleep chờ FPS thực -> quét 20s video trong vài giây.
    - Phát hiện bất kỳ người nào có trong DB:
      + Ngay lập tức cắt thumbnail snapshot khuôn mặt
      + Ghi ngay vào video_detections trong DB để Web push thông báo tức thì.
    - Cập nhật progress liên tục.
    """
    ai_engine = get_ai_engine()
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        update_job_status(job_id, "error", 0)
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 0 or fps > 120:
        fps = 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    step = max(1, int(round(fps / sample_fps)))
    frame_idx = 0
    processed_count = 0
    last_seen_time = {}  # person_name -> last_timestamp_sec

    # Bắt đầu phân tích
    update_job_status(job_id, "processing", 0, processed_frames=0, total_frames=total_frames)

    try:
        while True:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret or frame is None:
                break

            processed_count += 1
            timestamp_sec = frame_idx / fps
            timestamp_str = f"{int(timestamp_sec // 60):02d}:{int(timestamp_sec % 60):02d}"

            # Nhận diện khuôn mặt trong frame với cơ chế quét tầm xa (High-Res & Classroom Patch Zoom Scan)
            results = ai_engine.process_frame_high_res(frame)

            # Lọc ra những người có trong danh sách cần tìm (name != 'Unknown')
            found_persons = [r for r in results if r["name"] != "Unknown"]

            for p in found_persons:
                name = p["name"]
                conf = float(p["confidence"])
                last_time = last_seen_time.get(name, -999.0)

                # Kiểm tra debounce: nếu cùng 1 người xuất hiện liên tục thì cách ít nhất cooldown_sec giây mới ghi tiếp
                if timestamp_sec - last_time >= cooldown_sec:
                    last_seen_time[name] = timestamp_sec

                    # Cắt thumbnail khuôn mặt lưu lại làm bằng chứng (tối ưu cho cả khuôn mặt ở xa)
                    bbox = p["bbox"]
                    bx1, by1, bx2, by2 = bbox
                    fh, fw = frame.shape[:2]
                    bw = bx2 - bx1
                    bh = by2 - by1
                    pad_w = max(int(bw * 0.35), 20)
                    pad_h = max(int(bh * 0.35), 20)
                    sx1 = max(0, bx1 - pad_w)
                    sy1 = max(0, by1 - pad_h)
                    sx2 = min(fw, bx2 + pad_w)
                    sy2 = min(fh, by2 + pad_h)
                    crop_face = frame[sy1:sy2, sx1:sx2]

                    # Đảm bảo thumbnail sắc nét, nếu khuôn mặt ở xa có kích thước nhỏ thì upscale chất lượng cao
                    if crop_face.size > 0:
                        ch, cw = crop_face.shape[:2]
                        if ch < 120 or cw < 120:
                            scale = max(120.0 / ch, 120.0 / cw)
                            target_w = max(1, int(round(cw * scale)))
                            target_h = max(1, int(round(ch * scale)))
                            crop_face = cv2.resize(crop_face, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)

                    snap_filename = f"{job_id}_{uuid.uuid4().hex[:8]}.jpg"
                    snap_full_path = os.path.join(SNAPSHOT_DIR, snap_filename)
                    if crop_face.size > 0:
                        cv2.imwrite(snap_full_path, crop_face)
                    else:
                        cv2.imwrite(snap_full_path, frame)
                    snap_rel_path = f"static/snapshots/{snap_filename}"

                    # ĐẨY NGAY VÀO CSDL TẠI THỜI ĐIỂM NÀY -> FRONTEND SẼ NHẬN THÔNG BÁO TỨC THÌ!
                    add_video_detection(
                        job_id=job_id,
                        person_name=name,
                        confidence=conf,
                        timestamp_sec=timestamp_sec,
                        timestamp_str=timestamp_str,
                        snapshot_path=snap_rel_path
                    )

            # Cập nhật tiến độ
            progress = min(99, int((frame_idx / max(1, total_frames)) * 100))
            if processed_count % 3 == 0 or frame_idx + step >= total_frames:
                update_job_status(job_id, "processing", progress, processed_frames=processed_count, total_frames=total_frames)

            frame_idx += step
            if frame_idx >= total_frames:
                break

        # Hoàn thành 100%
        update_job_status(job_id, "completed", 100, processed_frames=processed_count, total_frames=total_frames)
    except Exception as e:
        print(f"Lỗi khi phân tích video {job_id}: {e}")
        update_job_status(job_id, "error", 0)
    finally:
        cap.release()
