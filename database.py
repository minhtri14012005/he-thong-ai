import os
import json
import sqlite3
import numpy as np
from config import DB_PATH, BASE_DIR


def get_db():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Khởi tạo các bảng dữ liệu nếu chưa tồn tại"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS persons(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS face_embeddings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_id INTEGER,
        embedding TEXT NOT NULL,
        image_path TEXT,
        FOREIGN KEY (person_id) REFERENCES persons (id) ON DELETE CASCADE
    )
    ''')

    try:
        cursor.execute("ALTER TABLE face_embeddings ADD COLUMN image_path TEXT")
    except sqlite3.OperationalError:
        pass

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS detection_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_name TEXT NOT NULL,
        confidence REAL NOT NULL,
        detected_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
    )
    ''')

    conn.commit()
    conn.close()


def save_person_embedding(name: str, embedding: np.ndarray, image_path: str = None):
    """Lưu thông tin người dùng, Vector đặc trưng VÀ Đường dẫn ảnh mẫu"""
    init_db()
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM persons WHERE name = ?", (name,))
    row = cursor.fetchone()

    if row:
        person_id = row['id']
    else:
        cursor.execute("INSERT INTO persons (name) VALUES (?)", (name,))
        person_id = cursor.lastrowid

    emb_json = json.dumps(embedding.tolist())
    cursor.execute(
        "INSERT INTO face_embeddings (person_id, embedding, image_path) VALUES (?, ?, ?)",
        (person_id, emb_json, image_path)
    )

    conn.commit()
    conn.close()
    return True


def get_person_embeddings(person_id: int):
    """Lấy danh sách ID mẫu và Đường dẫn ảnh mẫu tương ứng của 1 người"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, image_path FROM face_embeddings WHERE person_id = ?", (person_id,))
    rows = cursor.fetchall()
    conn.close()

    result = []
    for r in rows:
        path_str = r['image_path'] if r['image_path'] else ""
        # Định dạng chuẩn đường dẫn web để hiển thị
        if path_str and not path_str.startswith("/") and not path_str.startswith("http"):
            path_str = "/" + path_str.replace("\\", "/")

        result.append({
            "id": int(r['id']),
            "image_path": path_str
        })
    return result


def delete_single_embedding(embedding_id: int):
    """Xóa 1 mẫu ảnh (xóa record trong DB và file ảnh trên ổ đĩa)"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT image_path FROM face_embeddings WHERE id = ?", (embedding_id,))
    row = cursor.fetchone()
    if row and row['image_path']:
        clean_path = row['image_path'].lstrip("/")
        full_path = os.path.join(BASE_DIR, clean_path)
        if os.path.exists(full_path):
            try:
                os.remove(full_path)
            except Exception as e:
                print(f"Không thể xóa file ảnh: {e}")

    cursor.execute("DELETE FROM face_embeddings WHERE id = ?", (embedding_id,))
    conn.commit()
    conn.close()


def load_all_embeddings():
    """Tải tất cả vector đặc trưng đã đăng ký lên bộ nhớ AI"""
    init_db()
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
    SELECT p.name, e.embedding
    FROM persons p
    JOIN face_embeddings e ON p.id = e.person_id
    ''')

    rows = cursor.fetchall()
    conn.close()

    known_faces = {}
    for row in rows:
        name = row['name']
        emb = np.array(json.loads(row['embedding']), dtype=np.float32)
        if name not in known_faces:
            known_faces[name] = []
        known_faces[name].append(emb)

    return known_faces


def log_detection(person_name: str, confidence: float):
    """Ghi lịch sử phát hiện"""
    init_db()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO detection_logs (person_name, confidence, detected_at) VALUES (?, ?, datetime('now', 'localtime'))",
        (person_name, float(confidence))
    )
    conn.commit()
    conn.close()