from routers.cameras import router as cameras_router
from routers.logs import router as logs_router
from routers.persons import router as persons_router
from routers.stream import router as stream_router
from routers.analysis import router as analysis_router

__all__ = [
    "cameras_router",
    "logs_router",
    "persons_router",
    "stream_router",
    "analysis_router"
]
