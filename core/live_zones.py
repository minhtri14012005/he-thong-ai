"""User-calibrated normalized rectangles; no invented classroom geometry."""
import json
import os
import threading
from config import DATA_DIR

ZONE_PATH = os.path.join(DATA_DIR, 'live_zones.json')
_lock = threading.Lock()


def load_zones():
    with _lock:
        try:
            with open(ZONE_PATH, encoding='utf-8') as file:
                return validate_zones(json.load(file))
        except (OSError, ValueError, TypeError, KeyError):
            return []


def validate_zones(zones):
    if not isinstance(zones, list) or len(zones) > 10:
        raise ValueError('Tối đa 10 vùng')
    result = []
    for zone in zones:
        name = str(zone['name']).strip()
        x1, y1, x2, y2 = [float(v) for v in zone['rect']]
        if not name or len(name) > 60 or not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
            raise ValueError('Tên vùng và tọa độ phải hợp lệ: 0 ≤ trái < phải ≤ 100%, 0 ≤ trên < dưới ≤ 100%')
        result.append({'name': name, 'rect': [x1, y1, x2, y2]})
    return result


def save_zones(zones):
    zones = validate_zones(zones)
    with _lock:
        temp = ZONE_PATH + '.tmp'
        with open(temp, 'w', encoding='utf-8') as file:
            json.dump(zones, file, ensure_ascii=False, indent=2)
        os.replace(temp, ZONE_PATH)
    return zones


def find_zone(bbox, shape, zones):
    h, w = shape[:2]
    x, y = (bbox[0] + bbox[2]) / (2 * w), (bbox[1] + bbox[3]) / (2 * h)
    for zone in zones:
        x1, y1, x2, y2 = zone['rect']
        if x1 <= x <= x2 and y1 <= y <= y2:
            return zone['name']
    return 'Toàn cảnh'
