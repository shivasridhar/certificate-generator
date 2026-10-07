from contextlib import asynccontextmanager
from fastapi import FastAPI

from app import models  # noqa: F401 - Ensure all models are registered with Base metadata
from app.database import Base, engine
from app.routers import jobs


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI.
    Runs startup logic before the app starts accepting requests,
    and cleanup logic when shutting down.
    """
    # Create all database tables defined in SQLAlchemy models if they don't exist
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Bulk Certificate Generator",
    description="A backend service for generating bulk PDF certificates asynchronously.",
    version="1.0.0",
    lifespan=lifespan,
)

# Register routers
app.include_router(jobs.router)


@app.get("/health", tags=["Health"])
def health_check():
    """
    Health check endpoint to verify that the service is running and accessible.
    """
    return {"status": "ok"}
