import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Đường dẫn dữ liệu
DATA_DIR = os.path.join(BASE_DIR, "data")
FACES_DIR = os.path.join(DATA_DIR, "faces")
DB_PATH = os.path.join(DATA_DIR, "database.db")

os.makedirs(FACES_DIR, exist_ok=True)

# Ngưỡng nhận diện (Cosine Similarity Threshold)
# > 0.45: Độ chính xác cao, hạn chế tối đa nhận diện nhầm (False Positive)
SIMILARITY_THRESHOLD = 0.45

# Kích thước khung hình xử lý AI (giúp tăng tốc độ và độ chính xác detection)
DET_SIZE = (640, 640)