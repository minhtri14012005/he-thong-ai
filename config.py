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

# Kích thước khung hình xử lý AI (cho Webcam Live Stream)
DET_SIZE = (640, 640)

# Cấu hình quét tầm xa cho Video Upload (High-Res & Classroom Patch Zoom)
VIDEO_DET_SIZE = (1280, 1280)
ENABLE_PATCH_ZOOM_SCAN = True

# Cấu hình Camera Index mặc định
DEFAULT_WEBCAM_INDEX = 1  # Webcam Laptop (ACER HD User Facing)
DEFAULT_IRIUN_INDEX = 0   # iPhone qua Iriun Webcam