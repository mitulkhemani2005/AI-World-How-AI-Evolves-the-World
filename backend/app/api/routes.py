"""FastAPI endpoints used by the spectator page and local developers."""

from fastapi import APIRouter, HTTPException

from app.agent_brain.ollama_client import OllamaClient
from app.domain import AgentStateChange, ModelChange, SpectatorEventRequest, WorldState
from app.settings import settings
from app.simulation.engine import engine

router = APIRouter(prefix="/api")


@router.get("/health")
async def health() -> dict[str, object]:
    """Report Ollama availability and readiness of both default and active models."""
    ollama = OllamaClient()
    models = await ollama.installed_models()
    default_model = settings.ollama_model
    world = await engine.snapshot()
    current_model = world.global_model
    return {
        "status": "ok",
        "ollama_available": models is not None,
        "default_model": default_model,
        "default_model_ready": models is not None and default_model in models,
        "current_model": current_model,
        "model_ready": models is not None and current_model in models,
        "installed_models": models or [],
    }


@router.get("/models")
async def available_models() -> dict[str, object]:
    """Return installed local models for the shared world brain selector."""
    models = await OllamaClient().installed_models()
    return {"available": models is not None, "models": models or []}


@router.get("/world", response_model=WorldState)
async def get_world() -> WorldState:
    return await engine.snapshot()


@router.post("/world/tick", response_model=WorldState)
async def advance_world() -> WorldState:
    return await engine.tick()


@router.post("/world/run", response_model=WorldState)
async def run_world(interval_seconds: float | None = None) -> WorldState:
    return await engine.start(interval_seconds)


@router.post("/world/pause", response_model=WorldState)
async def pause_world() -> WorldState:
    return await engine.pause()


@router.post("/world/reset", response_model=WorldState)
async def reset_world(seed: int = 7) -> WorldState:
    return await engine.reset(seed)


@router.patch("/world/model", response_model=WorldState)
async def change_world_model(request: ModelChange) -> WorldState:
    """Set the same Ollama model for every current and future agent."""
    try:
        models = await OllamaClient().installed_models()
        if models is not None and request.model not in models:
            raise ValueError(f"Model '{request.model}' is not installed in Ollama")
        return await engine.change_global_model(request.model)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/agents/{agent_id}/state")
async def change_agent_state(agent_id: str, request: AgentStateChange) -> dict[str, object]:
    """Allow deliberate spectator adjustments to a person's biological stats."""
    try:
        agent = await engine.change_agent_state(agent_id, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"agent_id": agent.id, "health": agent.health, "hunger": agent.hunger,
            "thirst": agent.thirst, "energy": agent.energy, "alive": agent.alive}


@router.post("/events", response_model=WorldState)
async def trigger_event(request: SpectatorEventRequest) -> WorldState:
    try:
        return await engine.inject_event(request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
