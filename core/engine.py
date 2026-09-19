import os
import cv2
import uuid
import threading
from functools import wraps
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
from db.persons_repo import load_live_gallery
from config import (LIVE_DET_SIZE, LIVE_MATCH_THRESHOLD, LIVE_MATCH_MARGIN,
                    LIVE_MIN_FACE_PIXELS, LIVE_MIN_SHARPNESS, VIDEO_SCAN_PROFILES)


def serialized_inference(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self.inference_lock:
            return method(self, *args, **kwargs)
    return wrapped


class HighAccuracyFaceEngine:
    def __init__(self):
        self.inference_lock = threading.RLock()
        self.gallery_version = 0
        providers = ['CUDAExecutionProvider', 'CPUExecutionProvider'] if USE_GPU else ['CPUExecutionProvider']

        try:
            self.app = FaceAnalysis(name='buffalo_l', providers=providers, allowed_modules=['detection', 'recognition'])
            self.app.prepare(ctx_id=GPU_DEVICE_ID if USE_GPU else -1, det_size=DET_SIZE)
            print(f"[AI Engine] Providers: {self.runtime_providers()} - DET_SIZE={DET_SIZE}")
        except Exception as e:
            print(f"[AI Engine] Loi khoi tao GPU ({e}), fallback sang CPU")
            self.app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'], allowed_modules=['detection', 'recognition'])
            self.app.prepare(ctx_id=-1, det_size=DET_SIZE)

        # Cấu hình ngưỡng phát hiện cho SCRFD
        if hasattr(self.app, 'det_model') and hasattr(self.app.det_model, 'det_thresh'):
            self.app.det_model.det_thresh = DET_THRESH

        self.reload_known_faces()
        self.zoom_controller = SmoothZoomController()

    @serialized_inference
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

        rows = load_live_gallery()
        rows = [r for r in rows if np.linalg.norm(r[3]) > 1e-6]
        self.live_rows = rows
        self.live_matrix = (np.stack([r[3] / np.linalg.norm(r[3]) for r in rows]) if rows else None)
        self.gallery_version += 1

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

    @serialized_inference
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

    @serialized_inference
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

    @serialized_inference
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

    def match_live_face(self, embedding):
        if embedding is None or self.live_matrix is None:
            return None, 'Unknown', 0.0
        norm = np.linalg.norm(embedding)
        if norm < 1e-6:
            return None, 'Unknown', 0.0
        scores = self.live_matrix @ (embedding / norm)
        people = {}
        for row, score in zip(self.live_rows, scores):
            pid, name, enabled, _ = row
            if pid not in people or score > people[pid][0]:
                people[pid] = (float(score), name, enabled)
        ranked = sorted(people.items(), key=lambda item: item[1][0], reverse=True)
        pid, (score, name, enabled) = ranked[0]
        second = ranked[1][1][0] if len(ranked) > 1 else -1.0
        if enabled and score >= LIVE_MATCH_THRESHOLD and score - second >= LIVE_MATCH_MARGIN:
            return pid, name, score
        return None, 'Unknown', score

    @serialized_inference
    def process_frame_live(self, frame, tile_index=0):
        """Global pass + one rotating overlapping tile; alignment uses original pixels."""
        h, w = frame.shape[:2]
        regions = [(0, 0, w, h, LIVE_DET_SIZE)]
        # Six overlapping tiles cover the entire scene, including front desks.
        if w >= 960 and h >= 540:
            tw, th = int(w * 0.45), int(h * 0.60)
            col, row = tile_index % 3, (tile_index // 3) % 2
            x, y = int(col * (w - tw) / 2), row * (h - th)
            regions.append((x, y, x + tw, y + th, (640, 640)))
        return self._recognize_regions(frame, regions, self.match_live_face)

    @serialized_inference
    def process_frame_video(self, frame, gallery, mode='detailed', tile_index=0):
        profile = VIDEO_SCAN_PROFILES[mode]
        h, w = frame.shape[:2]
        regions = [(0, 0, w, h, VIDEO_DET_SIZE)]
        if w >= 640 and h >= 360:
            tw, th = int(w * 0.45), int(h * 0.60)
            for index in (range(6) if profile['all_tiles'] else [tile_index % 6]):
                col, row = index % 3, index // 3
                x, y = int(col * (w-tw) / 2), row * (h-th)
                size = profile['tile_size']
                regions.append((x, y, x+tw, y+th, (size, size)))
        return self._recognize_regions(frame, regions, gallery.match)

    def _recognize_regions(self, frame, regions, match):
        """Call under inference_lock. All embedding crops use original image pixels."""
        h, w = frame.shape[:2]
        boxes, landmarks = [], []
        for x1, y1, x2, y2, size in regions:
            b, k = self.app.det_model.detect(frame[y1:y2, x1:x2], input_size=size)
            if b is None or len(b) == 0 or k is None:
                continue
            b, k = b.copy(), k.copy()
            b[:, [0, 2]] += x1
            b[:, [1, 3]] += y1
            k[:, :, 0] += x1
            k[:, :, 1] += y1
            boxes.append(b)
            landmarks.append(k)
        if not boxes:
            return []
        boxes, landmarks = nms_bboxes_kps(np.vstack(boxes), np.vstack(landmarks), 0.45)
        results = []
        rec = self.app.models.get('recognition')
        for box, kps in zip(boxes, landmarks):
            bbox = box[:4].astype(int)
            bbox[[0, 2]] = np.clip(bbox[[0, 2]], 0, w)
            bbox[[1, 3]] = np.clip(bbox[[1, 3]], 0, h)
            x1, y1, x2, y2 = bbox
            crop = frame[y1:y2, x1:x2]
            size_ok = min(x2 - x1, y2 - y1) >= LIVE_MIN_FACE_PIXELS
            sharpness = float(cv2.Laplacian(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()) if crop.size else 0.0
            # Reject severely asymmetric landmarks; not a calibrated pose estimator.
            eye_span = float(np.linalg.norm(kps[1] - kps[0]))
            nose_offset = abs(float(kps[2, 0] - (kps[0, 0] + kps[1, 0]) / 2))
            pose_ok = eye_span >= 6 and nose_offset <= eye_span * 0.65
            quality_ok = bool(size_ok and sharpness >= LIVE_MIN_SHARPNESS and pose_ok)
            reason = '' if quality_ok else ('Mặt nhỏ' if not size_ok else ('Mờ' if sharpness < LIVE_MIN_SHARPNESS else 'Góc mặt lệch'))
            embedding = None
            if quality_ok and rec is not None:
                face = Face(bbox=bbox, kps=kps, det_score=float(box[4]))
                rec.get(frame, face)
                embedding = face.embedding
            pid, name, score = match(embedding)
            results.append(dict(bbox=bbox.tolist(), person_id=pid, name=name, confidence=score,
                                embedding=embedding, quality_ok=quality_ok, quality_reason=reason,
                                face_pixels=int(min(x2-x1, y2-y1)), sharpness=round(sharpness, 1)))
        return results

    def runtime_providers(self):
        return {name: model.session.get_providers() for name, model in self.app.models.items()
                if hasattr(model, 'session')}

    def apply_auto_zoom(self, frame: np.ndarray, detections: list, enabled: bool = True):
        """Áp dụng bộ điều khiển Auto-Zoom"""
        return self.zoom_controller.update_and_zoom(frame, detections, enabled=enabled)


# Singleton Lazy Loading
_ai_engine_instance = None
_ai_engine_lock = threading.Lock()


def get_ai_engine() -> HighAccuracyFaceEngine:
    global _ai_engine_instance
    with _ai_engine_lock:
        if _ai_engine_instance is None:
            _ai_engine_instance = HighAccuracyFaceEngine()
    return _ai_engine_instance
