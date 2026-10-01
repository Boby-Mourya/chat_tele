from fastapi import APIRouter

from northstar_api.routers.help_browse import router as browse_router
from northstar_api.routers.help_interactions import router as interactions_router

router = APIRouter(tags=["help"])
router.include_router(browse_router, prefix="/help")
router.include_router(interactions_router, prefix="/help")
