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

# Kích thước khung hình xử lý AI (Tối ưu cho Camera 2K iPhone 13 & Bắt mặt nhỏ tầm xa phòng học)
# Với RTX 4050 6GB VRAM, (1280, 1280) giúp nhận diện cực kỳ sắc nét các khuôn mặt ở xa bàn cuối
DET_SIZE = (1280, 1280)
DET_THRESH = 0.40

# Cấu hình quét tầm xa cho Video Upload (High-Res & Classroom Patch Zoom)
VIDEO_DET_SIZE = (1280, 1280)
ENABLE_PATCH_ZOOM_SCAN = True

# Cấu hình Camera Index mặc định
DEFAULT_WEBCAM_INDEX = 1  # Webcam Laptop (ACER HD User Facing)
DEFAULT_IRIUN_INDEX = 0   # iPhone qua Iriun Webcam

# Thiết lập độ phân giải mong muốn khi mở Camera (Hỗ trợ 2K cho iPhone 13 / Iriun)
IPHONE_CAM_WIDTH = 2560
IPHONE_CAM_HEIGHT = 1440
WEBCAM_WIDTH = 1280
WEBCAM_HEIGHT = 720

# Cấu hình Bộ theo dõi khuôn mặt (Face Tracker & Box Smoother)
TRACKER_MAX_AGE = 15        # Số frame giữ track khi tạm mất dấu (cúi đầu, xoay ngang)
TRACKER_MIN_HITS = 2       # Số frame phát hiện liên tiếp trước khi hiển thị chính thức
TRACKER_IOU_THRESH = 0.30  # Ngưỡng khớp IoU giữa các frame
RECOGNIZE_INTERVAL = 10    # Định kỳ sau 10 frames mới trích xuất lại ArcFace để tối ưu tải GPU

# Cấu hình Tự Động Zoom Kỹ Thuật Số (Smart Auto-Zoom)
DEFAULT_AUTO_ZOOM = True   # Mặc định luôn tự động bật Auto-Zoom (không cần bật/tắt thủ công)

