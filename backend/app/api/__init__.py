"""HTTP API UPA."""

from fastapi import APIRouter

from app.api.analyze import router as analyze_router
from app.api.crawl import router as crawl_router
from app.api.editor import router as editor_router
from app.api.export import router as export_router
from app.api.heal import router as heal_router
from app.api.run import router as run_router
from app.api.system import router as system_router
from app.api.workflow import router as workflow_router

api_router = APIRouter()
api_router.include_router(system_router)
api_router.include_router(crawl_router)
api_router.include_router(analyze_router)
api_router.include_router(editor_router)
api_router.include_router(run_router)
api_router.include_router(export_router)
api_router.include_router(heal_router)
api_router.include_router(workflow_router)

__all__ = ["api_router"]
