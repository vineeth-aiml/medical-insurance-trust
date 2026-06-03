from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import settings
from app.db.database import Base, engine

# For production, prefer Alembic migrations. create_all keeps local/demo runs simple.
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.app_name,
    description="Production-structured medical document fraud detection platform.",
    version="1.0.0-production-ready",
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(router)
