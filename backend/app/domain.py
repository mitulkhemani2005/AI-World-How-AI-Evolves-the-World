from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class EventSource(str, Enum):
    NATURAL = "natural"
    AGENT_ACTION = "agent_action"
    SPECTATOR = "spectator"
    SYSTEM = "system"


class EventKind(str, Enum):
    WORLD_STARTED = "world_started"
    ACTION = "action"
    NEED_CHANGED = "need_changed"
    DISEASE_STARTED = "disease_started"
    DISEASE_RECOVERED = "disease_recovered"
    INJURY = "injury"
    DEATH = "death"
    MODEL_CHANGED = "model_changed"
    SPECTATOR_EVENT = "spectator_event"
    NATURAL_EVENT = "natural_event"
    AGENT_SPOKE = "agent_spoke"
    FALLBACK_DECISION = "fallback_decision"


class AgentAction(BaseModel):
    action: Literal["forage", "drink", "rest", "move", "communicate", "help"]
    dx: int = Field(default=0, ge=-1, le=1)
    dy: int = Field(default=0, ge=-1, le=1)
    target_agent_id: str | None = None
    message: str = Field(default="", max_length=240)
    reason: str = Field(default="", max_length=300)


class ResourceNode(BaseModel):
    kind: Literal["food", "water", "shelter"]
    x: int
    y: int
    quantity: int = Field(ge=0)
    capacity: int = Field(ge=0)


class Agent(BaseModel):
    id: str
    name: str
    sex: Literal["male", "female"]
    age_days: int = Field(default=20 * 365, ge=0)
    x: int
    y: int
    health: float = Field(default=100, ge=0, le=100)
    hunger: float = Field(default=15, ge=0, le=100)
    thirst: float = Field(default=15, ge=0, le=100)
    energy: float = Field(default=85, ge=0, le=100)
    alive: bool = True
    disease: str | None = None
    disease_days: int = 0
    immune_to: list[str] = Field(default_factory=list)
    model: str
    memories: list[str] = Field(default_factory=list)
    last_action: AgentAction | None = None

    @property
    def age_years(self) -> float:
        return round(self.age_days / 365, 1)


class WorldEvent(BaseModel):
    id: str
    tick: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: EventSource
    kind: EventKind
    message: str
    agent_ids: list[str] = Field(default_factory=list)
    details: dict[str, object] = Field(default_factory=dict)


class WorldState(BaseModel):
    id: str
    seed: int
    tick: int = 0
    width: int = 12
    height: int = 8
    agents: list[Agent]
    resources: list[ResourceNode]
    events: list[WorldEvent] = Field(default_factory=list)
    running: bool = False


class ModelChange(BaseModel):
    model: str = Field(min_length=1, max_length=120)


class SpectatorEventRequest(BaseModel):
    kind: Literal["wildfire", "storm", "injury", "disease_outbreak"]
    target_agent_id: str | None = None
    x: int | None = Field(default=None, ge=0)
    y: int | None = Field(default=None, ge=0)


class WorldSummary(BaseModel):
    id: str
    tick: int
    running: bool
    population: int
    living_population: int
    agents: list[Agent]
    resources: list[ResourceNode]
    recent_events: list[WorldEvent]
