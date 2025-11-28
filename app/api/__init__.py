from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.dashboard import router as dashboard_router
from app.api.deliveries import router as deliveries_router
from app.api.recipes import router as recipes_router
from app.api.settings import router as settings_router
from app.api.subscriptions import router as subscriptions_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(dashboard_router)
api_router.include_router(subscriptions_router)
api_router.include_router(recipes_router)
api_router.include_router(deliveries_router)
api_router.include_router(settings_router)

__all__ = ["api_router"]
