"""FastAPI endpoints used by the spectator page and local developers."""

from fastapi import APIRouter, HTTPException

from app.agent_brain.ollama_client import OllamaClient
from app.domain import ModelChange, SpectatorEventRequest, WorldState
from app.settings import settings
from app.simulation.engine import engine

router = APIRouter(prefix="/api")


@router.get("/health")
async def health() -> dict[str, object]:
    """Report API, Ollama, and configured-model readiness separately."""
    ollama = OllamaClient()
    models = await ollama.installed_models()
    default_model = settings.ollama_model
    model_ready = models is not None and default_model in models
    return {
        "status": "ok",
        "ollama_available": models is not None,
        "default_model": default_model,
        "model_ready": model_ready,
        "installed_models": models or [],
    }


@router.get("/models")
async def available_models() -> dict[str, object]:
    """Return installed local models so the spectator can switch brains."""
    models = await OllamaClient().installed_models()
    return {"available": models is not None, "models": models or []}


@router.get("/world", response_model=WorldState)
async def get_world() -> WorldState:
    return await engine.snapshot()


@router.post("/world/tick", response_model=WorldState)
async def advance_world() -> WorldState:
    return await engine.tick()


@router.post("/world/run", response_model=WorldState)
async def run_world(interval_seconds: float = 3.0) -> WorldState:
    return await engine.start(interval_seconds)


@router.post("/world/pause", response_model=WorldState)
async def pause_world() -> WorldState:
    return await engine.pause()


@router.post("/world/reset", response_model=WorldState)
async def reset_world(seed: int = 7) -> WorldState:
    return await engine.reset(seed)


@router.patch("/agents/{agent_id}/model")
async def change_agent_model(agent_id: str, request: ModelChange) -> dict[str, object]:
    try:
        agent = await engine.change_model(agent_id, request.model)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"agent_id": agent.id, "model": agent.model}


@router.post("/events", response_model=WorldState)
async def trigger_event(request: SpectatorEventRequest) -> WorldState:
    try:
        return await engine.inject_event(request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
