from db.connection import get_db, init_db


def log_detection(person_name: str, confidence: float):
    """Ghi lịch sử phát hiện khuôn mặt thời gian thực"""
    init_db()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO detection_logs (person_name, confidence, detected_at) VALUES (?, ?, datetime('now', 'localtime'))",
        (person_name, float(confidence))
    )
    conn.commit()
    conn.close()
