import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Đường dẫn CSDL
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "database.db")

# Đường dẫn thư mục tĩnh chứa ảnh Web (static/uploads)
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOAD_DIR = os.path.join(STATIC_DIR, "uploads")

# Tự động tạo thư mục nếu chưa tồn tại
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Ngưỡng nhận diện (Cosine Similarity Threshold)
SIMILARITY_THRESHOLD = 0.45

# Kích thước khung hình xử lý AI
DET_SIZE = (640, 640)