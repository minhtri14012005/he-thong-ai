from db.connection import get_db, init_db


def create_video_job(job_id: str, filename: str, video_url: str, duration_sec: float = 0, total_frames: int = 0):
    """Tạo tác vụ phân tích video mới trong cơ sở dữ liệu"""
    init_db()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO video_analysis_jobs (id, filename, video_url, status, progress, duration_sec, total_frames)
           VALUES (?, ?, ?, 'processing', 0, ?, ?)""",
        (job_id, filename, video_url, duration_sec, total_frames)
    )
    conn.commit()
    conn.close()


def update_job_status(job_id: str, status: str, progress: int, processed_frames: int = 0, total_frames: int = 0):
    """Cập nhật tiến trình và trạng thái xử lý video job"""
    conn = get_db()
    cursor = conn.cursor()
    if total_frames > 0:
        cursor.execute(
            """UPDATE video_analysis_jobs 
               SET status = ?, progress = ?, processed_frames = ?, total_frames = ?
               WHERE id = ?""",
            (status, progress, processed_frames, total_frames, job_id)
        )
    else:
        cursor.execute(
            """UPDATE video_analysis_jobs 
               SET status = ?, progress = ?, processed_frames = ?
               WHERE id = ?""",
            (status, progress, processed_frames, job_id)
        )
    conn.commit()
    conn.close()


def add_video_detection(job_id: str, person_name: str, confidence: float, timestamp_sec: float, timestamp_str: str, snapshot_path: str = None):
    """Lưu kết quả phát hiện 1 người tại timestamp trong video"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO video_detections (job_id, person_name, confidence, timestamp_sec, timestamp_str, snapshot_path)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (job_id, person_name, float(confidence), float(timestamp_sec), timestamp_str, snapshot_path)
    )
    detection_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return detection_id


def get_video_job(job_id: str):
    """Lấy thông tin chi tiết một job phân tích video"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM video_analysis_jobs WHERE id = ?", (job_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def get_video_detections_since(job_id: str, last_id: int = 0):
    """Lấy danh sách các phát hiện mới hơn last_id để đẩy realtime ra Web"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT id, job_id, person_name, confidence, timestamp_sec, timestamp_str, snapshot_path, created_at
           FROM video_detections
           WHERE job_id = ? AND id > ?
           ORDER BY id ASC""",
        (job_id, last_id)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_job_summary(job_id: str):
    """Lấy tổng hợp kết quả của 1 job (group by người và danh sách toàn bộ detections)"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT person_name, COUNT(*) as count, MAX(confidence) as max_conf, 
                  MIN(timestamp_sec) as first_seen, MAX(timestamp_sec) as last_seen
           FROM video_detections
           WHERE job_id = ?
           GROUP BY person_name
           ORDER BY first_seen ASC""",
        (job_id,)
    )
    summary_rows = cursor.fetchall()

    cursor.execute(
        """SELECT * FROM video_detections WHERE job_id = ? ORDER BY timestamp_sec ASC""",
        (job_id,)
    )
    all_detections = cursor.fetchall()
    conn.close()

    return {
        "summary": [dict(r) for r in summary_rows],
        "all_detections": [dict(r) for r in all_detections]
    }
