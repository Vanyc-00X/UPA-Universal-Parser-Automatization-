"""HTTP API UPA."""

from fastapi import APIRouter

from app.api.analyze import router as analyze_router
from app.api.crawl import router as crawl_router
from app.api.system import router as system_router

api_router = APIRouter()
api_router.include_router(system_router)
api_router.include_router(crawl_router)
api_router.include_router(analyze_router)

__all__ = ["api_router"]
