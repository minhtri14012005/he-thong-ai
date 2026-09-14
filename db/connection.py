import os
import sqlite3
from config import DB_PATH


def get_db():
    """Tạo hoặc lấy kết nối SQLite tới database.db"""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Khởi tạo tất cả các bảng dữ liệu nếu chưa tồn tại"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS persons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS face_embeddings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_id INTEGER,
        embedding TEXT NOT NULL,
        image_path TEXT,
        FOREIGN KEY (person_id) REFERENCES persons (id) ON DELETE CASCADE
    )
    ''')

    try:
        cursor.execute("ALTER TABLE face_embeddings ADD COLUMN image_path TEXT")
    except sqlite3.OperationalError:
        pass

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS detection_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_name TEXT NOT NULL,
        confidence REAL NOT NULL,
        detected_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS video_analysis_jobs (
        id TEXT PRIMARY KEY,
        filename TEXT NOT NULL,
        video_url TEXT NOT NULL,
        status TEXT DEFAULT 'processing',
        progress INTEGER DEFAULT 0,
        total_frames INTEGER DEFAULT 0,
        processed_frames INTEGER DEFAULT 0,
        duration_sec REAL DEFAULT 0,
        created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS video_detections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL,
        person_name TEXT NOT NULL,
        confidence REAL NOT NULL,
        timestamp_sec REAL NOT NULL,
        timestamp_str TEXT NOT NULL,
        snapshot_path TEXT,
        created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (job_id) REFERENCES video_analysis_jobs (id) ON DELETE CASCADE
    )
    ''')

    conn.commit()
    conn.close()
