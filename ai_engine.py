import os
import cv2
import uuid
import numpy as np
import insightface
from insightface.app import FaceAnalysis
from config import SIMILARITY_THRESHOLD, DET_SIZE, UPLOAD_DIR
from database import load_all_embeddings


class HighAccuracyFaceEngine:
    def __init__(self):
        self.app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
        self.app.prepare(ctx_id=0, det_size=DET_SIZE)
        self.reload_known_faces()

    def reload_known_faces(self):
        """Cập nhật danh sách vector từ CSDL"""
        self.known_faces = load_all_embeddings()

    def extract_face_embedding(self, image: np.ndarray):
        """Trích xuất Vector 512D và tự động cắt lưu ảnh mẫu vào static/uploads"""
        faces = self.app.get(image)
        if len(faces) == 0:
            return None, None, "Không phát hiện thấy khuôn mặt nào trong ảnh!"

        # Lấy khuôn mặt lớn nhất trong ảnh
        largest_face = max(faces, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]))

        # 1. Cắt vùng khuôn mặt (Crop Face)
        bbox = largest_face.bbox.astype(int)
        h, w, _ = image.shape
        x1, y1, x2, y2 = max(0, bbox[0]), max(0, bbox[1]), min(w, bbox[2]), min(h, bbox[3])
        cropped_face = image[y1:y2, x1:x2]

        # 2. Tạo tên file ngẫu nhiên và lưu ảnh thực tế vào static/uploads
        filename = f"{uuid.uuid4().hex}.jpg"
        full_path = os.path.join(UPLOAD_DIR, filename)

        if cropped_face.size > 0:
            cv2.imwrite(full_path, cropped_face)
        else:
            cv2.imwrite(full_path, image)  # Fallback lưu cả ảnh nếu crop lỗi

        # Đường dẫn tương đối dùng để lưu vào CSDL cho web đọc
        rel_path = f"static/uploads/{filename}"

        return largest_face.embedding, rel_path, "Thành công"

    def process_frame(self, frame: np.ndarray):
        """Phát hiện và Nhận diện khuôn mặt trong 1 khung hình"""
        faces = self.app.get(frame)
        results = []

        for face in faces:
            bbox = face.bbox.astype(int)
            embedding = face.embedding

            matched_name = "Unknown"
            max_sim = 0.0

            # So sánh với tất cả các vector mẫu của từng người
            for name, emb_list in self.known_faces.items():
                for known_emb in emb_list:
                    sim = np.dot(embedding, known_emb) / (np.linalg.norm(embedding) * np.linalg.norm(known_emb))
                    if sim > SIMILARITY_THRESHOLD and sim > max_sim:
                        max_sim = sim
                        matched_name = name

            results.append({
                "bbox": bbox,
                "name": matched_name,
                "confidence": max_sim
            })

        return results


# Singleton Lazy Loading
_ai_engine_instance = None


def get_ai_engine():
    global _ai_engine_instance
    if _ai_engine_instance is None:
        _ai_engine_instance = HighAccuracyFaceEngine()
    return _ai_engine_instance