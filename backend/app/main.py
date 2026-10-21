from contextlib import asynccontextmanager
import asyncio
import os
import shutil
import subprocess
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.agent_brain.ollama_client import OllamaClient
from app.simulation.engine import engine


async def _ensure_local_ollama() -> None:
    """Start the local Ollama service when installed but not already listening."""
    ollama = OllamaClient()
    if await ollama.is_available():
        return

    # Never try to start a local process for a separately hosted Ollama endpoint.
    hostname = (urlparse(ollama.base_url).hostname or "").lower()
    if hostname not in {"localhost", "127.0.0.1", "::1"}:
        return
    executable = shutil.which("ollama")
    if not executable:
        return

    # Ollama owns GPU discovery and model placement; the API only starts its service.
    # On Windows, keep the helper console hidden behind the app window.
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.Popen([executable, "serve"], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=creation_flags)
    except OSError:
        # Another Ollama process may have won the startup race; readiness decides.
        pass
    for _ in range(20):
        if await ollama.is_available():
            return
        await asyncio.sleep(0.25)

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Preserve the user's run choice and warm the shared Qwen model on GPU."""
    await _ensure_local_ollama()
    warmup = asyncio.create_task(engine._ollama.warm_model())
    if engine.state.running:
        await engine.start()
    yield
    warmup.cancel()
    await asyncio.gather(warmup, return_exceptions=True)
    await engine.shutdown()

app = FastAPI(
    title="Origin: AI World API",
    description="Backend for the Origin: AI World generational life simulation.",
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
