import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import api_router
from app.config import settings
from app.ui.routes import router as ui_router

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

app = FastAPI(
    title="Kindledrop",
    description="Self-hosted news delivery to Kindle",
    version="0.1.0",
)

app.include_router(api_router)
app.include_router(ui_router)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
