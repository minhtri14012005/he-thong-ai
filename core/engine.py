import os
import cv2
import uuid
import numpy as np
import insightface
from insightface.app import FaceAnalysis
from insightface.app.common import Face

from config import (
    SIMILARITY_THRESHOLD,
    DET_SIZE,
    DET_THRESH,
    USE_GPU,
    GPU_DEVICE_ID,
    VIDEO_DET_SIZE,
    ENABLE_PATCH_ZOOM_SCAN,
    UPLOAD_DIR
)
from db.persons_repo import load_all_embeddings
from core.nms import nms_bboxes_kps
from core.zoom import SmoothZoomController


class HighAccuracyFaceEngine:
    def __init__(self):
        providers = ['CUDAExecutionProvider', 'CPUExecutionProvider'] if USE_GPU else ['CPUExecutionProvider']

        try:
            self.app = FaceAnalysis(name='buffalo_l', providers=providers)
            self.app.prepare(ctx_id=GPU_DEVICE_ID if USE_GPU else -1, det_size=DET_SIZE)
            dev_label = 'NVIDIA GPU CUDA:0 (RTX 4050)' if USE_GPU else 'CPU'
            print(f"[AI Engine] Khoi tao thanh cong tren: {dev_label} - DET_SIZE={DET_SIZE}")
        except Exception as e:
            print(f"[AI Engine] Loi khoi tao GPU ({e}), fallback sang CPU")
            self.app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
            self.app.prepare(ctx_id=-1, det_size=DET_SIZE)

        # Cấu hình ngưỡng phát hiện cho SCRFD
        if hasattr(self.app, 'det_model') and hasattr(self.app.det_model, 'det_thresh'):
            self.app.det_model.det_thresh = DET_THRESH

        self.reload_known_faces()
        self.zoom_controller = SmoothZoomController()

    def reload_known_faces(self):
        """Cập nhật danh sách vector từ CSDL lên RAM và tiền xử lý ma trận so khớp nhanh"""
        self.known_faces = load_all_embeddings()

        # Tạo ma trận numpy chuẩn hóa sẵn để so sánh vector cực nhanh qua matrix dot product
        emb_list = []
        names_list = []
        for name, vectors in self.known_faces.items():
            for vec in vectors:
                arr = np.array(vec, dtype=np.float32)
                norm = np.linalg.norm(arr)
                if norm > 1e-6:
                    emb_list.append(arr / norm)
                    names_list.append(name)

        if len(emb_list) > 0:
            self.known_matrix = np.array(emb_list, dtype=np.float32)  # Shape (N, 512)
            self.known_names = names_list
        else:
            self.known_matrix = None
            self.known_names = []

    def match_face(self, embedding: np.ndarray):
        """So khớp vector 512D với CSDL bằng 1 phép nhân ma trận tối ưu BLAS/GPU"""
        if self.known_matrix is None or len(self.known_names) == 0 or embedding is None:
            return "Unknown", 0.0

        norm = np.linalg.norm(embedding)
        if norm <= 1e-6:
            return "Unknown", 0.0

        norm_emb = embedding / norm
        sims = np.dot(self.known_matrix, norm_emb)
        best_idx = int(np.argmax(sims))
        best_sim = float(sims[best_idx])

        if best_sim > SIMILARITY_THRESHOLD:
            return self.known_names[best_idx], best_sim
        return "Unknown", best_sim

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

    def process_frame(self, frame: np.ndarray, max_num: int = 0):
        """Phát hiện và nhận diện khuôn mặt trong 1 khung hình camera thời gian thực"""
        faces = self.app.get(frame, max_num=max_num)
        results = []

        for face in faces:
            bbox = face.bbox.astype(int)
            embedding = face.embedding

            matched_name, max_sim = self.match_face(embedding)

            results.append({
                "bbox": bbox,
                "name": matched_name,
                "confidence": max_sim,
                "embedding": embedding
            })

        return results

    def process_frame_high_res(self, frame: np.ndarray):
        """
        Phát hiện và nhận diện khuôn mặt tầm xa (dành cho Video Toàn Cảnh Phòng Học):
        1. Quét toàn cảnh độ phân giải cao (Global High-Res Pass) với VIDEO_DET_SIZE = (1280, 1280).
        2. Quét phân vùng tầm xa (Classroom Patch Zoom Scan): chia frame thành các cụm vùng học sinh (nửa trên / giữa)
           để dò quét ở tỉ lệ điểm ảnh 1:1, bắt trọn các khuôn mặt nhỏ ở bàn xa nhất.
        3. Gộp và khử trùng lặp (NMS) với iou_thresh=0.45.
        4. Trích xuất vector đặc trưng 512D từ khung hình gốc và so khớp với CSDL.
        """
        h, w = frame.shape[:2]
        candidate_bboxes = []
        candidate_kpss = []

        # Pass 1: Quét toàn cảnh độ phân giải cao (Global High-Res Pass)
        g_bboxes, g_kpss = self.app.det_model.detect(
            frame,
            input_size=VIDEO_DET_SIZE,
            det_thresh=DET_THRESH
        )
        if g_bboxes is not None and len(g_bboxes) > 0:
            candidate_bboxes.append(g_bboxes)
            if g_kpss is not None:
                candidate_kpss.append(g_kpss)

        # Pass 2: Quét phân vùng tầm xa (Classroom Patch Zoom Scan)
        if ENABLE_PATCH_ZOOM_SCAN and w >= 640 and h >= 360:
            py1 = int(h * 0.05)
            py2 = int(h * 0.75)

            patches = []
            if w >= 1400:
                # Với video rộng (Full HD 1080p, 2K): 3 phân vùng gối mép
                patches.append((0, py1, int(w * 0.45), py2))
                patches.append((int(w * 0.30), py1, int(w * 0.70), py2))
                patches.append((int(w * 0.55), py1, w, py2))
            else:
                # Với video 720p hoặc khung hình vừa: 2 phân vùng gối mép
                patches.append((0, py1, int(w * 0.60), py2))
                patches.append((int(w * 0.40), py1, w, py2))

            for px1, p_y1, px2, p_y2 in patches:
                patch_img = frame[p_y1:p_y2, px1:px2]
                if patch_img.size == 0:
                    continue

                p_bboxes, p_kpss = self.app.det_model.detect(
                    patch_img,
                    input_size=(640, 640),
                    det_thresh=DET_THRESH
                )
                if p_bboxes is not None and len(p_bboxes) > 0:
                    p_bboxes_orig = p_bboxes.copy()
                    p_bboxes_orig[:, 0] += px1
                    p_bboxes_orig[:, 2] += px1
                    p_bboxes_orig[:, 1] += p_y1
                    p_bboxes_orig[:, 3] += p_y1

                    p_kpss_orig = None
                    if p_kpss is not None:
                        p_kpss_orig = p_kpss.copy()
                        p_kpss_orig[:, :, 0] += px1
                        p_kpss_orig[:, :, 1] += p_y1

                    candidate_bboxes.append(p_bboxes_orig)
                    if p_kpss_orig is not None:
                        candidate_kpss.append(p_kpss_orig)

        # Nếu không tìm thấy khuôn mặt nào
        if len(candidate_bboxes) == 0:
            return []

        all_bboxes = np.vstack(candidate_bboxes)
        all_kpss = np.vstack(candidate_kpss) if len(candidate_kpss) == len(candidate_bboxes) else None

        # Pass 3: Gộp và khử trùng lặp qua NMS
        final_bboxes, final_kpss = nms_bboxes_kps(all_bboxes, all_kpss, iou_thresh=0.45)

        # Pass 4: Trích xuất đặc trưng nhận diện và so khớp CSDL
        results = []
        rec_model = self.app.models.get('recognition')

        for idx in range(len(final_bboxes)):
            bbox = final_bboxes[idx, 0:4].astype(int)
            det_score = float(final_bboxes[idx, 4])
            kps = final_kpss[idx] if final_kpss is not None else None

            face = Face(bbox=bbox, kps=kps, det_score=det_score)

            embedding = None
            if rec_model is not None:
                try:
                    rec_model.get(frame, face)
                    embedding = getattr(face, 'embedding', None)
                except Exception:
                    # Fallback crop nếu landmarks nằm sát biên
                    bx1, by1, bx2, by2 = max(0, bbox[0]), max(0, bbox[1]), min(w, bbox[2]), min(h, bbox[3])
                    crop = frame[by1:by2, bx1:bx2]
                    if crop.size > 0:
                        try:
                            resized_crop = cv2.resize(crop, (112, 112))
                            embedding = rec_model.get_feat(resized_crop).flatten()
                        except Exception:
                            pass

            matched_name, max_sim = self.match_face(embedding)

            results.append({
                "bbox": bbox,
                "name": matched_name,
                "confidence": float(max_sim),
                "det_score": det_score
            })

        return results

    def apply_auto_zoom(self, frame: np.ndarray, detections: list, enabled: bool = True):
        """Áp dụng bộ điều khiển Auto-Zoom"""
        return self.zoom_controller.update_and_zoom(frame, detections, enabled=enabled)


# Singleton Lazy Loading
_ai_engine_instance = None


def get_ai_engine() -> HighAccuracyFaceEngine:
    global _ai_engine_instance
    if _ai_engine_instance is None:
        _ai_engine_instance = HighAccuracyFaceEngine()
    return _ai_engine_instance
