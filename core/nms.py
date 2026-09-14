import numpy as np


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
