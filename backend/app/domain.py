"""Canonical data models shared by the world engine, API, and LLM adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class EventSource(str, Enum):
    NATURAL = "natural"
    AGENT_ACTION = "agent_action"
    SPECTATOR = "spectator"
    SYSTEM = "system"


class EventKind(str, Enum):
    WORLD_STARTED = "world_started"
    ACTION = "action"
    BIRTH = "birth"
    DEATH = "death"
    DISEASE_STARTED = "disease_started"
    DISEASE_RECOVERED = "disease_recovered"
    INJURY = "injury"
    MODEL_CHANGED = "model_changed"
    SPECTATOR_EVENT = "spectator_event"
    NATURAL_EVENT = "natural_event"
    AGENT_SPOKE = "agent_spoke"
    RELATIONSHIP = "relationship"
    AFFAIR = "affair"
    TEACHING = "teaching"
    DISCOVERY = "discovery"
    CONSTRUCTION = "construction"
    GROUP_FORMED = "group_formed"
    GROUP_JOINED = "group_joined"
    BELIEF_CREATED = "belief_created"
    FIGHT = "fight"
    FALLBACK_DECISION = "fallback_decision"
    SIMULATION_ERROR = "simulation_error"


ActionName = Literal[
    "forage",
    "drink",
    "rest",
    "move",
    "communicate",
    "help",
    "teach",
    "gather",
    "build",
    "bond",
    "reproduce",
    "fight",
    "form_group",
    "join_group",
    "create_belief",
]


class AgentAction(BaseModel):
    """A constrained proposal. The simulation still decides whether it succeeds."""

    action: ActionName
    dx: int = Field(default=0, ge=-1, le=1)
    dy: int = Field(default=0, ge=-1, le=1)
    target_agent_id: str | None = None
    target_group_id: str | None = None
    message: str = Field(default="", max_length=240)
    structure_type: str | None = None
    resource_kind: Literal["wood", "stone"] | None = None
    group_type: Literal["community", "family", "gang"] = "community"
    belief_name: str = Field(default="", max_length=80)
    belief_type: Literal["deity", "myth", "virtue", "evil", "taboo"] | None = None
    reason: str = Field(default="", max_length=300)


class ResourceNode(BaseModel):
    """A renewable or finite resource at a map coordinate."""

    kind: Literal["food", "water", "wood", "stone"]
    x: int
    y: int
    quantity: int = Field(ge=0)
    capacity: int = Field(ge=0)


class Agent(BaseModel):
    """An individual body, memory, and model assignment in the world."""

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
    traits: dict[str, float] = Field(default_factory=dict)
    memories: list[str] = Field(default_factory=list)
    knowledge: list[str] = Field(default_factory=list)
    inventory: dict[str, int] = Field(default_factory=dict)
    relationship_scores: dict[str, float] = Field(default_factory=dict)
    bonded_partner_id: str | None = None
    pregnancy_days_remaining: int | None = None
    other_parent_id: str | None = None
    parent_ids: list[str] = Field(default_factory=list)
    children_ids: list[str] = Field(default_factory=list)
    last_action: AgentAction | None = None

    @property
    def age_years(self) -> float:
        return round(self.age_days / 365, 1)


class Structure(BaseModel):
    """A physical place with an owner and condition."""

    id: str
    kind: Literal["lean_to", "hut", "home", "communal_house", "granary", "farm", "workshop", "shrine"]
    x: int
    y: int
    owner_agent_id: str | None = None
    group_id: str | None = None
    condition: float = Field(default=100, ge=0, le=100)
    built_at_tick: int


class SocialGroup(BaseModel):
    """A social group; its kind may emerge from how members behave."""

    id: str
    name: str
    kind: Literal["community", "family", "gang"] = "community"
    leader_agent_id: str
    member_ids: list[str] = Field(default_factory=list)
    formed_at_tick: int


class CulturalBelief(BaseModel):
    """A story or value invented by agents and potentially shared over time."""

    id: str
    name: str
    kind: Literal["deity", "myth", "virtue", "evil", "taboo"]
    description: str
    creator_agent_id: str
    believer_ids: list[str] = Field(default_factory=list)
    created_at_tick: int


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
    # One world-wide brain model is used by every independent person.
    global_model: str = "gemma4:e2b"
    tick: int = 0
    width: int = 12
    height: int = 8
    agents: list[Agent]
    resources: list[ResourceNode]
    structures: list[Structure] = Field(default_factory=list)
    groups: list[SocialGroup] = Field(default_factory=list)
    beliefs: list[CulturalBelief] = Field(default_factory=list)
    tech_level: int = 0
    weather: str = "clear"
    season: str = "spring"
    events: list[WorldEvent] = Field(default_factory=list)
    running: bool = False
    processing: bool = False


class ModelChange(BaseModel):
    model: str = Field(min_length=1, max_length=120)

    @field_validator("model")
    @classmethod
    def trim_model_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Model name cannot be empty")
        return value


class AgentStateChange(BaseModel):
    """A spectator may tune visible needs, while the engine owns all consequences."""

    health: float | None = Field(default=None, ge=0, le=100)
    hunger: float | None = Field(default=None, ge=0, le=100)
    thirst: float | None = Field(default=None, ge=0, le=100)
    energy: float | None = Field(default=None, ge=0, le=100)


class SpectatorEventRequest(BaseModel):
    kind: Literal["wildfire", "storm", "flood", "drought", "injury", "disease_outbreak"]
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
    structures: list[Structure]
    groups: list[SocialGroup]
    beliefs: list[CulturalBelief]
    tech_level: int
    recent_events: list[WorldEvent]
