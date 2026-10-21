"""Canonical data models shared by the world engine, API, and LLM adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, field_validator


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
    WORLD_EXTINCT = "world_extinct"
    POPULATION_LIMIT = "population_limit"
    CARE = "care"
    FOODBORNE_ILLNESS = "foodborne_illness"
    ANIMAL_BIRTH = "animal_birth"
    ANIMAL_DISEASE = "animal_disease"
    MOURNING = "mourning"
    BURIAL = "burial"
    TERRAIN_CARE = "terrain_care"
    ANIMAL_SPAWNED = "animal_spawned"
    CRAFTING = "crafting"
    ITEM_USED = "item_used"
    PREDATOR_ATTACK = "predator_attack"
    EXPLORATION = "exploration"


ActionName = Literal[
    "forage",
    "drink",
    "rest",
    "move",
    "communicate",
    "help",
    "teach",
    "gather",
    "hunt",
    "tame",
    "tend_animal",
    "collect_animal_food",
    "plant",
    "water_crop",
    "harvest",
    "cook",
    "mourn",
    "bury",
    "build",
    "bond",
    "reproduce",
    "name_child",
    "visit",
    "fight",
    "form_group",
    "join_group",
    "create_belief",
    "tend_terrain",
    "craft", "use_item", "drop_item", "repair", "experiment", "board", "sail", "disembark", "defend", "flee", "explore",
]


class AgentAction(BaseModel):
    """A constrained proposal. The simulation still decides whether it succeeds."""

    action: ActionName
    dx: int = Field(default=0, ge=-1, le=1)
    dy: int = Field(default=0, ge=-1, le=1)
    target_agent_id: str | None = None
    target_group_id: str | None = None
    target_animal_id: str | None = None
    target_item_id: str | None = None
    target_structure_id: str | None = None
    item_kind: Literal["spear", "stone_axe", "raft"] | None = None
    destination_x: int | None = Field(default=None, ge=0)
    destination_y: int | None = Field(default=None, ge=0)
    message: str = Field(default="", max_length=240)
    structure_type: str | None = None
    resource_kind: Literal["wood", "stone"] | None = None
    crop_kind: Literal["fruit", "vegetable"] | None = None
    group_type: Literal["community", "family", "gang"] = "community"
    belief_name: str = Field(default="", max_length=80)
    belief_type: Literal["deity", "myth", "virtue", "evil", "taboo"] | None = None
    reason: str = Field(default="", max_length=300)


class ResourceNode(BaseModel):
    """A renewable or finite resource at a map coordinate."""

    kind: Literal["food", "fruit", "vegetable", "meat", "cooked_meat", "eggs", "milk", "water", "wood", "stone"]
    x: int
    y: int
    quantity: int = Field(ge=0)
    capacity: int = Field(ge=0)
    contamination: float = Field(default=0, ge=0, le=100)
    days_old: int = Field(default=0, ge=0)


class PlaceMemory(BaseModel):
    """A private, spatial memory of a useful place an agent has personally learned."""

    kind: Literal["food", "water", "resource", "shelter", "structure"]
    x: int
    y: int
    detail: str = ""
    last_seen_tick: int = 0


class TerrainCell(BaseModel):
    """A fictional globe coordinate with a biome and climate profile."""

    x: int
    y: int
    kind: Literal["ocean", "plains", "grassland", "farmland", "forest", "rainforest", "boreal_forest", "mountain", "desert", "ice", "river", "lake"]
    elevation: float = Field(default=0, ge=-1, le=1)
    moisture: float = Field(default=0.5, ge=0, le=1)
    temperature: float = Field(default=0.5, ge=0, le=1)
    condition: float = Field(default=100, ge=0, le=100)
    fertility: float = Field(default=70, ge=0, le=100)
    pollution: float = Field(default=0, ge=0, le=100)
    last_tended_tick: int = -1


class Animal(BaseModel):
    """An individual rule-driven NPC animal; animals never call the LLM."""

    id: str
    species: str
    animal_type: Literal["wild", "domestic", "pet"] = "wild"
    brain_type: Literal["npc"] = "npc"
    sex: Literal["male", "female"]
    age_days: int = Field(default=0, ge=0)
    x: int
    y: int
    health: float = Field(default=100, ge=0, le=100)
    hunger: float = Field(default=15, ge=0, le=100)
    thirst: float = Field(default=15, ge=0, le=100)
    alive: bool = True
    disease: str | None = None
    owner_agent_id: str | None = None
    temperament: float = Field(default=0.5, ge=0, le=1)
    # Livestock products replenish by day, not once per LLM decision.
    last_product_tick: int = -1
    last_care_tick: int = -1
    death_tick: int | None = None
    last_birth_tick: int = -10000
    last_attack_tick: int = -1


class CropPlot(BaseModel):
    """A planted food crop that grows through simulated days and seasons."""

    id: str
    crop_kind: Literal["fruit", "vegetable"]
    x: int
    y: int
    planted_by: str
    planted_tick: int
    growth_days: int = 0
    moisture: float = Field(default=60, ge=0, le=100)
    condition: float = Field(default=100, ge=0, le=100)


class Agent(BaseModel):
    """An individual body, memory, and model assignment in the world."""

    id: str
    name: str
    sex: Literal["male", "female"]
    name_status: Literal["final", "provisional"] = "final"
    age_days: int = Field(default=20 * 365, ge=0)
    x: int
    y: int
    health: float = Field(default=100, ge=0, le=100)
    hunger: float = Field(default=15, ge=0, le=100)
    thirst: float = Field(default=15, ge=0, le=100)
    energy: float = Field(default=85, ge=0, le=100)
    alive: bool = True
    # A dead body remains in the scene until another agent chooses to bury it.
    buried: bool = False
    death_cause: str | None = None
    death_tick: int | None = None
    death_details: dict[str, object] = Field(default_factory=dict)
    last_injury: dict[str, object] = Field(default_factory=dict)
    disease: str | None = None
    disease_days: int = 0
    immune_to: list[str] = Field(default_factory=list)
    model: str
    traits: dict[str, float] = Field(default_factory=dict)
    memories: list[str] = Field(default_factory=list)
    # Coordinates are private to this person and persist with the world snapshot.
    place_memories: list[PlaceMemory] = Field(default_factory=list)
    knowledge: list[str] = Field(default_factory=list)
    inventory: dict[str, int] = Field(default_factory=dict)
    relationship_scores: dict[str, float] = Field(default_factory=dict)
    bonded_partner_id: str | None = None
    # Legacy snapshots stored this monthly countdown under a day-based property name.
    pregnancy_months_remaining: int | None = Field(
        default=None,
        validation_alias=AliasChoices("pregnancy_months_remaining", "pregnancy_days_remaining"),
    )
    other_parent_id: str | None = None
    # Each parent may suggest a name before birth; these choices persist across restarts.
    unborn_name_suggestions: dict[str, str] = Field(default_factory=dict)
    fear: float = Field(default=0, ge=0, le=100)
    stress: float = Field(default=0, ge=0, le=100)
    loneliness: float = Field(default=0, ge=0, le=100)
    last_social_tick: int = -1
    mourned_ids: list[str] = Field(default_factory=list)
    # A partner may independently answer a proposal on a later turn; consent expires.
    family_offer: AgentAction | None = None
    family_offer_until_tick: int = -1
    last_birth_tick: int = -10000
    parent_ids: list[str] = Field(default_factory=list)
    children_ids: list[str] = Field(default_factory=list)
    last_action: AgentAction | None = None
    last_result: str = ""
    decision_source: Literal["llm", "fallback", "continuation", "dependent", "reflex"] = "dependent"
    visited_cells: list[str] = Field(default_factory=list)
    # A brain-selected resource/care intention continues while the body walks to its target.
    pending_action: AgentAction | None = None
    construction_project: str | None = None
    intention_source: Literal["llm", "fallback", "dependent", "reflex"] = "dependent"
    decisions_made: int = 0
    last_rest_recovery_tick: int = -1
    last_care_tick: int = -1
    crafting_project: str | None = None
    equipped_item_id: str | None = None
    vehicle_id: str | None = None
    has_sailed: bool = False

    @property
    def age_years(self) -> float:
        # The simulation calendar advances in 30-day months and 12-month years.
        return round(self.age_days / 360, 1)


class Structure(BaseModel):
    """A physical place with an owner and condition."""

    id: str
    kind: Literal["lean_to", "hut", "home", "communal_house", "granary", "farm", "workshop", "shrine", "campfire"]
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


class CraftedItem(BaseModel):
    """A physical shared object; creator credit does not restrict who can use it."""

    id: str
    kind: Literal["spear", "stone_axe", "raft"]
    x: int
    y: int
    creator_agent_id: str
    holder_agent_id: str | None = None
    durability: float = Field(default=100, ge=0, le=100)
    created_tick: int
    capacity: int = 1


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
    global_model: str = "qwen2.5:0.5b"
    tick: int = 0
    # A monthly world step advances on elapsed time, independently from agent decisions.
    # Legacy aliases keep existing SQLite snapshots loadable after this calendar rename.
    month_progress_seconds: float = Field(
        default=0, ge=0,
        validation_alias=AliasChoices("month_progress_seconds", "day_progress_seconds"),
    )
    month_length_seconds: float = Field(
        default=60, ge=1, le=3600,
        validation_alias=AliasChoices("month_length_seconds", "day_length_seconds"),
    )
    time_scale: float = Field(default=1, ge=1, le=16)
    base_time_scale: float = Field(default=1, ge=1, le=16)
    auto_accelerate: bool = False
    running_elapsed_seconds: float = 0
    width: int = 12
    height: int = 8
    agents: list[Agent]
    resources: list[ResourceNode]
    terrain: list[TerrainCell] = Field(default_factory=list)
    animals: list[Animal] = Field(default_factory=list)
    crops: list[CropPlot] = Field(default_factory=list)
    structures: list[Structure] = Field(default_factory=list)
    items: list[CraftedItem] = Field(default_factory=list)
    rules_version: int = 1
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


class SpeedChange(BaseModel):
    time_scale: float = Field(default=1, ge=1, le=16)
    auto_accelerate: bool = False


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
