from db.connection import get_db, init_db
from db.persons_repo import (
    save_person_embedding,
    get_person_embeddings,
    delete_single_embedding,
    load_all_embeddings
)
from db.logs_repo import log_detection
from db.jobs_repo import (
    create_video_job,
    update_job_status,
    add_video_detection,
    get_video_job,
    get_video_detections_since,
    get_job_summary
)

__all__ = [
    "get_db",
    "init_db",
    "save_person_embedding",
    "get_person_embeddings",
    "delete_single_embedding",
    "load_all_embeddings",
    "log_detection",
    "create_video_job",
    "update_job_status",
    "add_video_detection",
    "get_video_job",
    "get_video_detections_since",
    "get_job_summary"
]
