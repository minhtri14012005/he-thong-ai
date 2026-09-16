import cv2
import numpy as np


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
            # Nếu đang trong trạng thái zoom mà tắt, mượt mà lùi về toàn cảnh (1.0x) thay vì giật hình
            if self.current_crop is not None and not np.allclose(self.current_crop, default_box, atol=2.0):
                self.target_crop = default_box.copy()
                self.current_crop = self.current_crop * (1.0 - self.smooth_factor) + self.target_crop * self.smooth_factor
                cx1, cy1, cx2, cy2 = self.current_crop
                cx1 = max(0, min(w - 10, int(round(cx1))))
                cy1 = max(0, min(h - 10, int(round(cy1))))
                cx2 = max(cx1 + 10, min(w, int(round(cx2))))
                cy2 = max(cy1 + 10, min(h, int(round(cy2))))
                crop_w = cx2 - cx1
                crop_h = cy2 - cy1
                cropped_img = frame[cy1:cy2, cx1:cx2]
                if cropped_img.size > 0 and crop_w > 0 and crop_h > 0:
                    zoomed_frame = cv2.resize(cropped_img, (w, h), interpolation=cv2.INTER_LINEAR)
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
                    return zoomed_frame, adj_detections, False

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
