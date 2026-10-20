"""Authoritative world rules for the first generational simulation prototype."""

from __future__ import annotations

import asyncio
import math
import random
from uuid import uuid4

from app.agent_brain.ollama_client import OllamaClient, OllamaError
from app.domain import (
    Agent,
    AgentAction,
    AgentStateChange,
    CulturalBelief,
    EventKind,
    EventSource,
    ResourceNode,
    SocialGroup,
    SpectatorEventRequest,
    Structure,
    WorldEvent,
    WorldState,
)
from app.settings import settings
from app.storage.sqlite_store import SQLiteWorldStore


ADULT_AGE_DAYS = 16 * 365
PREGNANCY_DAYS = 270
DISEASES = ("fever", "respiratory illness", "wound infection")
TRAIT_NAMES = ("curiosity", "cooperation", "aggression", "resilience", "sociability")

# Building costs and minimum technology levels create gradual, resource-bound growth.
BUILDING_RULES: dict[str, tuple[int, dict[str, int]]] = {
    "lean_to": (0, {"wood": 2}),
    "hut": (1, {"wood": 4}),
    "home": (1, {"wood": 5, "stone": 1}),
    "communal_house": (2, {"wood": 8, "stone": 3}),
    "granary": (2, {"wood": 5, "stone": 1}),
    "farm": (2, {"wood": 6}),
    "shrine": (2, {"wood": 4, "stone": 2}),
    "workshop": (3, {"wood": 8, "stone": 4}),
}


