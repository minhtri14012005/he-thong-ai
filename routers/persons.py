import os
import uuid
import cv2
import numpy as np
from typing import List
from fastapi import APIRouter, UploadFile, File, Form, Query
from fastapi.responses import JSONResponse

from config import UPLOAD_DIR
from db.connection import get_db
from db.persons_repo import (
    save_person_embedding,
    get_person_embeddings,
    delete_single_embedding
)
from core.engine import get_ai_engine

router = APIRouter(prefix="/api", tags=["Persons"])


@router.get("/persons")
def get_persons_api():
    """Lấy danh sách tất cả người dùng và số lượng ảnh mẫu đã đăng ký"""
    db = get_db()
    persons = db.execute("SELECT id, name, created_at FROM persons").fetchall()
    result = []
    for p in persons:
        p_id, name, created_at = p["id"], p["name"], p["created_at"]
        count = db.execute("SELECT COUNT(*) FROM face_embeddings WHERE person_id = ?", (p_id,)).fetchone()[0]
        result.append({"id": p_id, "name": name, "sample_count": count, "created_at": created_at})
    return JSONResponse(content={"persons": result})


@router.get("/person_embeddings")
def get_person_embeddings_query(person_id: int = Query(...)):
    """Lấy danh sách mẫu ảnh theo Query Param"""
    try:
        embeddings = get_person_embeddings(person_id)
        return JSONResponse(content={"embeddings": embeddings})
    except Exception as e:
        print(f"Lỗi khi lấy embeddings: {e}")
        return JSONResponse(status_code=500, content={"message": str(e)})


@router.get("/person_embeddings/{person_id}")
def get_person_embeddings_path(person_id: int):
    """Lấy danh sách mẫu ảnh theo Path Param"""
    try:
        embeddings = get_person_embeddings(person_id)
        return JSONResponse(content={"embeddings": embeddings})
    except Exception as e:
        print(f"Lỗi khi lấy embeddings: {e}")
        return JSONResponse(status_code=500, content={"message": str(e)})


@router.delete("/embeddings/{embedding_id}")
def delete_embedding_api(embedding_id: int):
    """Xóa 1 mẫu ảnh của người dùng"""
    delete_single_embedding(embedding_id)
    get_ai_engine().reload_known_faces()
    return {"status": "success", "message": "Đã xóa 1 mẫu ảnh thành công!"}


@router.post("/register")
async def register_person_api(name: str = Form(...), files: List[UploadFile] = File(...)):
    """Đăng ký người dùng mới hoặc thêm mẫu ảnh nhận diện cho người đã có"""
    ai_engine = get_ai_engine()
    success_count = 0

    for file in files:
        contents = await file.read()
        if not contents:
            continue

        nparr = np.frombuffer(contents, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is not None:
            res = ai_engine.extract_face_embedding(img)
            if len(res) == 3:
                embedding, rel_path, msg = res
            else:
                embedding, msg = res
                rel_path = None

            if embedding is not None:
                if not rel_path:
                    ext = os.path.splitext(file.filename)[1] or ".jpg"
                    filename = f"{uuid.uuid4().hex}{ext}"
                    full_file_path = os.path.join(UPLOAD_DIR, filename)

                    with open(full_file_path, "wb") as f:
                        f.write(contents)

                    rel_path = f"static/uploads/{filename}"

                if save_person_embedding(name, embedding, rel_path):
                    success_count += 1

    if success_count > 0:
        ai_engine.reload_known_faces()
        return {"status": "success", "message": f"Đã lưu thành công {success_count} mẫu ảnh cho {name}"}
    return {"status": "error", "message": "Không thể trích xuất khuôn mặt từ các file đã chọn!"}


@router.put("/persons/rename")
def rename_person_api(person_id: int = Form(...), new_name: str = Form(...)):
    """Đổi tên người dùng trong CSDL"""
    db = get_db()
    db.execute("UPDATE persons SET name = ? WHERE id = ?", (new_name, person_id))
    db.commit()
    get_ai_engine().reload_known_faces()
    return {"status": "success", "message": "Đã đổi tên thành công!"}


@router.delete("/persons/{person_id}")
def delete_person_api(person_id: int):
    """Xóa hoàn toàn người dùng và toàn bộ dữ liệu mẫu ảnh liên quan"""
    db = get_db()
    rows = db.execute("SELECT image_path FROM face_embeddings WHERE person_id = ?", (person_id,)).fetchall()

    for r in rows:
        if r['image_path'] and os.path.exists(r['image_path']):
            try:
                os.remove(r['image_path'])
            except Exception:
                pass

    db.execute("DELETE FROM face_embeddings WHERE person_id = ?", (person_id,))
    db.execute("DELETE FROM persons WHERE id = ?", (person_id,))
    db.commit()
    get_ai_engine().reload_known_faces()
    return {"status": "success", "message": "Đã xóa người dùng khỏi hệ thống!"}
