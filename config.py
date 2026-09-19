import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Đường dẫn CSDL
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "database.db")

# Đường dẫn thư mục tĩnh chứa ảnh Web (static/uploads)
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOAD_DIR = os.path.join(STATIC_DIR, "uploads")
SNAPSHOT_DIR = os.path.join(STATIC_DIR, "snapshots")
VIDEO_UPLOAD_DIR = os.path.join(STATIC_DIR, "uploaded_videos")

# Tự động tạo thư mục nếu chưa tồn tại
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(SNAPSHOT_DIR, exist_ok=True)
os.makedirs(VIDEO_UPLOAD_DIR, exist_ok=True)

# Ngưỡng nhận diện (Cosine Similarity Threshold)
SIMILARITY_THRESHOLD = 0.45

# Cấu hình Tăng tốc Phần Cứng GPU (NVIDIA RTX 4050)
USE_GPU = True
GPU_DEVICE_ID = 0

# Kích thước khung hình xử lý AI cho Camera thời gian thực (Chuẩn SCRFD 640x640 tối ưu tốc độ và bắt nét mọi cự ly)
DET_SIZE = (640, 640)
DET_THRESH = 0.35

# Cấu hình quét tầm xa cho Video Upload (High-Res & Classroom Patch Zoom)
VIDEO_DET_SIZE = (1280, 1280)
ENABLE_PATCH_ZOOM_SCAN = True

# Cấu hình Camera Index mặc định
DEFAULT_WEBCAM_INDEX = 1  # Webcam Laptop (ACER HD User Facing)
DEFAULT_IRIUN_INDEX = 0   # iPhone qua Iriun Webcam

# Thiết lập độ phân giải thu nhận Camera (1080p mượt mà cho Iriun, 720p cho Webcam)
IPHONE_CAM_WIDTH = 1920
IPHONE_CAM_HEIGHT = 1080
WEBCAM_WIDTH = 1280
WEBCAM_HEIGHT = 720

# Cấu hình Bộ theo dõi khuôn mặt (Face Tracker & Box Smoother)
TRACKER_MAX_AGE = 15        # Số frame giữ track khi tạm mất dấu (cúi đầu, xoay ngang)
TRACKER_MIN_HITS = 2       # Số frame phát hiện liên tiếp trước khi hiển thị chính thức
TRACKER_IOU_THRESH = 0.30  # Ngưỡng khớp IoU giữa các frame
RECOGNIZE_INTERVAL = 10    # Định kỳ sau 10 frames mới trích xuất lại ArcFace để tối ưu tải GPU

# Cấu hình Tự Động Zoom Kỹ Thuật Số (Smart Auto-Zoom)
DEFAULT_AUTO_ZOOM = False  # Giữ toàn cảnh; zoom chỉ phục vụ hiển thị.

# Tham số khởi đầu cho live, cần hiệu chỉnh bằng dữ liệu tại lớp.
LIVE_DET_SIZE = (1280, 1280)
LIVE_MATCH_THRESHOLD = 0.50
LIVE_MATCH_MARGIN = 0.08
LIVE_MIN_FACE_PIXELS = 40
LIVE_MIN_SHARPNESS = 35.0
LIVE_CONFIRM_HITS = 3
LIVE_CONFIRM_WINDOW = 5
LIVE_CONFIRM_SECONDS = 2.5
LIVE_TRACK_TTL = 1.5
LIVE_CAMERA_STALE_SECONDS = 2.0
LIVE_REENTRY_SECONDS = 15.0
LIVE_TARGET_AI_FPS = 10.0

# Video được phân tích theo thời gian trong file, không theo tốc độ xử lý của máy.
VIDEO_SCAN_PROFILES = {
    'fast': {'sample_fps': 3.0, 'burst_fps': 8.0, 'all_tiles': False, 'tile_size': 640},
    'detailed': {'sample_fps': 4.0, 'burst_fps': 8.0, 'all_tiles': True, 'tile_size': 960},
}
# Tương thích các yêu cầu API cũ; giao diện dùng tên chung "Quét kỹ".
VIDEO_SCAN_PROFILES['classroom'] = VIDEO_SCAN_PROFILES['detailed']
VIDEO_REENTRY_SECONDS = 5.0
VIDEO_BURST_HOLD_SECONDS = 1.0


