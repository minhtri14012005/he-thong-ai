from typing import Optional
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from db.connection import get_db

router = APIRouter(prefix="/api/logs", tags=["Logs"])


@router.get("")
def get_detection_logs_api(person: Optional[str] = None):
    """API lấy nhật ký phát hiện: hỗ trợ dòng thời gian và phân nhóm theo từng người để chống chồng chéo"""
    db = get_db()

    # 1. Danh sách log dòng thời gian (có hỗ trợ lọc theo người)
    if isinstance(person, str) and person.strip() and person.strip() != "all":
        logs = db.execute(
            "SELECT id, person_name, confidence, strftime('%H:%M:%S', detected_at) as time_str, detected_at "
            "FROM detection_logs WHERE person_name = ? ORDER BY id DESC LIMIT 50",
            (person.strip(),)
        ).fetchall()
    else:
        logs = db.execute(
            "SELECT id, person_name, confidence, strftime('%H:%M:%S', detected_at) as time_str, detected_at "
            "FROM detection_logs ORDER BY id DESC LIMIT 50"
        ).fetchall()

    # 2. Phân nhóm theo từng người
    grouped_rows = db.execute("""
        SELECT 
            person_name,
            COUNT(*) as total_detections,
            MAX(confidence) as max_confidence,
            MAX(detected_at) as last_detected_at,
            strftime('%H:%M:%S', MAX(detected_at)) as last_seen_time
        FROM detection_logs
        GROUP BY person_name
        ORDER BY last_detected_at DESC
    """).fetchall()

    # Lấy ảnh đại diện (avatar) nếu có từ bảng persons & face_embeddings
    avatars = {}
    try:
        avatar_rows = db.execute("""
            SELECT p.name, f.image_path 
            FROM persons p 
            JOIN face_embeddings f ON p.id = f.person_id 
            WHERE f.image_path IS NOT NULL AND f.image_path != ''
            GROUP BY p.name
        """).fetchall()
        for r in avatar_rows:
            avatars[r['name']] = r['image_path']
    except Exception:
        pass

    # Lấy danh sách các lần gần nhất của riêng từng người
    people_groups = []
    for g in grouped_rows:
        p_name = g['person_name']
        p_logs = db.execute(
            "SELECT confidence, strftime('%H:%M:%S', detected_at) as time_str, detected_at "
            "FROM detection_logs WHERE person_name = ? ORDER BY id DESC LIMIT 10",
            (p_name,)
        ).fetchall()

        people_groups.append({
            "name": p_name,
            "total_count": g['total_detections'],
            "max_confidence": f"{g['max_confidence'] * 100:.1f}%",
            "last_seen": g['last_seen_time'],
            "last_detected_at": g['last_detected_at'],
            "avatar": avatars.get(p_name),
            "recent_logs": [
                {"confidence": f"{l['confidence'] * 100:.1f}%", "time": l["time_str"]}
                for l in p_logs
            ]
        })

    result_logs = [
        {"name": l["person_name"], "confidence": f"{l['confidence'] * 100:.1f}%", "time": l["time_str"] or ""}
        for l in logs
    ]

    return JSONResponse(content={
        "logs": result_logs,
        "people_groups": people_groups
    })


@router.delete("")
def clear_detection_logs_api():
    """Xóa toàn bộ nhật ký phát hiện camera"""
    db = get_db()
    db.execute("DELETE FROM detection_logs")
    db.commit()
    return {"status": "success", "message": "Đã xóa toàn bộ nhật ký phát hiện!"}