class SimulationEngine:
    """Runs a single persisted world; model output never mutates state directly."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._tick_lock = asyncio.Lock()
        self._random = random.Random(7)
        self._ollama = OllamaClient()
        self._store = SQLiteWorldStore(settings.database_path)
        self._runner_task: asyncio.Task[None] | None = None
        self._tick_interval_seconds = 3.0
        self.state = self._store.load() or self._new_world(seed=7)
        # Older snapshots may contain per-person model choices; migrate them to one shared brain.
        if not self.state.global_model:
            self.state.global_model = settings.ollama_model
        for person in self.state.agents:
            person.model = self.state.global_model
        # A server restart restores the world but never silently resumes a background loop.
        self.state.running = False
        self.state.processing = False
        self._save()

    def _new_world(self, seed: int) -> WorldState:
        self._random.seed(seed)
        world = WorldState(
            id=str(uuid4()),
            seed=seed,
            global_model=settings.ollama_model,
            agents=[
                Agent(
                    id="agent-1",
                    name="Aru",
                    sex="male",
                    x=3,
                    y=4,
                    model=settings.ollama_model,
                    traits={"curiosity": 0.7, "cooperation": 0.6, "aggression": 0.3, "resilience": 0.6, "sociability": 0.6},
                ),
                Agent(
                    id="agent-2",
                    name="Nima",
                    sex="female",
                    x=4,
                    y=4,
                    model=settings.ollama_model,
                    traits={"curiosity": 0.6, "cooperation": 0.7, "aggression": 0.2, "resilience": 0.7, "sociability": 0.7},
                ),
            ],
            resources=[
                ResourceNode(kind="food", x=2, y=5, quantity=20, capacity=30),
                ResourceNode(kind="food", x=10, y=4, quantity=20, capacity=30),
                ResourceNode(kind="water", x=7, y=3, quantity=35, capacity=45),
                ResourceNode(kind="wood", x=5, y=7, quantity=24, capacity=30),
                ResourceNode(kind="wood", x=12, y=6, quantity=24, capacity=30),
                ResourceNode(kind="stone", x=12, y=2, quantity=15, capacity=20),
            ],
        )
        # The starting pair know one another, but they still choose whether to bond or reproduce.
        world.agents[0].relationship_scores[world.agents[1].id] = 20
        world.agents[1].relationship_scores[world.agents[0].id] = 20
        world.agents[0].memories.append("You have lived near Nima for a long time.")
        world.agents[1].memories.append("You have lived near Aru for a long time.")
        self._record(world, EventSource.SYSTEM, EventKind.WORLD_STARTED, "A new world began with two independent agents.")
        return world

    async def reset(self, seed: int = 7) -> WorldState:
        async with self._tick_lock:
            async with self._lock:
                self.state.running = False
                self.state = self._new_world(seed)
                self._save()
                return self.state.model_copy(deep=True)

    async def snapshot(self) -> WorldState:
        async with self._lock:
            return self.state.model_copy(deep=True)

    async def start(self, interval_seconds: float = 3.0) -> WorldState:
        async with self._lock:
            self._tick_interval_seconds = min(max(interval_seconds, 0.5), 60.0)
            self.state.running = True
            if self._runner_task is None or self._runner_task.done():
                self._runner_task = asyncio.create_task(self._run_loop())
            self._save()
            return self.state.model_copy(deep=True)

    async def pause(self) -> WorldState:
        async with self._lock:
            self.state.running = False
            self._save()
            return self.state.model_copy(deep=True)

    async def _run_loop(self) -> None:
        while True:
            await asyncio.sleep(self._tick_interval_seconds)
            async with self._lock:
                if not self.state.running:
                    self._runner_task = None
                    return
            try:
                await self.tick()
            except Exception as exc:
                # Keep a failed background tick visible and stop instead of spinning on bad state.
                async with self._lock:
                    self.state.running = False
                    self.state.processing = False
                    self._record(self.state, EventSource.SYSTEM, EventKind.SIMULATION_ERROR, "The simulation paused after an internal error.", details={"error": str(exc)[:300]})
                    self._save()
                    self._runner_task = None
                return

    async def tick(self) -> WorldState:
        # Keep reads and spectator inspection responsive while slow model calls are in flight.
        async with self._tick_lock:
            async with self._lock:
                world = self.state
                world.tick += 1
                world.processing = True
                self._advance_environment(world)
                self._regenerate_resources(world)
                self._natural_events(world)
                world_id = world.id
                observation_state = world.model_copy(deep=True)
                self._save()

            # Gather proposals first so consent-based actions can be resolved mutually.
            proposals: dict[str, AgentAction] = {}
            fallback_errors: dict[str, str] = {}
            # Infants have needs and depend on caregivers, but do not yet make language-model choices.
            decision_agents = [
                person for person in observation_state.agents
                if person.alive and person.age_days >= 3 * 365
            ]
            # A small concurrency limit keeps the shared local model responsive as families grow.
            decision_slots = asyncio.Semaphore(2)

            async def decide_one(person: Agent) -> tuple[str, AgentAction | OllamaError]:
                async with decision_slots:
                    try:
                        return person.id, await self._ollama.decide(person, observation_state)
                    except OllamaError as error:
                        return person.id, error

            results = await asyncio.gather(*(decide_one(person) for person in decision_agents))
            for agent_id, result in results:
                if isinstance(result, OllamaError):
                    person = next(person for person in decision_agents if person.id == agent_id)
                    proposals[agent_id] = self._fallback_action(person, observation_state)
                    fallback_errors[agent_id] = str(result)[:240]
                else:
                    proposals[agent_id] = result

            async with self._lock:
                world = self.state
                # A reset cannot race a decision round because reset shares the tick lock.
                if world.id != world_id:
                    return world.model_copy(deep=True)
                for agent_id, error in fallback_errors.items():
                    action = proposals[agent_id]
                    agent = next((person for person in world.agents if person.id == agent_id), None)
                    if agent:
                        self._record(world, EventSource.SYSTEM, EventKind.FALLBACK_DECISION, f"{agent.name}'s model could not decide; a basic survival policy chose instead.", [agent.id], {"error": error, "fallback_action": action.action})

                handled: set[str] = set()
                for agent_id, action in proposals.items():
                    if agent_id in handled:
                        continue
                    agent = next((person for person in world.agents if person.id == agent_id and person.alive), None)
                    if not agent:
                        continue
                    if action.action in {"bond", "reproduce"}:
                        partner_id = action.target_agent_id
                        partner_action = proposals.get(partner_id or "")
                        partner = next((person for person in world.agents if person.id == partner_id and person.alive), None)
                        mutual = partner is not None and partner_action is not None and partner_action.action == action.action and partner_action.target_agent_id == agent.id
                        if mutual:
                            if action.action == "bond":
                                self._resolve_bond(world, agent, partner)
                            else:
                                self._resolve_reproduction(world, agent, partner)
                            handled.add(partner.id)
                        else:
                            self._record_action(world, agent, action, "The other person did not independently agree.")
                    else:
                        # Translate a resource-seeking choice into a path step when the resource is not underfoot.
                        resolved_action = self._prepare_resource_action(world, agent, action)
                        result = self._apply_action(world, agent, resolved_action)
                        self._record_action(
                            world,
                            agent,
                            resolved_action,
                            result,
                            proposed_action=action if resolved_action.action != action.action else None,
                        )
                    handled.add(agent.id)

                for agent in world.agents:
                    if agent.alive:
                        self._advance_biology(world, agent)

                world.events = world.events[-settings.max_saved_events :]
                world.processing = False
                self._save()
                return world.model_copy(deep=True)

    async def change_global_model(self, model: str) -> WorldState:
        async with self._lock:
            model = model.strip()
            if not model:
                raise ValueError("Model name cannot be empty")
            old_model = self.state.global_model
            self.state.global_model = model
            for agent in self.state.agents:
                # Memory and personality remain private even though the model family is shared.
                agent.model = model
            self._record(
                self.state,
                EventSource.SPECTATOR,
                EventKind.MODEL_CHANGED,
                f"The spectator changed the shared brain model to {model}.",
                [agent.id for agent in self.state.agents],
                {"old_model": old_model, "new_model": model},
            )
            self._save()
            return self.state.model_copy(deep=True)

    async def change_agent_state(self, agent_id: str, update: AgentStateChange) -> Agent:
        """Apply a visible spectator adjustment and immediately resolve its consequences."""
        async with self._lock:
            agent = self._get_agent(agent_id)
            changed = {key: value for key, value in update.model_dump(exclude_none=True).items()}
            if not changed:
                raise ValueError("Choose at least one stat to change")
            for key, value in changed.items():
                setattr(agent, key, value)
            self._check_death(self.state, agent, "a spectator adjustment", EventSource.SPECTATOR)
            self._record(self.state, EventSource.SPECTATOR, EventKind.SPECTATOR_EVENT,
                         f"The spectator adjusted {agent.name}'s condition.", [agent.id], {"changes": changed})
            self._save()
            return agent.model_copy(deep=True)

    async def inject_event(self, request: SpectatorEventRequest) -> WorldState:
        # Spectator events stay responsive during slow local-model inference.
        async with self._lock:
            world = self.state
            agent = self._get_agent(request.target_agent_id) if request.target_agent_id else None
            x = request.x if request.x is not None else (agent.x if agent else world.width // 2)
            y = request.y if request.y is not None else (agent.y if agent else world.height // 2)
            x = min(max(x, 0), world.width - 1)
            y = min(max(y, 0), world.height - 1)
            affected: list[str] = []

            if request.kind == "injury":
                # A dropped mishap only reaches its selected target or nearest nearby people.
                targets = [agent] if agent else [
                    person for person in world.agents if person.alive
                    and self._distance_to(person.x, person.y, x, y) <= 1.5
                ]
                for target in targets:
                    if target and target.alive:
                        target.health = max(0, target.health - 25)
                        affected.append(target.id)
                        self._check_death(world, target, "an injury", EventSource.SPECTATOR)
            elif request.kind == "disease_outbreak":
                targets = [a for a in world.agents if a.alive and self._distance_to(a.x, a.y, x, y) <= 4]
                for target in targets:
                    already_ill = target.disease is not None
                    self._infect(world, target, self._random.choice(DISEASES), EventSource.SPECTATOR)
                    if not already_ill and target.disease:
                        affected.append(target.id)
            else:
                damage = {"wildfire": 34, "storm": 16, "flood": 23, "drought": 9}[request.kind]
                radius = {"wildfire": 2.8, "storm": 4.2, "flood": 2.6, "drought": 4.8}[request.kind]
                affected = self._hazard_damage(world, x, y, radius, damage, request.kind, EventSource.SPECTATOR)
                self._apply_hazard_to_resources(world, x, y, radius, request.kind)

            self._record(
                world,
                EventSource.SPECTATOR,
                EventKind.SPECTATOR_EVENT,
                f"The spectator triggered a {request.kind.replace('_', ' ')}.",
                affected,
                {"event": request.kind, "x": x, "y": y, "affected": len(affected)},
            )
            self._save()
            return world.model_copy(deep=True)

    def _apply_action(self, world: WorldState, agent: Agent, action: AgentAction) -> str:
        """Resolve one non-consensual action against authoritative world state."""
        if self._is_child(agent) and action.action in {"build", "fight", "form_group", "reproduce", "bond"}:
            return "This person is too young for that action."

        if action.action == "move":
            # Resolve diagonal proposals into one cardinal step so movement has consistent speed.
            dx, dy = action.dx, action.dy
            if dx and dy:
                dy = 0
            agent.x = min(max(agent.x + dx, 0), world.width - 1)
            agent.y = min(max(agent.y + dy, 0), world.height - 1)
            return f"Moved to ({agent.x}, {agent.y})."
        if action.action == "forage":
            food = self._resource_at(world, "food", agent.x, agent.y)
            if not food or food.quantity <= 0:
                return "Looked for food here but found none."
            food.quantity -= 1
            agent.hunger = max(0, agent.hunger - 42)
            self._remember(agent, "Found food here and ate it.")
            self._learn(agent, "foraging")
            return "Found food and ate."
        if action.action == "drink":
            water = self._resource_at(world, "water", agent.x, agent.y)
            if not water or water.quantity <= 0:
                return "Looked for water here but found none."
            water.quantity -= 1
            agent.thirst = max(0, agent.thirst - 55)
            self._remember(agent, "Found water here and drank.")
            self._learn(agent, "finding water")
            return "Found water and drank."
        if action.action == "rest":
            agent.energy = min(100, agent.energy + 30)
            agent.health = min(100, agent.health + 2)
            return "Rested and recovered some energy."
        if action.action == "gather":
            kind = action.resource_kind or "wood"
            node = self._resource_at(world, kind, agent.x, agent.y)
            if not node or node.quantity <= 0:
                return f"There was no {kind} to gather here."
            node.quantity -= 1
            agent.inventory[kind] = agent.inventory.get(kind, 0) + 1
            self._learn(agent, f"gathering {kind}")
            return f"Gathered one unit of {kind}."
        if action.action == "communicate":
            target = self._nearby_target(world, agent, action.target_agent_id, 3)
            if not target or not action.message:
                return "Could not communicate with the selected person."
            self._remember(target, f"{agent.name} said: {action.message}")
            self._remember(agent, f"Told {target.name}: {action.message}")
            self._adjust_relationship(agent, target, 2)
            self._spread_belief(world, target, action.message)
            self._record(world, EventSource.AGENT_ACTION, EventKind.AGENT_SPOKE, f"{agent.name} shared an idea with {target.name}: {action.message}", [agent.id, target.id])
            return f"Shared an idea with {target.name}."
        if action.action == "help":
            target = self._nearby_target(world, agent, action.target_agent_id, 1)
            if not target:
                return "No one nearby could be helped."
            target.health = min(100, target.health + 8)
            target.hunger = max(0, target.hunger - 10)
            target.thirst = max(0, target.thirst - 10)
            target.energy = min(100, target.energy + 8)
            self._adjust_relationship(agent, target, 5)
            self._remember(target, f"{agent.name} cared for you.")
            return f"Helped {target.name}."
        if action.action == "teach":
            target = self._nearby_target(world, agent, action.target_agent_id, 1)
            if not target or not action.message:
                return "No nearby learner or lesson was available."
            lesson = action.message.strip()
            if lesson not in agent.knowledge and not self._has_experience(agent, lesson):
                return "Could not teach something this person had not learned or experienced."
            if lesson not in target.knowledge:
                target.knowledge.append(lesson)
            self._remember(target, f"{agent.name} taught you: {lesson}")
            self._adjust_relationship(agent, target, 2)
            self._record(world, EventSource.AGENT_ACTION, EventKind.TEACHING, f"{agent.name} taught {target.name}: {lesson}", [agent.id, target.id])
            return f"Taught {target.name} a lesson."
        if action.action == "build":
            return self._build(world, agent, action.structure_type or "lean_to")
        if action.action == "fight":
            return self._fight(world, agent, action.target_agent_id)
        if action.action == "form_group":
            return self._form_group(world, agent, action.message, action.group_type)
        if action.action == "join_group":
            return self._join_group(world, agent, action.target_group_id)
        if action.action == "create_belief":
            return self._create_belief(world, agent, action)
        return "The action was not supported by this world."

    def _resolve_bond(self, world: WorldState, first: Agent, second: Agent) -> None:
        if not self._adult(first) or not self._adult(second) or first.id == second.id:
            self._record_action(world, first, AgentAction(action="bond", target_agent_id=second.id), "A bond could not form at this life stage.")
            return
        if self._distance(first, second) > 1:
            self._record_action(world, first, AgentAction(action="bond", target_agent_id=second.id), "The two people were too far apart.")
            return
        previous = (first.bonded_partner_id, second.bonded_partner_id)
        first.bonded_partner_id = second.id
        second.bonded_partner_id = first.id
        self._adjust_relationship(first, second, 10)
        kind = EventKind.RELATIONSHIP
        if previous[0] not in (None, second.id) or previous[1] not in (None, first.id):
            # A new mutual bond can disrupt an existing one; the timeline makes that visible.
            kind = EventKind.RELATIONSHIP
        self._record(world, EventSource.AGENT_ACTION, kind, f"{first.name} and {second.name} formed a mutual bond.", [first.id, second.id])
        self._record_action(world, first, AgentAction(action="bond", target_agent_id=second.id), "A mutual bond formed.")
        self._record_action(world, second, AgentAction(action="bond", target_agent_id=first.id), "A mutual bond formed.")

    def _resolve_reproduction(self, world: WorldState, first: Agent, second: Agent) -> None:
        female = first if first.sex == "female" else second if second.sex == "female" else None
        male = first if first.sex == "male" else second if second.sex == "male" else None
        if not female or not male or not self._adult(female) or not self._adult(male):
            result = "Reproduction was not biologically possible for this pair."
        elif self._distance(female, male) > 1:
            result = "The two people were too far apart."
        elif female.pregnancy_days_remaining is not None:
            result = f"{female.name} is already pregnant."
        elif min(female.health, male.health) < 35 or max(female.hunger, male.hunger, female.thirst, male.thirst) > 90:
            result = "Their health or immediate needs made reproduction unsafe."
        else:
            female.pregnancy_days_remaining = PREGNANCY_DAYS
            female.other_parent_id = male.id
            self._adjust_relationship(female, male, 3)
            result = f"{female.name} became pregnant; birth is expected in about {PREGNANCY_DAYS} simulated days."
        self._record(world, EventSource.AGENT_ACTION, EventKind.ACTION, result, [first.id, second.id], {"action": "mutual_reproduction"})
        self._record_action(world, first, AgentAction(action="reproduce", target_agent_id=second.id), result)
        self._record_action(world, second, AgentAction(action="reproduce", target_agent_id=first.id), result)

    def _advance_biology(self, world: WorldState, agent: Agent) -> None:
        """Advance body state once per simulated day; all ages use the same hazard rules."""
        agent.age_days += 1
        agent.hunger = min(100, agent.hunger + (0.9 if agent.age_days < 6 * 365 else 1.4))
        agent.thirst = min(100, agent.thirst + (1.2 if agent.age_days < 6 * 365 else 2.0))
        agent.energy = max(0, agent.energy - (0.5 if agent.age_days < 6 * 365 else 1.0))

        if agent.hunger >= 85:
            agent.health = max(0, agent.health - 2.0)
        if agent.thirst >= 85:
            agent.health = max(0, agent.health - 4.0)
        if agent.energy <= 5:
            agent.health = max(0, agent.health - 1.0)

        if agent.disease:
            agent.health = max(0, agent.health - (3 if agent.disease == "wound infection" else 2))
            agent.disease_days += 1
            if agent.disease_days >= 5 and self._random.random() < 0.15:
                disease = agent.disease
                agent.disease = None
                agent.disease_days = 0
                agent.immune_to.append(disease)
                self._record(world, EventSource.NATURAL, EventKind.DISEASE_RECOVERED, f"{agent.name} recovered from {disease}.", [agent.id])
            elif agent.disease:
                spread_chance = 0.10 if agent.disease == "respiratory illness" else 0.05
                for other in world.agents:
                    if other.alive and not other.disease and self._distance(agent, other) <= 1:
                        if self._random.random() < spread_chance:
                            self._infect(world, other, agent.disease, EventSource.NATURAL)

        if agent.pregnancy_days_remaining is not None:
            agent.pregnancy_days_remaining -= 1
            if agent.pregnancy_days_remaining <= 0:
                self._give_birth(world, agent)
        if agent.age_days > 45 * 365:
            # Age raises risk gradually; other hazards can still kill at any age.
            daily_age_risk = min(0.002, (agent.age_days - 45 * 365) / (35 * 365 * 12000))
            if self._random.random() < daily_age_risk:
                agent.health = max(0, agent.health - 18)
                self._record(world, EventSource.NATURAL, EventKind.INJURY, f"{agent.name} suffered an age-related health decline.", [agent.id])
        self._check_death(world, agent, "illness or unmet biological needs")

    def _give_birth(self, world: WorldState, mother: Agent) -> None:
        father = self._get_agent(mother.other_parent_id) if mother.other_parent_id else None
        if not mother.alive:
            mother.pregnancy_days_remaining = None
            return
        father = father if father and father.alive else None
        parents = [mother] + ([father] if father else [])
        inherited: dict[str, float] = {}
        for trait in TRAIT_NAMES:
            values = [parent.traits.get(trait, 0.5) for parent in parents]
            inherited[trait] = min(1, max(0, sum(values) / len(values) + self._random.uniform(-0.12, 0.12)))
        names = ["Tavi", "Suri", "Kori", "Luma", "Ravi", "Mira", "Oru", "Sena"]
        sex = self._random.choice(["male", "female"])
        child = Agent(
            id=str(uuid4()),
            name=self._random.choice(names),
            sex=sex,
            age_days=0,
            x=mother.x,
            y=mother.y,
            health=self._random.randint(65, 100),
            hunger=10,
            thirst=10,
            energy=75,
            # A child's brain uses the world's shared model; inherited traits remain individual.
            model=world.global_model,
            traits=inherited,
            parent_ids=[parent.id for parent in parents],
        )
        for parent in parents:
            parent.children_ids.append(child.id)
            parent.memories.append(f"Your child {child.name} was born.")
        # Initial relationship links help caregivers notice and respond to the newborn.
        for parent in parents:
            parent.relationship_scores[child.id] = 50
            child.relationship_scores[parent.id] = 50
        world.agents.append(child)
        mother.pregnancy_days_remaining = None
        mother.other_parent_id = None
        self._record(world, EventSource.NATURAL, EventKind.BIRTH, f"{child.name} was born to {', '.join(p.name for p in parents)}.", [child.id, *[p.id for p in parents]], {"sex": sex, "inherited_traits": inherited})

    def _advance_environment(self, world: WorldState) -> None:
        # Seasons and weather are lightweight world pressures, not a full climate model.
        day_of_year = world.tick % 365
        world.season = ("spring", "summer", "autumn", "winter")[min(3, day_of_year // 91)]
        if self._random.random() < 0.08:
            world.weather = self._random.choice(("clear", "rain", "heat", "cold", "wind"))
        if world.weather == "heat":
            for agent in world.agents:
                if agent.alive:
                    agent.thirst = min(100, agent.thirst + 0.8)

    def _regenerate_resources(self, world: WorldState) -> None:
        if world.tick % 7:
            return
        for node in world.resources:
            if node.kind == "food":
                growth = 1 if world.season == "winter" else 3
                node.quantity = min(node.capacity, node.quantity + growth)
            elif node.kind == "water":
                node.quantity = min(node.capacity, node.quantity + (2 if world.season == "summer" else 5))
            elif node.kind == "wood" and world.season != "winter":
                node.quantity = min(node.capacity, node.quantity + 1)

    def _natural_events(self, world: WorldState) -> None:
        if self._random.random() < settings.disease_emergence_probability:
            susceptible = [a for a in world.agents if a.alive and not a.disease]
            if susceptible:
                self._infect(world, self._random.choice(susceptible), self._random.choice(DISEASES), EventSource.NATURAL)
        if self._random.random() >= settings.natural_event_probability:
            return
        kind = self._random.choices(("wildfire", "storm", "flood", "drought", "mishap"), (1, 3, 1, 1, 4))[0]
        x, y = self._random.randrange(world.width), self._random.randrange(world.height)
        if kind == "mishap":
            living = [a for a in world.agents if a.alive]
            if living:
                victim = self._random.choice(living)
                damage = self._random.randint(4, 18)
                victim.health = max(0, victim.health - damage)
                self._check_death(world, victim, "a natural mishap")
                self._record(world, EventSource.NATURAL, EventKind.NATURAL_EVENT, f"A natural mishap injured {victim.name}.", [victim.id], {"damage": damage})
            return
        damage = {"wildfire": 32, "storm": 12, "flood": 20, "drought": 3}[kind]
        radius = 2.8 if kind == "wildfire" else 2.6 if kind == "flood" else 4.2
        affected = self._hazard_damage(world, x, y, radius, damage, kind, EventSource.NATURAL)
        self._apply_hazard_to_resources(world, x, y, radius, kind)
        self._record(world, EventSource.NATURAL, EventKind.NATURAL_EVENT, f"A {kind} occurred near ({x}, {y}).", affected, {"event": kind, "x": x, "y": y})

    def _fallback_action(self, agent: Agent, world: WorldState) -> AgentAction:
        """Conservative local behavior keeps the world alive while Ollama is unavailable."""
        if agent.thirst >= 48:
            water = self._nearest_resource(world, "water", agent)
            if water:
                return self._move_or_act(agent, water, "drink", "Find water")
        if agent.hunger >= 48:
            food = self._nearest_resource(world, "food", agent)
            if food:
                return self._move_or_act(agent, food, "forage", "Find food")
        child_needing_care = next(
            (a for a in world.agents if a.alive and a.age_days < 3 * 365 and self._distance(agent, a) <= 1 and (a.hunger > 55 or a.thirst > 55 or a.health < 60)),
            None,
        )
        if child_needing_care:
            return AgentAction(action="help", target_agent_id=child_needing_care.id, reason="Care for a nearby child")
        if agent.health < 60 or agent.energy < 35:
            return AgentAction(action="rest", reason="Recover health and energy")
        learner = next(
            (a for a in world.agents if a.alive and 3 * 365 <= a.age_days < ADULT_AGE_DAYS and self._distance(agent, a) <= 1 and any(item not in a.knowledge for item in agent.knowledge)),
            None,
        )
        if learner and agent.knowledge:
            lesson = next(item for item in agent.knowledge if item not in learner.knowledge)
            return AgentAction(action="teach", target_agent_id=learner.id, message=lesson, reason="Pass learned knowledge to a child")
        if self._adult(agent) and not agent.bonded_partner_id:
            possible_partner = next(
                (a for a in world.agents if a.alive and a.id != agent.id and self._adult(a) and self._distance(agent, a) <= 1 and a.sex != agent.sex),
                None,
            )
            if possible_partner:
                return AgentAction(action="bond", target_agent_id=possible_partner.id, reason="Form a mutual bond")
        partner = next((a for a in world.agents if a.id == agent.bonded_partner_id and a.alive), None)
        pregnant_person = agent if agent.sex == "female" else partner
        if (
            partner and partner.alive and self._adult(agent) and self._adult(partner)
            and agent.sex != partner.sex and pregnant_person
            and pregnant_person.pregnancy_days_remaining is None
            and max(agent.hunger, partner.hunger, agent.thirst, partner.thirst) < 45
            and world.tick % 14 == 0
        ):
            return AgentAction(action="reproduce", target_agent_id=partner.id, reason="Choose to have a child")
        # Once immediate needs are met, fallback agents slowly invest in shared shelter.
        if self._adult(agent) and world.tick % 11 == 0 and len(world.structures) < 8:
            preferred = "lean_to" if world.tech_level == 0 else "hut" if world.tech_level == 1 else "communal_house"
            required_level, cost = BUILDING_RULES[preferred]
            missing = [resource for resource, amount in cost.items() if agent.inventory.get(resource, 0) < amount]
            if not missing and world.tech_level >= required_level:
                return AgentAction(action="build", structure_type=preferred, reason="Build shelter with available materials")
            resource_kind = next(iter(missing), "wood")
            resource = self._nearest_resource(world, resource_kind, agent)
            if resource:
                if (resource.x, resource.y) == (agent.x, agent.y):
                    return AgentAction(action="gather", resource_kind=resource_kind, reason="Gather materials for shelter")
                return self._move_or_act(agent, resource, "gather", "Find building materials", resource_kind)
        if self._random.random() < 0.08:
            return AgentAction(action="communicate", target_agent_id=next((a.id for a in world.agents if a.alive and a.id != agent.id and self._distance(agent, a) <= 3), None), message="Food and water matter for our survival.", reason="Share a survival idea")
        return AgentAction(action="rest", reason="No immediate need")

    def _prepare_resource_action(self, world: WorldState, agent: Agent, action: AgentAction) -> AgentAction:
        """Turn a resource choice into one sensible step when its target is farther away."""
        resource_kind = {"forage": "food", "drink": "water"}.get(action.action)
        if action.action == "gather":
            resource_kind = action.resource_kind or "wood"
        if not resource_kind:
            return action
        local_resource = self._resource_at(world, resource_kind, agent.x, agent.y)
        if local_resource and local_resource.quantity > 0:
            return action
        # The engine may only route toward a resource that this person can currently observe.
        visible_targets = [
            node for node in world.resources
            if node.kind == resource_kind and node.quantity > 0
            and self._distance_to(node.x, node.y, agent.x, agent.y) <= 5
        ]
        target = min(
            visible_targets,
            key=lambda node: self._distance_to(agent.x, agent.y, node.x, node.y),
            default=None,
        )
        if not target:
            return action
        return self._move_or_act(
            agent,
            target,
            action.action,
            f"The model chose to {action.action}; move toward nearby {resource_kind} first",
            resource_kind if action.action == "gather" else None,
        )

    def _build(self, world: WorldState, agent: Agent, kind: str) -> str:
        if kind not in BUILDING_RULES:
            return "That kind of structure is not known in this world."
        required_level, cost = BUILDING_RULES[kind]
        if world.tech_level < required_level:
            return f"The community has not discovered the knowledge needed to build a {kind.replace('_', ' ')}."
        missing = [name for name, amount in cost.items() if agent.inventory.get(name, 0) < amount]
        if missing:
            return f"Not enough materials; gather {', '.join(missing)} first."
        for name, amount in cost.items():
            agent.inventory[name] -= amount
        structure = Structure(
            id=str(uuid4()), kind=kind, x=agent.x, y=agent.y,
            owner_agent_id=agent.id, built_at_tick=world.tick,
        )
        world.structures.append(structure)
        self._learn(agent, f"building:{kind}")
        old_level = world.tech_level
        world.tech_level = min(3, len(world.structures) // 2)
        if world.tech_level > old_level:
            self._record(world, EventSource.AGENT_ACTION, EventKind.DISCOVERY, f"The community developed new building knowledge (level {world.tech_level}).", [agent.id])
        if kind == "farm":
            world.resources.append(ResourceNode(kind="food", x=agent.x, y=agent.y, quantity=12, capacity=24))
        self._record(world, EventSource.AGENT_ACTION, EventKind.CONSTRUCTION, f"{agent.name} built a {kind.replace('_', ' ')}.", [agent.id], {"structure_id": structure.id, "owner_agent_id": agent.id, "cost": cost})
        return f"Built a {kind.replace('_', ' ')}."

    def _resolve_bond(self, world: WorldState, first: Agent, second: Agent) -> None:
        if not self._adult(first) or not self._adult(second) or first.id == second.id:
            self._record_action(world, first, AgentAction(action="bond", target_agent_id=second.id), "A bond could not form at this life stage.")
            return
        if self._distance(first, second) > 1:
            self._record_action(world, first, AgentAction(action="bond", target_agent_id=second.id), "The two people were too far apart.")
            return
        prior_partners = (first.bonded_partner_id, second.bonded_partner_id)
        first.bonded_partner_id = second.id
        second.bonded_partner_id = first.id
        self._adjust_relationship(first, second, 10)
        details = {"previous_partners": list(prior_partners)}
        self._record(world, EventSource.AGENT_ACTION, EventKind.RELATIONSHIP, f"{first.name} and {second.name} formed a mutual bond.", [first.id, second.id], details)
        self._record_action(world, first, AgentAction(action="bond", target_agent_id=second.id), "A mutual bond formed.")
        self._record_action(world, second, AgentAction(action="bond", target_agent_id=first.id), "A mutual bond formed.")

    def _resolve_reproduction(self, world: WorldState, first: Agent, second: Agent) -> None:
        female = first if first.sex == "female" else second if second.sex == "female" else None
        male = first if first.sex == "male" else second if second.sex == "male" else None
        if not female or not male or not self._adult(female) or not self._adult(male):
            result = "Reproduction was not biologically possible for this pair."
        elif self._distance(female, male) > 1:
            result = "The two people were too far apart."
        elif female.pregnancy_days_remaining is not None:
            result = f"{female.name} is already pregnant."
        elif min(female.health, male.health) < 35 or max(female.hunger, male.hunger, female.thirst, male.thirst) > 90:
            result = "Their health or immediate needs made reproduction unsafe."
        else:
            female.pregnancy_days_remaining = PREGNANCY_DAYS
            female.other_parent_id = male.id
            self._adjust_relationship(female, male, 3)
            result = f"{female.name} became pregnant; birth is expected in about {PREGNANCY_DAYS} simulated days."
        affair = bool(female and result.startswith(f"{female.name} became pregnant")) and any(
            person.bonded_partner_id not in (None, partner.id)
            for person, partner in ((first, second), (second, first))
        )
        if affair:
            self._record(world, EventSource.AGENT_ACTION, EventKind.AFFAIR, f"The reproductive choice involved a relationship outside an existing bond.", [first.id, second.id])
            for person, partner in ((first, second), (second, first)):
                if person.bonded_partner_id and person.bonded_partner_id != partner.id:
                    previous = next((a for a in world.agents if a.id == person.bonded_partner_id), None)
                    if previous:
                        self._adjust_relationship(person, previous, -25)
        self._record(world, EventSource.AGENT_ACTION, EventKind.ACTION, result, [first.id, second.id], {"action": "mutual_reproduction", "affair": affair})
        self._record_action(world, first, AgentAction(action="reproduce", target_agent_id=second.id), result)
        self._record_action(world, second, AgentAction(action="reproduce", target_agent_id=first.id), result)

    def _fight(self, world: WorldState, agent: Agent, target_id: str | None) -> str:
        target = self._nearby_target(world, agent, target_id, 1)
        if not target:
            return "There was no nearby target for the fight."
        damage = self._random.randint(5, 18) + round(agent.traits.get("aggression", 0.5) * 8)
        target.health = max(0, target.health - damage)
        agent.energy = max(0, agent.energy - 12)
        self._adjust_relationship(agent, target, -30)
        self._record(world, EventSource.AGENT_ACTION, EventKind.FIGHT, f"{agent.name} fought {target.name} and caused {damage} injury.", [agent.id, target.id], {"damage": damage})
        self._check_death(world, target, "violence", EventSource.AGENT_ACTION)
        return f"Fought {target.name}."

    def _form_group(self, world: WorldState, agent: Agent, proposed_name: str, kind: str) -> str:
        if any(agent.id in group.member_ids for group in world.groups):
            return "This person already belongs to a group."
        name = proposed_name.strip()[:60] or f"{agent.name}'s group"
        group = SocialGroup(
            id=str(uuid4()), name=name, kind=kind, leader_agent_id=agent.id,
            member_ids=[agent.id], formed_at_tick=world.tick,
        )
        world.groups.append(group)
        self._record(world, EventSource.AGENT_ACTION, EventKind.GROUP_FORMED, f"{agent.name} formed the {name} ({kind}).", [agent.id], {"group_id": group.id, "group_kind": kind})
        return f"Formed the group {name}."

    def _join_group(self, world: WorldState, agent: Agent, group_id: str | None) -> str:
        group = next((g for g in world.groups if g.id == group_id), None)
        if not group:
            return "That group does not exist."
        if any(agent.id in g.member_ids for g in world.groups):
            return "This person already belongs to a group."
        group.member_ids.append(agent.id)
        self._record(world, EventSource.AGENT_ACTION, EventKind.GROUP_JOINED, f"{agent.name} joined {group.name}.", [agent.id, *group.member_ids], {"group_id": group.id})
        return f"Joined {group.name}."

    def _create_belief(self, world: WorldState, agent: Agent, action: AgentAction) -> str:
        name = action.belief_name.strip() or action.message.split(":", 1)[0].strip()[:80]
        description = action.message.split(":", 1)[-1].strip() if ":" in action.message else action.message.strip()
        if not name or not description:
            return "A belief needs a name and a short description."
        if any(b.name.casefold() == name.casefold() for b in world.beliefs):
            return "A belief with that name already exists."
        belief = CulturalBelief(
            id=str(uuid4()), name=name, kind=action.belief_type or "myth",
            description=description[:240], creator_agent_id=agent.id,
            believer_ids=[agent.id], created_at_tick=world.tick,
        )
        world.beliefs.append(belief)
        self._learn(agent, f"belief:{belief.name}")
        self._record(world, EventSource.AGENT_ACTION, EventKind.BELIEF_CREATED, f"{agent.name} created the {belief.kind} belief '{belief.name}'.", [agent.id], {"belief_id": belief.id, "description": belief.description})
        return f"Created the belief {belief.name}."

    def _spread_belief(self, world: WorldState, listener: Agent, message: str) -> None:
        lowered = message.casefold()
        for belief in world.beliefs:
            if belief.name.casefold() in lowered and listener.id not in belief.believer_ids:
                belief.believer_ids.append(listener.id)
                self._learn(listener, f"belief:{belief.name}")

    def _infect(self, world: WorldState, agent: Agent, disease: str, source: EventSource) -> None:
        if not agent.alive or agent.disease or disease in agent.immune_to:
            return
        agent.disease = disease
        agent.disease_days = 0
        self._remember(agent, f"You began to feel sick with {disease}.")
        self._record(world, source, EventKind.DISEASE_STARTED, f"{agent.name} became ill with {disease}.", [agent.id], {"disease": disease})

    def _hazard_damage(self, world: WorldState, x: int, y: int, radius: float, damage: int, hazard: str, source: EventSource) -> list[str]:
        affected: list[str] = []
        for agent in world.agents:
            distance = self._distance_to(agent.x, agent.y, x, y)
            if agent.alive and distance <= radius:
                # Model hazard strength as a radial force with a softer edge.
                falloff = max(0.18, 1 - (distance / radius) * 0.78)
                impact = max(1, round(damage * falloff))
                agent.health = max(0, agent.health - impact)
                affected.append(agent.id)
                self._check_death(world, agent, hazard, source)
        return affected

    def _apply_hazard_to_resources(self, world: WorldState, x: int, y: int, radius: float, hazard: str) -> None:
        """Spread environmental damage to nearby food and building materials."""
        for node in world.resources:
            distance = self._distance_to(node.x, node.y, x, y)
            if distance > radius:
                continue
            falloff = max(0.12, 1 - distance / radius)
            if hazard in {"wildfire", "drought"} and node.kind == "food":
                node.quantity = max(0, node.quantity - math.ceil(node.quantity * falloff))
            elif hazard == "wildfire" and node.kind == "wood":
                node.quantity = max(0, node.quantity - math.ceil(node.quantity * falloff * 0.65))
            elif hazard == "flood" and node.kind in {"food", "wood"}:
                node.quantity = max(0, node.quantity - math.ceil(node.quantity * falloff * 0.35))

    def _check_death(self, world: WorldState, agent: Agent, cause: str, source: EventSource = EventSource.NATURAL) -> None:
        if agent.alive and agent.health <= 0:
            agent.alive = False
            self._record(world, source, EventKind.DEATH, f"{agent.name} died at age {agent.age_years} from {cause}.", [agent.id], {"age_years": agent.age_years, "cause": cause})

    def _get_agent(self, agent_id: str | None) -> Agent:
        agent = next((a for a in self.state.agents if a.id == agent_id), None)
        if agent is None:
            raise KeyError(f"Unknown agent: {agent_id}")
        return agent

    @staticmethod
    def _nearby_target(world: WorldState, agent: Agent, target_id: str | None, radius: int) -> Agent | None:
        target = next((a for a in world.agents if a.id == target_id and a.alive), None)
        return target if target and target.id != agent.id and SimulationEngine._distance(agent, target) <= radius else None

    @staticmethod
    def _resource_at(world: WorldState, kind: str, x: int, y: int) -> ResourceNode | None:
        return next((r for r in world.resources if r.kind == kind and r.x == x and r.y == y), None)

    @staticmethod
    def _distance(first: Agent, second: Agent) -> int:
        return abs(first.x - second.x) + abs(first.y - second.y)

    @staticmethod
    def _distance_to(x1: int, y1: int, x2: int, y2: int) -> float:
        # Distances match the circular event footprints shown on the 3D land.
        return math.hypot(x1 - x2, y1 - y2)

    @staticmethod
    def _adult(agent: Agent) -> bool:
        return agent.alive and agent.age_days >= ADULT_AGE_DAYS

    @staticmethod
    def _is_child(agent: Agent) -> bool:
        return agent.age_days < ADULT_AGE_DAYS

    @staticmethod
    def _remember(agent: Agent, memory: str) -> None:
        agent.memories.append(memory)
        agent.memories = agent.memories[-80:]

    @staticmethod
    def _learn(agent: Agent, knowledge: str) -> None:
        if knowledge not in agent.knowledge:
            agent.knowledge.append(knowledge)

    @staticmethod
    def _has_experience(agent: Agent, lesson: str) -> bool:
        target = lesson.casefold()
        return any(target in memory.casefold() for memory in agent.memories)

    @staticmethod
    def _adjust_relationship(first: Agent, second: Agent, amount: float) -> None:
        first.relationship_scores[second.id] = min(100, max(-100, first.relationship_scores.get(second.id, 0) + amount))
        second.relationship_scores[first.id] = min(100, max(-100, second.relationship_scores.get(first.id, 0) + amount))

    def _nearest_resource(self, world: WorldState, kind: str, agent: Agent) -> ResourceNode | None:
        options = [r for r in world.resources if r.kind == kind and r.quantity > 0]
        return min(options, key=lambda r: self._distance_to(agent.x, agent.y, r.x, r.y), default=None)

    def _move_or_act(
        self,
        agent: Agent,
        node: ResourceNode,
        action: str,
        reason: str,
        resource_kind: str | None = None,
    ) -> AgentAction:
        dx = 0 if node.x == agent.x else (1 if node.x > agent.x else -1)
        dy = 0 if node.y == agent.y else (1 if node.y > agent.y else -1)
        if dx == 0 and dy == 0:
            return AgentAction(action=action, reason=reason, resource_kind=resource_kind)
        # Move one cardinal tile per day, preventing diagonal speed advantages.
        if abs(node.x - agent.x) > abs(node.y - agent.y):
            dy = 0
        else:
            dx = 0
        return AgentAction(action="move", dx=dx, dy=dy, reason=reason, resource_kind=resource_kind)

    @staticmethod
    def _record_action(
        world: WorldState,
        agent: Agent,
        action: AgentAction,
        result: str,
        proposed_action: AgentAction | None = None,
    ) -> None:
        agent.last_action = action
        details: dict[str, object] = {"action": action.action, "reason": action.reason, "result": result}
        if proposed_action:
            details["proposed_action"] = proposed_action.action
        SimulationEngine._record(world, EventSource.AGENT_ACTION, EventKind.ACTION, f"{agent.name}: {result}", [agent.id], details)

    @staticmethod
    def _record(
        world: WorldState,
        source: EventSource,
        kind: EventKind,
        message: str,
        agent_ids: list[str] | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        world.events.append(WorldEvent(id=str(uuid4()), tick=world.tick, source=source, kind=kind, message=message, agent_ids=agent_ids or [], details=details or {}))

    def _save(self) -> None:
        self._store.save(self.state)


engine = SimulationEngine()
