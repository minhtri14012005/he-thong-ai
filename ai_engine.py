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
    VIDEO_DET_SIZE,
    ENABLE_PATCH_ZOOM_SCAN,
    UPLOAD_DIR,
    SNAPSHOT_DIR
)
from database import load_all_embeddings, update_job_status, add_video_detection


def nms_bboxes_kps(bboxes: np.ndarray, kpss: np.ndarray = None, iou_thresh: float = 0.45):
    """
    Khử trùng lặp Non-Maximum Suppression (NMS) cho bboxes và kpss giữa các pass quét.
    bboxes: ndarray (N, 5) dạng [x1, y1, x2, y2, score]
    kpss: ndarray (N, 5, 2) hoặc None
    """
    if bboxes is None or len(bboxes) == 0:
        return np.empty((0, 5), dtype=np.float32), (np.empty((0, 5, 2), dtype=np.float32) if kpss is not None else None)

    x1 = bboxes[:, 0]
    y1 = bboxes[:, 1]
    x2 = bboxes[:, 2]
    y2 = bboxes[:, 3]
    scores = bboxes[:, 4]

    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    order = scores.argsort()[::-1]

    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        if order.size == 1:
            break
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])

        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)

        inds = np.where(iou <= iou_thresh)[0]
        order = order[inds + 1]

    keep = np.array(keep, dtype=int)
    kept_bboxes = bboxes[keep]
    kept_kpss = kpss[keep] if kpss is not None else None
    return kept_bboxes, kept_kpss



class SmoothZoomController:
    """
    Bộ điều khiển Auto-Zoom kỹ thuật số thông minh:
    - Khi phát hiện có người ở xa trong phạm vi lớp học (diện tích mặt nhỏ):
      Tự động tính toán vùng bao quanh (bounding box gộp) và zoom-in mượt mà.
    - Khi không có người (hoặc người rời đi):
      Tự động out-zoom mượt mà quay về toàn cảnh góc rộng ban đầu (1.0x).
    - Sử dụng Exponential Moving Average (EMA) để chuyển động cực kỳ êm dịu, không giật rung.
    """
    def __init__(self, smooth_factor: float = 0.15, max_zoom: float = 2.5, no_face_hold_frames: int = 15):
        self.smooth_factor = smooth_factor
        self.max_zoom = max_zoom
        self.no_face_hold_frames = no_face_hold_frames
        self.no_face_count = 0
        self.current_crop = None  # [x1, y1, x2, y2]
        self.target_crop = None

    def update_and_zoom(self, frame: np.ndarray, detections: list, enabled: bool = True):
        """
        frame: khung hình gốc (H, W, 3)
        detections: danh sách dict [{"bbox": [x1, y1, x2, y2], "name": ..., "confidence": ...}]
        enabled: có bật Auto-Zoom hay không
        Trả về: (zoomed_frame, adjusted_detections, is_zooming)
        """
        h, w = frame.shape[:2]
        default_box = np.array([0.0, 0.0, float(w), float(h)], dtype=np.float32)

        if not enabled:
            self.current_crop = default_box.copy()
            self.target_crop = default_box.copy()
            self.no_face_count = 0
            return frame, detections, False

        if self.current_crop is None:
            self.current_crop = default_box.copy()

        valid_bboxes = [d["bbox"] for d in detections if d.get("bbox") is not None]

        if len(valid_bboxes) > 0:
            self.no_face_count = 0
            # Tính khung bao bao phủ tất cả khuôn mặt
            min_x = min(b[0] for b in valid_bboxes)
            min_y = min(b[1] for b in valid_bboxes)
            max_x = max(b[2] for b in valid_bboxes)
            max_y = max(b[3] for b in valid_bboxes)

            box_w = max_x - min_x
            box_h = max_y - min_y

            # Nếu người đã ở rất gần (mặt/người chiếm > 40% màn hình), không cần zoom
            if box_w / w > 0.40 or box_h / h > 0.40:
                target = default_box.copy()
            else:
                # Người ở xa (phòng học VN: khoảng cách 4-8m, mặt chỉ chiếm vài %)
                # Mở rộng lề an toàn (padding 70% để lấy cả phần thân/vai và lề xung quanh)
                pad_x = box_w * 0.70
                pad_y = box_h * 0.70
                target_w = max(box_w + 2 * pad_x, w / self.max_zoom)
                target_h = target_w * (h / w)

                # Giới hạn trong kích thước frame gốc
                target_w = min(target_w, float(w))
                target_h = min(target_h, float(h))

                center_x = (min_x + max_x) / 2.0
                center_y = (min_y + max_y) / 2.0

                t_x1 = max(0.0, min(float(w) - target_w, center_x - target_w / 2.0))
                t_y1 = max(0.0, min(float(h) - target_h, center_y - target_h / 2.0))
                target = np.array([t_x1, t_y1, t_x1 + target_w, t_y1 + target_h], dtype=np.float32)
        else:
            self.no_face_count += 1
            if self.no_face_count > self.no_face_hold_frames:
                # Không có người sau một số frame -> out-zoom về góc rộng toàn cảnh
                target = default_box.copy()
            else:
                # Giữ nguyên target gần nhất một khoảng ngắn để tránh giật hình
                target = self.target_crop if self.target_crop is not None else default_box.copy()

        self.target_crop = target

        # Làm mượt chuyển động (Exponential Moving Average)
        self.current_crop = self.current_crop * (1.0 - self.smooth_factor) + self.target_crop * self.smooth_factor

        cx1, cy1, cx2, cy2 = self.current_crop
        cx1 = max(0, min(w - 10, int(round(cx1))))
        cy1 = max(0, min(h - 10, int(round(cy1))))
        cx2 = max(cx1 + 10, min(w, int(round(cx2))))
        cy2 = max(cy1 + 10, min(h, int(round(cy2))))

        crop_w = cx2 - cx1
        crop_h = cy2 - cy1

        # Nếu độ zoom nhỏ hơn 5% so với khung hình thì coi như đang ở toàn cảnh
        is_zooming = (crop_w < w * 0.95 or crop_h < h * 0.95)

        # Cắt và phóng to (resize)
        cropped_img = frame[cy1:cy2, cx1:cx2]
        if cropped_img.size == 0 or crop_w <= 0 or crop_h <= 0:
            zoomed_frame = frame
            adj_detections = detections
        else:
            zoomed_frame = cv2.resize(cropped_img, (w, h), interpolation=cv2.INTER_LINEAR)
            # Điều chỉnh lại tọa độ bounding box hiển thị khớp chuẩn trên ảnh đã zoom
            scale_x = float(w) / float(crop_w)
            scale_y = float(h) / float(crop_h)
            adj_detections = []
            for d in detections:
                orig_b = d["bbox"]
                adj_b = np.array([
                    int((orig_b[0] - cx1) * scale_x),
                    int((orig_b[1] - cy1) * scale_y),
                    int((orig_b[2] - cx1) * scale_x),
                    int((orig_b[3] - cy1) * scale_y)
                ])
                adj_detections.append({
                    "bbox": adj_b,
                    "name": d["name"],
                    "confidence": d["confidence"]
                })

        return zoomed_frame, adj_detections, is_zooming


