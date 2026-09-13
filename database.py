import sqlite3
import numpy as np
import json
from config import DB_PATH


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Khởi tạo các bảng dữ liệu nếu chưa tồn tại"""
    conn = get_db()
    cursor = conn.cursor()

    # Bảng lưu thông tin người cần tìm
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS persons
                   (
                       id
                       INTEGER
                       PRIMARY
                       KEY
                       AUTOINCREMENT,
                       name
                       TEXT
                       NOT
                       NULL
                       UNIQUE,
                       created_at
                       TIMESTAMP
                       DEFAULT
                       CURRENT_TIMESTAMP
                   )
                   ''')

    # Bảng lưu vector đặc trưng (Face Embedding 512D)
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS face_embeddings
                   (
                       id
                       INTEGER
                       PRIMARY
                       KEY
                       AUTOINCREMENT,
                       person_id
                       INTEGER,
                       embedding
                       TEXT
                       NOT
                       NULL,
                       FOREIGN
                       KEY
                   (
                       person_id
                   ) REFERENCES persons
                   (
                       id
                   ) ON DELETE CASCADE
                       )
                   ''')

    # Bảng lưu lịch sử phát hiện
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS detection_history
                   (
                       id
                       INTEGER
                       PRIMARY
                       KEY
                       AUTOINCREMENT,
                       person_name
                       TEXT
                       NOT
                       NULL,
                       confidence
                       REAL
                       NOT
                       NULL,
                       detected_at
                       TIMESTAMP
                       DEFAULT
                       CURRENT_TIMESTAMP
                   )
                   ''')

    conn.commit()
    conn.close()


def save_person_embedding(name: str, embedding: np.ndarray):
    """Lưu người mới hoặc thêm vector khuôn mặt vào CSDL"""
    init_db()
    conn = get_db()
    cursor = conn.cursor()

    # Kiểm tra xem người này đã tồn tại chưa
    cursor.execute("SELECT id FROM persons WHERE name = ?", (name,))
    row = cursor.fetchone()

    if row:
        person_id = row['id']
    else:
        cursor.execute("INSERT INTO persons (name) VALUES (?)", (name,))
        person_id = cursor.lastrowid

    emb_json = json.dumps(embedding.tolist())
    cursor.execute("INSERT INTO face_embeddings (person_id, embedding) VALUES (?, ?)", (person_id, emb_json))

    conn.commit()
    conn.close()
    return True


def load_all_embeddings():
    """Tải tất cả vector đặc trưng đã đăng ký lên bộ nhớ"""
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
    cursor.execute("INSERT INTO detection_history (person_name, confidence) VALUES (?, ?)",
                   (person_name, float(confidence)))
    conn.commit()
    conn.close()