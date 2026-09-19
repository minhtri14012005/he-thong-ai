import json
from contextlib import closing
from db.connection import get_db, init_db


def serialize_video_detection(row):
    result = dict(row)
    # Preserve the original API contract: clients may prepend '/' themselves.
    # Newer records contain '/static/...' whereas legacy records contain 'static/...'.
    for key in ('snapshot_path', 'scene_path'):
        path = result.get(key)
        if path:
            normalized = path.replace('\\', '/').lstrip('/')
            if normalized.startswith('static/snapshots/'):
                result[key] = normalized
    return result


def create_video_job(job_id: str, filename: str, video_url: str, duration_sec: float = 0, total_frames: int = 0,
                     mode: str = 'legacy', settings=None):
    """Tạo tác vụ phân tích video mới trong cơ sở dữ liệu"""
    init_db()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO video_analysis_jobs (id, filename, video_url, status, progress, duration_sec, total_frames, mode, settings_json)
           VALUES (?, ?, ?, 'queued', 0, ?, ?, ?, ?)""",
        (job_id, filename, video_url, duration_sec, total_frames, mode, json.dumps(settings or {}, ensure_ascii=False))
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


def add_video_detection(job_id: str, person_name: str, confidence: float, timestamp_sec: float, timestamp_str: str, snapshot_path: str = None,
                        person_id=None, first_seen_sec=None, scene_path=None, zone=None, track_id=None,
                        confirmation_delay_sec=None):
    """Lưu kết quả phát hiện 1 người tại timestamp trong video"""
    with closing(get_db()) as conn, conn:
        cursor = conn.execute(
            """INSERT INTO video_detections (job_id, person_name, confidence, timestamp_sec, timestamp_str, snapshot_path,
               person_id, first_seen_sec, last_seen_sec, scene_path, zone, last_zone, track_id, confirmation_delay_sec)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (job_id, person_name, float(confidence), float(timestamp_sec), timestamp_str, snapshot_path,
             person_id, first_seen_sec, timestamp_sec, scene_path, zone, zone, track_id, confirmation_delay_sec)
        )
        return cursor.lastrowid


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
        """SELECT *
           FROM video_detections
           WHERE job_id = ? AND id > ?
           ORDER BY id ASC""",
        (job_id, last_id)
    )
    rows = cursor.fetchall()
    conn.close()
    return [serialize_video_detection(r) for r in rows]


def get_job_summary(job_id: str):
    """Lấy tổng hợp kết quả của 1 job (group by người và danh sách toàn bộ detections)"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT person_name, COUNT(*) as count, MAX(confidence) as max_conf, 
                  MIN(COALESCE(first_seen_sec, timestamp_sec)) as first_seen, MAX(COALESCE(last_seen_sec, timestamp_sec)) as last_seen
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
        "all_detections": [serialize_video_detection(r) for r in all_detections]
    }


def set_video_job_details(job_id, **fields):
    allowed = {'mode', 'settings_json', 'error_message', 'warning_message', 'scanned_frames',
               'scanned_until_sec', 'elapsed_sec', 'source_fps', 'frame_width', 'frame_height',
               'duration_sec', 'status', 'progress', 'processed_frames', 'total_frames'}
    if not fields or not set(fields).issubset(allowed):
        raise ValueError('Unsupported job fields')
    with closing(get_db()) as conn, conn:
        conn.execute('UPDATE video_analysis_jobs SET ' + ', '.join(f'{key}=?' for key in fields) + ' WHERE id=?',
                     (*fields.values(), job_id))


def update_video_appearance(detection_id, timestamp_sec, zone):
    with closing(get_db()) as conn, conn:
        conn.execute('UPDATE video_detections SET last_seen_sec=?, last_zone=? WHERE id=?',
                     (timestamp_sec, zone, detection_id))


def get_video_appearance_updates(job_id):
    with closing(get_db()) as conn:
        return [dict(row) for row in conn.execute(
            'SELECT id, last_seen_sec, last_zone FROM video_detections WHERE job_id=?', (job_id,))]


def mark_interrupted_video_jobs():
    """A single-server restart cannot resume the old in-memory gallery/decoder."""
    with closing(get_db()) as conn, conn:
        conn.execute("""UPDATE video_analysis_jobs SET status='error', error_message=?
                        WHERE status IN ('queued', 'processing')""",
                     ('Server đã khởi động lại. Kết quả đã lưu được giữ lại; hãy tải video lên để phân tích lại.',))
