import os
import json
import numpy as np
from config import BASE_DIR
from db.connection import get_db, init_db


def save_person_embedding(name: str, embedding: np.ndarray, image_path: str = None) -> bool:
    """Lưu thông tin người dùng, Vector đặc trưng 512D và đường dẫn ảnh mẫu"""
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
    """Lấy danh sách ID mẫu và đường dẫn ảnh mẫu tương ứng của một người"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, image_path FROM face_embeddings WHERE person_id = ?", (person_id,))
    rows = cursor.fetchall()
    conn.close()

    result = []
    for r in rows:
        path_str = r['image_path'] if r['image_path'] else ""
        if path_str and not path_str.startswith("/") and not path_str.startswith("http"):
            path_str = "/" + path_str.replace("\\", "/")

        result.append({
            "id": int(r['id']),
            "image_path": path_str
        })
    return result


def delete_single_embedding(embedding_id: int):
    """Xóa 1 mẫu ảnh (xóa bản ghi trong DB và xóa file ảnh trên ổ đĩa)"""
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
    """Tải tất cả vector đặc trưng đã đăng ký lên bộ nhớ phục vụ so khớp AI"""
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


def load_live_gallery():
    """Keep disabled identities in comparisons to reject ambiguous matches."""
    init_db()
    conn = get_db()
    try:
        rows = conn.execute('''SELECT p.id, p.name, p.search_enabled, e.embedding
                               FROM persons p JOIN face_embeddings e ON p.id=e.person_id''').fetchall()
        return [(int(r['id']), r['name'], bool(r['search_enabled']),
                 np.array(json.loads(r['embedding']), dtype=np.float32)) for r in rows]
    finally:
        conn.close()
