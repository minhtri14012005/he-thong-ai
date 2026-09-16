import numpy as np
from config import TRACKER_MAX_AGE, TRACKER_MIN_HITS, TRACKER_IOU_THRESH, RECOGNIZE_INTERVAL


def compute_iou(box1, box2):
    """Tính toán Intersection over Union (IoU) giữa 2 bounding box [x1, y1, x2, y2]"""
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])

    inter_w = max(0.0, x2 - x1)
    inter_h = max(0.0, y2 - y1)
    inter_area = inter_w * inter_h

    area1 = max(0.0, (box1[2] - box1[0]) * (box1[3] - box1[1]))
    area2 = max(0.0, (box2[2] - box2[0]) * (box2[3] - box2[1]))

    union_area = area1 + area2 - inter_area
    if union_area <= 0.0:
        return 0.0
    return inter_area / union_area


class FaceTrack:
    """Đại diện cho 1 khuôn mặt đang được theo dõi qua các khung hình liên tiếp"""
    _next_id = 1

    def __init__(self, bbox, name="Unknown", confidence=0.0, embedding=None):
        self.track_id = FaceTrack._next_id
        FaceTrack._next_id += 1

        self.bbox = np.array(bbox, dtype=np.float32)
        self.name = name
        self.confidence = float(confidence)
        self.embedding = embedding

        self.hits = 1
        self.age = 1
        self.time_since_update = 0
        self.frames_since_recognition = 0

    def update(self, new_bbox, name=None, confidence=None, embedding=None, smooth_factor=0.65):
        """Cập nhật tọa độ và danh tính với EMA smoothing để chuyển động mượt"""
        self.time_since_update = 0
        self.hits += 1
        self.age += 1
        self.frames_since_recognition += 1

        # Exponential Moving Average làm mượt bounding box
        self.bbox = self.bbox * (1.0 - smooth_factor) + np.array(new_bbox, dtype=np.float32) * smooth_factor

        # Cập nhật nhận diện nếu có kết quả nhận diện mới
        if name is not None and name != "Unknown":
            self.name = name
            if confidence is not None:
                self.confidence = float(confidence)
            if embedding is not None:
                self.embedding = embedding
            self.frames_since_recognition = 0
        elif self.name == "Unknown" and name is not None:
            self.name = name
            if confidence is not None:
                self.confidence = float(confidence)

    def mark_missed(self):
        """Đánh dấu khung hình hiện tại không phát hiện thấy khuôn mặt này"""
        self.age += 1
        self.time_since_update += 1
        self.frames_since_recognition += 1

    def should_recognize(self):
        """Xác định xem có cần chạy ArcFace trích xuất lại embedding hay không"""
        if self.name == "Unknown":
            return True
        return self.frames_since_recognition >= RECOGNIZE_INTERVAL

    def to_dict(self):
        return {
            "bbox": self.bbox.astype(int).tolist(),
            "name": self.name,
            "confidence": self.confidence,
            "track_id": self.track_id
        }


class FaceTracker:
    """
    Bộ theo dõi và ổn định khuôn mặt thời gian thực:
    - Khớp (Matching) các phát hiện AI mới với danh sách track hiện có qua IoU.
    - Giữ track sống tối đa TRACKER_MAX_AGE khung hình khi học sinh cúi đầu hoặc bị che khuất.
    - Làm mượt vị trí bounding box, triệt tiêu hoàn toàn hiện tượng rung giật nhấp nháy.
    """
    def __init__(self, max_age=TRACKER_MAX_AGE, min_hits=TRACKER_MIN_HITS, iou_thresh=TRACKER_IOU_THRESH):
        self.max_age = max_age
        self.min_hits = min_hits
        self.iou_thresh = iou_thresh
        self.tracks = []

    def update(self, detections):
        """
        detections: danh sách dict [{"bbox": [x1, y1, x2, y2], "name": ..., "confidence": ..., "embedding": ...}]
        Trả về: danh sách các khuôn mặt đang theo dõi hợp lệ
        """
        unmatched_dets = list(range(len(detections)))
        unmatched_tracks = list(range(len(self.tracks)))

        matched_pairs = []

        if len(self.tracks) > 0 and len(detections) > 0:
            # Tính ma trận IoU
            iou_matrix = np.zeros((len(self.tracks), len(detections)), dtype=np.float32)
            for t_idx, track in enumerate(self.tracks):
                for d_idx, det in enumerate(detections):
                    iou_matrix[t_idx, d_idx] = compute_iou(track.bbox, det["bbox"])

            # Khớp theo thứ tự IoU giảm dần (Greedy matching)
            while True:
                if iou_matrix.size == 0:
                    break
                max_iou = np.max(iou_matrix)
                if max_iou < self.iou_thresh:
                    break
                t_idx, d_idx = np.unravel_index(np.argmax(iou_matrix), iou_matrix.shape)
                matched_pairs.append((t_idx, d_idx))

                # Loại bỏ hàng và cột đã khớp
                iou_matrix[t_idx, :] = -1.0
                iou_matrix[:, d_idx] = -1.0

            matched_track_indices = set(t for t, _ in matched_pairs)
            matched_det_indices = set(d for _, d in matched_pairs)

            unmatched_tracks = [i for i in range(len(self.tracks)) if i not in matched_track_indices]
            unmatched_dets = [i for i in range(len(detections)) if i not in matched_det_indices]

        # 1. Cập nhật các track đã khớp
        for t_idx, d_idx in matched_pairs:
            det = detections[d_idx]
            self.tracks[t_idx].update(
                new_bbox=det["bbox"],
                name=det.get("name"),
                confidence=det.get("confidence"),
                embedding=det.get("embedding")
            )

        # 2. Đánh dấu các track bị mất dấu trong frame này
        for t_idx in unmatched_tracks:
            self.tracks[t_idx].mark_missed()

        # 3. Tạo track mới cho các phát hiện chưa khớp
        for d_idx in unmatched_dets:
            det = detections[d_idx]
            new_track = FaceTrack(
                bbox=det["bbox"],
                name=det.get("name", "Unknown"),
                confidence=det.get("confidence", 0.0),
                embedding=det.get("embedding")
            )
            self.tracks.append(new_track)

        # 4. Xóa các track đã hết hạn
        self.tracks = [t for t in self.tracks if t.time_since_update <= self.max_age]

        # 5. Xuất kết quả các track hợp lệ (đã xuất hiện đủ số lần min_hits hoặc vừa cập nhật)
        active_results = []
        for track in self.tracks:
            if track.hits >= self.min_hits or track.time_since_update == 0:
                active_results.append(track.to_dict())

        return active_results

    def reset(self):
        """Khởi tạo lại danh sách track khi chuyển đổi nguồn Camera"""
        self.tracks.clear()