class HighAccuracyFaceEngine:
    def __init__(self):
        self.app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
        self.app.prepare(ctx_id=0, det_size=DET_SIZE)
        self.reload_known_faces()
        self.zoom_controller = SmoothZoomController()

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

    def process_frame_high_res(self, frame: np.ndarray):
        """
        Phát hiện và nhận diện khuôn mặt tầm xa (dành cho Video Upload toàn cảnh phòng học):
        1. Quét toàn cảnh độ phân giải cao (Global High-Res Pass) với VIDEO_DET_SIZE = (1280, 1280).
        2. Quét phân vùng tầm xa (Classroom Patch Zoom Scan): chia frame thành các cụm vùng học sinh (nửa trên / nửa giữa)
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
            det_thresh=0.40
        )
        if g_bboxes is not None and len(g_bboxes) > 0:
            candidate_bboxes.append(g_bboxes)
            if g_kpss is not None:
                candidate_kpss.append(g_kpss)

        # Pass 2: Quét phân vùng tầm xa (Classroom Patch Zoom Scan)
        if ENABLE_PATCH_ZOOM_SCAN and w >= 640 and h >= 360:
            # Các dãy bàn học sinh ở xa camera thường nằm ở khoảng 5% đến 75% chiều cao.
            # Chia chiều ngang thành các vùng có gối mép (overlap) để không sót mặt nằm ở biên vùng.
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
                    det_thresh=0.40
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

            matched_name = "Unknown"
            max_sim = 0.0

            if embedding is not None:
                norm_emb = np.linalg.norm(embedding)
                if norm_emb > 1e-6:
                    for name, emb_list in self.known_faces.items():
                        for known_emb in emb_list:
                            norm_known = np.linalg.norm(known_emb)
                            if norm_known > 1e-6:
                                sim = np.dot(embedding, known_emb) / (norm_emb * norm_known)
                                if sim > SIMILARITY_THRESHOLD and sim > max_sim:
                                    max_sim = sim
                                    matched_name = name

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


def analyze_video_background(
    job_id: str,
    video_path: str,
    sample_fps: float = 2.0,
    cooldown_sec: float = 1.5
):
    """
    Phân tích video nền siêu tốc:
    - Quét frame theo sample_fps (mặc định 2 khung hình / giây).
    - Không sleep chờ FPS thực -> quét 20s video trong vài giây.
    - Phát hiện bất kỳ người nào có trong DB:
      + Ngay lập tức cắt thumbnail snapshot khuôn mặt
      + Ghi ngay vào video_detections trong DB để Web push thông báo tức thì.
    - Cập nhật progress liên tục.
    """
    ai_engine = get_ai_engine()
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        update_job_status(job_id, "error", 0)
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 0 or fps > 120:
        fps = 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_sec = total_frames / fps if fps > 0 else 0

    step = max(1, int(round(fps / sample_fps)))
    frame_idx = 0
    processed_count = 0
    last_seen_time = {}  # person_name -> last_timestamp_sec

    # Bắt đầu phân tích
    update_job_status(job_id, "processing", 0, processed_frames=0, total_frames=total_frames)

    try:
        while True:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret or frame is None:
                break

            processed_count += 1
            timestamp_sec = frame_idx / fps
            timestamp_str = f"{int(timestamp_sec // 60):02d}:{int(timestamp_sec % 60):02d}"

            # Nhận diện khuôn mặt trong frame với cơ chế quét tầm xa (High-Res & Classroom Patch Zoom Scan)
            results = ai_engine.process_frame_high_res(frame)

            # Lọc ra những người có trong danh sách cần tìm (name != 'Unknown')
            found_persons = [r for r in results if r["name"] != "Unknown"]

            for p in found_persons:
                name = p["name"]
                conf = float(p["confidence"])
                last_time = last_seen_time.get(name, -999.0)

                # Kiểm tra debounce: nếu cùng 1 người xuất hiện liên tục thì cách ít nhất cooldown_sec giây mới ghi tiếp
                if timestamp_sec - last_time >= cooldown_sec:
                    last_seen_time[name] = timestamp_sec

                    # Cắt thumbnail khuôn mặt lưu lại làm bằng chứng (tối ưu cho cả khuôn mặt ở xa)
                    bbox = p["bbox"]
                    bx1, by1, bx2, by2 = bbox
                    fh, fw = frame.shape[:2]
                    bw = bx2 - bx1
                    bh = by2 - by1
                    pad_w = max(int(bw * 0.35), 20)
                    pad_h = max(int(bh * 0.35), 20)
                    sx1 = max(0, bx1 - pad_w)
                    sy1 = max(0, by1 - pad_h)
                    sx2 = min(fw, bx2 + pad_w)
                    sy2 = min(fh, by2 + pad_h)
                    crop_face = frame[sy1:sy2, sx1:sx2]

                    # Đảm bảo thumbnail sắc nét, nếu khuôn mặt ở xa có kích thước nhỏ thì upscale chất lượng cao
                    if crop_face.size > 0:
                        ch, cw = crop_face.shape[:2]
                        if ch < 120 or cw < 120:
                            scale = max(120.0 / ch, 120.0 / cw)
                            target_w = max(1, int(round(cw * scale)))
                            target_h = max(1, int(round(ch * scale)))
                            crop_face = cv2.resize(crop_face, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)

                    snap_filename = f"{job_id}_{uuid.uuid4().hex[:8]}.jpg"
                    snap_full_path = os.path.join(SNAPSHOT_DIR, snap_filename)
                    if crop_face.size > 0:
                        cv2.imwrite(snap_full_path, crop_face)
                    else:
                        cv2.imwrite(snap_full_path, frame)
                    snap_rel_path = f"static/snapshots/{snap_filename}"

                    # ĐẨY NGAY VÀO CSDL TẠI THỜI ĐIỂM NÀY -> FRONTEND SẼ NHẬN THÔNG BÁO TỨC THÌ!
                    add_video_detection(
                        job_id=job_id,
                        person_name=name,
                        confidence=conf,
                        timestamp_sec=timestamp_sec,
                        timestamp_str=timestamp_str,
                        snapshot_path=snap_rel_path
                    )

            # Cập nhật tiến độ
            progress = min(99, int((frame_idx / max(1, total_frames)) * 100))
            if processed_count % 3 == 0 or frame_idx + step >= total_frames:
                update_job_status(job_id, "processing", progress, processed_frames=processed_count, total_frames=total_frames)

            frame_idx += step
            if frame_idx >= total_frames:
                break

        # Hoàn thành 100%
        update_job_status(job_id, "completed", 100, processed_frames=processed_count, total_frames=total_frames)
    except Exception as e:
        print(f"Lỗi khi phân tích video {job_id}: {e}")
        update_job_status(job_id, "error", 0)
    finally:
        cap.release()


# Singleton Lazy Loading
_ai_engine_instance = None


def get_ai_engine():
    global _ai_engine_instance
    if _ai_engine_instance is None:
        _ai_engine_instance = HighAccuracyFaceEngine()
    return _ai_engine_instance