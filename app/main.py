import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import api_router
from app.config import settings
from app.services.calibre import calibre
from app.services.delivery import DeliveryEngine
from app.services.scheduler import SchedulerService
from app.ui.routes import router as ui_router

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

# Global scheduler instance (accessible for graceful shutdown)
scheduler_service: SchedulerService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle: startup and shutdown."""
    global scheduler_service

    # Startup
    logger.info("Starting Kindledrop...")

    # Ensure epub directory exists
    settings.epub_dir.mkdir(parents=True, exist_ok=True)

    # Initialize delivery engine
    delivery_engine = DeliveryEngine(calibre=calibre, epub_dir=settings.epub_dir)

    # Initialize and start scheduler
    scheduler_service = SchedulerService(delivery_engine=delivery_engine)
    await scheduler_service.start()

    logger.info("Kindledrop started successfully")

    yield

    # Shutdown
    logger.info("Shutting down Kindledrop...")

    if scheduler_service:
        await scheduler_service.stop()

    logger.info("Kindledrop shut down")


app = FastAPI(
    title="Kindledrop",
    description="Self-hosted news delivery to Kindle",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(api_router)
app.include_router(ui_router)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
