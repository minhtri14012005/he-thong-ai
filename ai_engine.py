import cv2
import numpy as np
import insightface
from insightface.app import FaceAnalysis
from config import SIMILARITY_THRESHOLD, DET_SIZE
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
        """Trích xuất Vector 512D từ ảnh đăng ký"""
        faces = self.app.get(image)
        if len(faces) == 0:
            return None, "Không phát hiện thấy khuôn mặt nào trong ảnh!"

        largest_face = max(faces, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]))
        return largest_face.embedding, "Thành công"

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