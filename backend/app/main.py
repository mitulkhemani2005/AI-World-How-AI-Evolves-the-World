from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.simulation.engine import engine

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Stop the tick loop cleanly while leaving the last world snapshot saved."""
    yield
    await engine.pause()

app = FastAPI(
    title="AI World API",
    description="Backend for an autonomous generational world simulation.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    # Configure one or more independently hosted frontend origins in deployment.
    allow_origins=[origin.strip() for origin in os.getenv(
        "FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
