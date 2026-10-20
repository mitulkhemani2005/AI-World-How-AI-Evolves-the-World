from contextlib import asynccontextmanager
import asyncio
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.simulation.engine import engine

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Preserve the user's run choice and warm the shared Qwen model on GPU."""
    warmup = asyncio.create_task(engine._ollama.warm_model())
    if engine.state.running:
        await engine.start()
    yield
    warmup.cancel()
    await asyncio.gather(warmup, return_exceptions=True)
    await engine.shutdown()

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
