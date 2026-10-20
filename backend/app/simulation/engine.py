"""Authoritative world rules for the first generational simulation prototype."""

from __future__ import annotations

import asyncio
import math
import random
import time
from uuid import uuid4

from app.agent_brain.ollama_client import OllamaClient, OllamaError
from app.domain import (
    Agent,
    AgentAction,
    AgentStateChange,
    Animal,
    CulturalBelief,
    CropPlot,
    EventKind,
    EventSource,
    ResourceNode,
    SocialGroup,
    SpectatorEventRequest,
    Structure,
    TerrainCell,
    WorldEvent,
    WorldState,
)
from app.settings import settings
from app.storage.sqlite_store import SQLiteWorldStore
from app.simulation.rules import (
    ADULT_AGE_DAYS,
    BUILDING_RULES,
    DISEASES,
    FARMABLE_TERRAIN,
    FOOD_KINDS,
    MAX_POPULATION,
    PREGNANCY_DAYS,
    SHELTER_KINDS,
    TRAIT_NAMES,
)


class SimulationEngine:
    """Runs a single persisted world; model output never mutates state directly."""

    def __init__(self, database_path: str | None = None) -> None:
        self._lock = asyncio.Lock()
        self._tick_lock = asyncio.Lock()
        self._random = random.Random(7)
        self._ollama = OllamaClient()
        self._store = SQLiteWorldStore(database_path or settings.database_path)
        self._runner_task: asyncio.Task[None] | None = None
        self._clock_task: asyncio.Task[None] | None = None
        self._clock_at: float | None = None
        self._decision_epoch = 0
        self._tick_interval_seconds = settings.decision_interval_seconds
        self.state = self._store.load() or self._new_world(seed=7)
        self._upgrade_world_map(self.state)
        saved_random_state = self._store.load_random_state()
        if saved_random_state is not None:
            self._random.setstate(self._tuple_tree(saved_random_state))
        else:
            # Continue older databases from their world seed; future saves persist the full stream.
            self._random.seed(self.state.seed)
        # Older snapshots may contain per-person model choices; migrate them to one shared brain.
        # Always migrate legacy snapshots to the one supported shared model.
        self.state.global_model = settings.ollama_model
        for person in self.state.agents:
            person.model = self.state.global_model
            person.x = min(max(person.x, 0), self.state.width - 1)
            person.y = min(max(person.y, 0), self.state.height - 1)
        # Snap pre-existing out-of-bounds material nodes onto the playable map during migration.
        for resource in self.state.resources:
            resource.x = min(max(resource.x, 0), self.state.width - 1)
            resource.y = min(max(resource.y, 0), self.state.height - 1)
        for structure in self.state.structures:
            structure.x = min(max(structure.x, 0), self.state.width - 1)
            structure.y = min(max(structure.y, 0), self.state.height - 1)
        # Preserve the spectator's run/pause choice across application restarts.
        self.state.processing = False
        self._save()

    def _new_world(self, seed: int) -> WorldState:
        self._random.seed(seed)
        world = WorldState(
            id=str(uuid4()),
            seed=seed,
            global_model=settings.ollama_model,
            width=36,
            height=18,
            day_length_seconds=settings.day_length_seconds,
            agents=[
                Agent(
                    id="agent-1",
                    name="Aru",
                    sex="male",
                    x=17,
                    y=8,
                    model=settings.ollama_model,
                    traits={"curiosity": 0.7, "cooperation": 0.6, "aggression": 0.3, "resilience": 0.6, "sociability": 0.6},
                ),
                Agent(
                    id="agent-2",
                    name="Nima",
                    sex="female",
                    x=18,
                    y=8,
                    model=settings.ollama_model,
                    traits={"curiosity": 0.6, "cooperation": 0.7, "aggression": 0.2, "resilience": 0.7, "sociability": 0.7},
                ),
            ],
            resources=[],
        )
        world.terrain = self._generate_terrain(world.width, world.height, seed)
        world.resources = self._seed_resources(world)
        # Start in a viable natural habitat, rather than the old hardcoded mountain summit.
        habitats = [cell for cell in world.terrain if cell.kind in FARMABLE_TERRAIN]
        def habitat_score(cell: TerrainCell) -> float:
            total = self._distance_to(cell.x, cell.y, 18, 8, world.width) * 0.2
            for kinds, weight in (({"water"}, 2), (FOOD_KINDS, 1), ({"wood"}, 1)):
                nearest = min((self._distance_to(cell.x, cell.y, node.x, node.y, world.width)
                               for node in world.resources if node.kind in kinds), default=100)
                total += nearest * weight
            return total
        habitat = min(habitats, key=habitat_score, default=None)
        if habitat:
            world.agents[0].x, world.agents[0].y = habitat.x, habitat.y
            neighbors = self._habitable_neighbors(world, habitat.x, habitat.y)
            world.agents[1].x, world.agents[1].y = min(neighbors, key=lambda point:
                habitat_score(self._terrain_at(world, point[0], point[1])))
        world.animals = self._seed_animals(world)
        # The starting pair know one another, but they still choose whether to bond or reproduce.
        world.agents[0].relationship_scores[world.agents[1].id] = 20
        world.agents[1].relationship_scores[world.agents[0].id] = 20
        world.agents[0].memories.append("You have lived near Nima for a long time.")
        world.agents[1].memories.append("You have lived near Aru for a long time.")
        self._record(world, EventSource.SYSTEM, EventKind.WORLD_STARTED, "A new world began with two independent agents.")
        return world

    def _upgrade_world_map(self, world: WorldState) -> None:
        """Migrate saved flat habitats onto the new fictional spherical biome map."""
        if not world.terrain:
            old_width, old_height = world.width, world.height
            if (old_width, old_height) != (36, 18):
                def remap(x: int, y: int) -> tuple[int, int]:
                    nx = round((x / max(1, old_width - 1)) * 35)
                    ny = round((y / max(1, old_height - 1)) * 17)
                    return nx, ny

                for person in world.agents:
                    person.x, person.y = remap(person.x, person.y)
                for item in world.resources:
                    item.x, item.y = remap(item.x, item.y)
                for item in world.structures:
                    item.x, item.y = remap(item.x, item.y)
                for plot in world.crops:
                    plot.x, plot.y = remap(plot.x, plot.y)
                world.width, world.height = 36, 18
            world.terrain = self._generate_terrain(world.width, world.height, world.seed)
            # Move people off ocean cells without changing their relative settlement area.
            for person in world.agents:
                person.x, person.y = self._nearest_land(world, person.x, person.y)
            for item in world.resources:
                item.x, item.y = self._nearest_land(world, item.x, item.y)
            for item in world.structures:
                item.x, item.y = self._nearest_land(world, item.x, item.y)
            for plot in world.crops:
                plot.x, plot.y = self._nearest_land(world, plot.x, plot.y)
        if not world.animals:
            world.animals = self._seed_animals(world)
        # Legacy worlds had generic food only; add edible plants and biome-based renewable food.
        if not any(node.kind in {"fruit", "vegetable"} for node in world.resources):
            world.resources.extend(self._seed_plant_resources(world))

    def _generate_terrain(self, width: int, height: int, seed: int = 7) -> list[TerrainCell]:
        """Create fictional continents and biomes from smooth seeded mathematical fields."""
        landmasses = [
            (0.48, 0.48, 0.20, 0.34), (0.15, 0.48, 0.13, 0.31),
            (0.81, 0.57, 0.12, 0.23), (0.27, 0.83, 0.12, 0.14),
            (0.75, 0.16, 0.11, 0.15),
        ]
        terrain_random = random.Random(seed)
        landmasses = [(cx + terrain_random.uniform(-0.015, 0.015), cy + terrain_random.uniform(-0.015, 0.015),
                       rx * terrain_random.uniform(0.95, 1.05), ry * terrain_random.uniform(0.95, 1.05))
                      for cx, cy, rx, ry in landmasses]
        cells: list[TerrainCell] = []
        for y in range(height):
            latitude = y / max(1, height - 1)
            polar = abs(latitude - 0.5) * 2
            for x in range(width):
                longitude = x / width
                scores = []
                for cx, cy, rx, ry in landmasses:
                    dx = min(abs(longitude - cx), 1 - abs(longitude - cx))
                    dy = latitude - cy
                    scores.append(math.exp(-1.8 * ((dx / rx) ** 2 + (dy / ry) ** 2)))
                landness = max(scores) + 0.045 * math.sin(x * 1.73 + y * 0.87) * math.cos(y * 1.39 - x * 0.22)
                moisture = 0.5 + 0.32 * math.sin(x * 0.51 + y * 0.27) + 0.15 * math.cos(y * 0.91 - x * 0.16)
                temperature = max(0, min(1, 1 - polar * 0.9 + 0.06 * math.sin(x * 0.3)))
                elevation = max(-1, min(1, (landness - 0.43) * 1.5 + 0.18 * math.sin(x * 0.83) * math.cos(y * 1.13)))
                if (polar > 0.8 and landness >= 0.27) or (landness >= 0.36 and temperature < 0.13):
                    kind = "ice" if landness >= 0.36 else "ocean"
                elif landness < 0.36:
                    kind = "ocean"
                elif elevation > 0.58:
                    kind = "mountain"
                elif moisture < 0.23 and temperature > 0.28:
                    kind = "desert"
                elif moisture > 0.78 and temperature > 0.62:
                    kind = "rainforest"
                elif temperature < 0.34 and moisture > 0.38:
                    kind = "boreal_forest"
                elif moisture > 0.54:
                    kind = "forest"
                else:
                    kind = "grassland" if moisture < 0.42 else "plains"
                    if (x * 11 + y * 7) % 17 == 0:
                        kind = "farmland"
                # Rivers and lakes are overlaid on habitable land, not represented as ocean tiles.
                if kind in {"plains", "grassland", "forest"}:
                    river_field = abs(math.sin(x * 0.42 + math.sin(y * 0.23) * 1.7) + 0.32 * math.cos(y * 0.8 + x * 0.14))
                    if river_field < 0.22 and moisture > 0.45:
                        kind = "river"
                    elif (x * 13 + y * 29) % 47 == 0 and moisture > 0.5:
                        kind = "lake"
                cells.append(TerrainCell(x=x, y=y, kind=kind, elevation=elevation, moisture=max(0, min(1, moisture)), temperature=temperature))
        if not any(cell.kind == "lake" for cell in cells):
            candidate = max((cell for cell in cells if cell.kind in {"plains", "grassland", "farmland", "forest"}),
                            key=lambda cell: cell.moisture, default=None)
            if candidate:
                candidate.kind = "lake"
        return cells

    @staticmethod
    def _terrain_at(world: WorldState, x: int, y: int) -> TerrainCell | None:
        return next((cell for cell in world.terrain if cell.x == x and cell.y == y), None)

    def _nearest_land(self, world: WorldState, x: int, y: int) -> tuple[int, int]:
        candidates = [cell for cell in world.terrain if cell.kind != "ocean"]
        closest = min(candidates, key=lambda cell: self._distance_to(cell.x, cell.y, x, y, world.width), default=None)
        return (closest.x, closest.y) if closest else (x, y)

    def _seed_resources(self, world: WorldState) -> list[ResourceNode]:
        """Place food, water, wood, and stone where the fictional biomes support them."""
        resources: list[ResourceNode] = []
        for cell in world.terrain:
            if cell.kind == "ocean":
                continue
            if cell.kind in {"river", "lake"}:
                resources.append(ResourceNode(kind="water", x=cell.x, y=cell.y, quantity=40, capacity=50, contamination=2))
            elif cell.kind in {"forest", "rainforest", "boreal_forest"} and (cell.x * 7 + cell.y * 11) % 5 == 0:
                resources.append(ResourceNode(kind="fruit", x=cell.x, y=cell.y, quantity=14, capacity=20))
            elif cell.kind in {"grassland", "plains", "farmland"} and (cell.x * 3 + cell.y * 5) % 7 == 0:
                resources.append(ResourceNode(kind="vegetable", x=cell.x, y=cell.y, quantity=12, capacity=18))
            if cell.kind in {"forest", "rainforest", "boreal_forest"} and (cell.x * 5 + cell.y * 13) % 4 == 0:
                resources.append(ResourceNode(kind="wood", x=cell.x, y=cell.y, quantity=15, capacity=24))
            if cell.kind == "mountain" and (cell.x + cell.y * 2) % 3 == 0:
                resources.append(ResourceNode(kind="stone", x=cell.x, y=cell.y, quantity=14, capacity=22))
        # Place a freshwater spring close to the first settlement even if its terrain is not a lake.
        if not any(node.kind == "water" and self._distance_to(node.x, node.y, 18, 8, world.width) <= 4 for node in resources):
            wx, wy = self._nearest_land(world, 20, 8)
            resources.append(ResourceNode(kind="water", x=wx, y=wy, quantity=35, capacity=45, contamination=1))
        if not any(node.kind in {"fruit", "vegetable"} and self._distance_to(node.x, node.y, 18, 8, world.width) <= 4 for node in resources):
            cell = min((cell for cell in world.terrain if cell.kind in {"forest", "rainforest", "grassland", "plains", "farmland"}),
                       key=lambda cell: self._distance_to(cell.x, cell.y, 18, 8, world.width), default=None)
            if cell:
                resources.append(ResourceNode(kind="fruit", x=cell.x, y=cell.y, quantity=12, capacity=18))
        if not any(node.kind == "wood" and self._distance_to(node.x, node.y, 18, 8, world.width) <= 4 for node in resources):
            cell = min((cell for cell in world.terrain if cell.kind in {"forest", "rainforest", "boreal_forest"}),
                       key=lambda cell: self._distance_to(cell.x, cell.y, 18, 8, world.width), default=None)
            if cell:
                resources.append(ResourceNode(kind="wood", x=cell.x, y=cell.y, quantity=14, capacity=20))
        return resources

    def _seed_plant_resources(self, world: WorldState) -> list[ResourceNode]:
        return [node for node in self._seed_resources(world) if node.kind in {"fruit", "vegetable"}]

    def _seed_animals(self, world: WorldState) -> list[Animal]:
        """Seed wild species across suitable land and keep the starting settlement nearby."""
        habitat_cells = [cell for cell in world.terrain if cell.kind in {"grassland", "plains", "farmland", "forest", "rainforest", "boreal_forest"}]
        species_by_habitat = {"grassland": "goat", "plains": "deer", "forest": "boar", "rainforest": "chicken", "boreal_forest": "hare", "farmland": "dog"}
        animals: list[Animal] = []
        if not habitat_cells:
            return animals
        for index, cell in enumerate(cell for cell in habitat_cells if self._random.random() < 0.25):
            species = ("goat", "chicken", "dog", "deer", "boar", "hare")[index % 6]
            if cell.kind in {"rainforest", "boreal_forest"}:
                species = species_by_habitat.get(cell.kind, species)
            animals.append(Animal(
                id=str(uuid4()), species=species, sex=self._random.choice(("male", "female")),
                animal_type="wild", age_days=self._random.randint(120, 1600),
                x=cell.x, y=cell.y, hunger=self._random.randint(5, 55),
                temperament=self._random.uniform(0.1, 0.8),
            ))
        founder = world.agents[0]
        start_cell = min(habitat_cells, key=lambda cell: self._distance_to(cell.x, cell.y, founder.x, founder.y, world.width))
        for species, dx in (("goat", -1), ("chicken", 1), ("dog", 0)):
            animal_x, animal_y = self._nearest_land(world, (start_cell.x + dx) % world.width, start_cell.y)
            animals.append(Animal(id=str(uuid4()), species=species, sex=self._random.choice(("male", "female")),
                                  age_days=self._random.randint(200, 1200), x=animal_x,
                                  y=animal_y, hunger=20, temperament=self._random.uniform(0.15, 0.7)))
        return animals

    async def reset(self, seed: int = 7) -> WorldState:
        async with self._tick_lock:
            async with self._lock:
                was_running = self.state.running
                self._clock_at = time.monotonic() if was_running else None
                self._decision_epoch += 1
                self.state = self._new_world(seed)
                self.state.running = was_running
                self._save()
                return self.state.model_copy(deep=True)

    async def snapshot(self) -> WorldState:
        async with self._lock:
            return self.state.model_copy(deep=True)

    async def start(self, interval_seconds: float | None = None) -> WorldState:
        async with self._lock:
            # Each interval is an agent decision opportunity, not a whole simulated day.
            self._tick_interval_seconds = min(max(interval_seconds or settings.decision_interval_seconds, 0.5), 10.0)
            self.state.running = True
            if self._clock_at is None:
                self._clock_at = time.monotonic()
            if self._clock_task is None or self._clock_task.done():
                self._clock_task = asyncio.create_task(self._clock_loop())
            if self._runner_task is None or self._runner_task.done():
                self._runner_task = asyncio.create_task(self._run_loop())
            self._save()
            return self.state.model_copy(deep=True)

    async def pause(self) -> WorldState:
        async with self._lock:
            self._decision_epoch += 1
            if self._clock_at is not None:
                self._advance_time(self.state, max(0, time.monotonic() - self._clock_at) * self.state.time_scale)
            self._clock_at = None
            self.state.running = False
            self.state.processing = False
            self._save()
            return self.state.model_copy(deep=True)

    async def change_speed(self, speed: float, automatic: bool) -> WorldState:
        async with self._lock:
            self.state.base_time_scale = self.state.time_scale = min(16, max(1, speed))
            self.state.auto_accelerate = automatic
            self.state.running_elapsed_seconds = 0
            self._save()
            return self.state.model_copy(deep=True)

    async def shutdown(self) -> None:
        """Suspend tasks without changing the persisted spectator run/pause choice."""
        async with self._lock:
            self._decision_epoch += 1
            self.state.processing = False
            self._save()
        tasks = [task for task in (self._runner_task, self._clock_task) if task]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _report_error(self, message: str, error: Exception) -> None:
        detail = str(error)[:300]
        previous = next((event for event in reversed(self.state.events) if event.kind == EventKind.SIMULATION_ERROR), None)
        if not previous or previous.details.get("error") != detail or previous.tick != self.state.tick:
            self._record(self.state, EventSource.SYSTEM, EventKind.SIMULATION_ERROR, message,
                         details={"error": detail, "recoverable": True})
        self.state.processing = False
        self._save()

    async def _run_loop(self) -> None:
        """Keep executing actions until explicit pause; transient failures retry with backoff."""
        while True:
            delay = max(0.35, self._tick_interval_seconds / math.sqrt(self.state.time_scale))
            await asyncio.sleep(delay)
            async with self._lock:
                if not self.state.running:
                    return
            try:
                await self._tick_once()
            except Exception as exc:
                async with self._lock:
                    self._report_error("An action round failed; the world is continuing and will retry.", exc)
                await asyncio.sleep(2)

    async def _clock_loop(self) -> None:
        """Clock and ecology continue through inference, interventions and human extinction."""
        while True:
            await asyncio.sleep(0.5)
            async with self._lock:
                if not self.state.running:
                    self._clock_at = None
                    return
                current = time.monotonic()
                elapsed = max(0, current - (self._clock_at if self._clock_at is not None else current))
                self._clock_at = current
                self.state.running_elapsed_seconds += elapsed
                if self.state.auto_accelerate:
                    stages = int(self.state.running_elapsed_seconds / max(1, settings.auto_acceleration_seconds))
                    self.state.time_scale = min(8, self.state.base_time_scale * 2 ** min(stages, 4))
                # Roll back only a failed clock update so a partial day cannot be applied twice.
                checkpoint = self.state.model_copy(deep=True)
                random_state = self._random.getstate()
                try:
                    self._advance_time(self.state, elapsed * self.state.time_scale)
                    self._move_animal_npcs(self.state)
                except Exception as exc:
                    self.state = checkpoint
                    self._random.setstate(random_state)
                    self._report_error("An ecology update failed; the world is continuing and will retry.", exc)
                self._save()

    def _advance_time(self, world: WorldState, elapsed_seconds: float = 0, force_day: bool = False) -> None:
        """All daily consequences share one clock; decision count never advances age."""
        progress = world.day_progress_seconds + max(0, elapsed_seconds)
        elapsed_days = 1 if force_day else int(progress // world.day_length_seconds)
        world.day_progress_seconds = progress % world.day_length_seconds
        for _ in range(elapsed_days):
            world.tick += 1
            self._advance_environment(world)
            self._regenerate_resources(world)
            self._advance_ecology(world)
            self._natural_events(world)
            for person in tuple(world.agents):
                if person.alive:
                    self._advance_biology(world, person)

    async def tick(self) -> WorldState:
        """Manually advance one complete simulated day and resolve one decision round."""
        try:
            return await self._tick_once(force_day=True)
        except Exception as exc:
            async with self._lock:
                if self.state.processing:
                    self._report_error("A manual step failed; the world remains available.", exc)
            raise

    async def _tick_once(self, elapsed_seconds: float = 0, force_day: bool = False) -> WorldState:
        # Keep reads and spectator inspection responsive while slow model calls are in flight.
        async with self._tick_lock:
            async with self._lock:
                world = self.state
                world.processing = True
                self._advance_time(world, elapsed_seconds, force_day)
                world_id = world.id
                decision_epoch = self._decision_epoch
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
            decision_slots = asyncio.Semaphore(4)
            continuing_ids: set[str] = set()

            async def decide_one(person: Agent) -> tuple[str, AgentAction | OllamaError]:
                if person.pending_action and max(person.hunger, person.thirst) < 75 and person.energy >= 15:
                    # Walking is execution of the person's earlier intention, not a fresh random LLM choice.
                    continuing_ids.add(person.id)
                    return person.id, person.pending_action.model_copy(deep=True)
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
                if decision_epoch != self._decision_epoch:
                    # Pause invalidates in-flight intentions instead of letting a late model act afterward.
                    world.processing = False
                    self._save()
                    return world.model_copy(deep=True)
                for agent_id, error in fallback_errors.items():
                    action = proposals[agent_id]
                    agent = next((person for person in world.agents if person.id == agent_id), None)
                    if agent:
                        self._record(world, EventSource.SYSTEM, EventKind.FALLBACK_DECISION, f"{agent.name}'s model could not decide; a basic survival policy chose instead.", [agent.id], {"error": error, "fallback_action": action.action})

                for person in world.agents:
                    if person.id in proposals:
                        person.decision_source = "fallback" if person.id in fallback_errors else "continuation" if person.id in continuing_ids else "llm"
                        if person.id not in continuing_ids:
                            person.intention_source = "fallback" if person.id in fallback_errors else "llm"
                            person.decisions_made += 1
                handled: set[str] = set()
                for agent_id, action in proposals.items():
                    if agent_id in handled:
                        continue
                    agent = next((person for person in world.agents if person.id == agent_id and person.alive), None)
                    if not agent:
                        continue
                    if action.structure_type in BUILDING_RULES and action.action in {"gather", "build"}:
                        agent.construction_project = action.structure_type
                    if action.action in {"bond", "reproduce"}:
                        agent.pending_action = None
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
                        resolved_action = self._prepare_corpse_action(world, agent, action)
                        if resolved_action is action:
                            resolved_action = self._prepare_resource_action(world, agent, action)
                        agent.pending_action = action.model_copy(deep=True) if (
                            resolved_action.action == "move" and action.action != "move"
                        ) else None
                        result = self._apply_action(world, agent, resolved_action)
                        # A chosen building project can gather its batch without repeatedly asking the brain.
                        if action.action == "gather" and action.structure_type in BUILDING_RULES:
                            cost = BUILDING_RULES[action.structure_type][1]
                            if (resolved_action.action == "gather" and result.startswith("Gathered")
                                and agent.inventory.get(action.resource_kind or "wood", 0) < cost.get(action.resource_kind or "wood", 0)):
                                agent.pending_action = action.model_copy(deep=True)
                        if result.startswith("Built") and action.structure_type == agent.construction_project:
                            agent.construction_project = None
                        self._record_action(
                            world,
                            agent,
                            resolved_action,
                            result,
                            proposed_action=action if resolved_action.action != action.action else None,
                        )
                    handled.add(agent.id)

                # Human extinction is an outcome; the clock and ecosystem keep running.
                if not any(agent.alive for agent in world.agents):
                    if not any(event.kind == EventKind.WORLD_EXTINCT for event in world.events):
                        self._record(world, EventSource.SYSTEM, EventKind.WORLD_EXTINCT,
                                     "The human population is extinct; the ecosystem continues running.")

                world.events = world.events[-settings.max_saved_events :]
                world.processing = False
                self._save()
                return world.model_copy(deep=True)

    async def change_global_model(self, model: str) -> WorldState:
        async with self._lock:
            model = model.strip()
            if model != settings.ollama_model:
                raise ValueError(f"Only {settings.ollama_model} is supported for this world")
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
        if self._is_child(agent) and action.action in {"build", "fight", "form_group", "reproduce", "bond", "hunt", "tame", "plant", "cook", "bury"}:
            return "This person is too young for that action."

        if action.action == "move":
            # Resolve diagonal proposals into one cardinal step so movement has consistent speed.
            dx, dy = action.dx, action.dy
            if dx and dy:
                dy = 0
            next_x = (agent.x + dx) % world.width
            next_y = min(max(agent.y + dy, 0), world.height - 1)
            cell = self._terrain_at(world, next_x, next_y)
            if cell and cell.kind == "ocean":
                return "The ocean blocked the way; find a land route."
            if (next_x, next_y) == (agent.x, agent.y):
                return "Stayed in place; no movement step was proposed."
            agent.x, agent.y = next_x, next_y
            if cell and cell.kind == "mountain":
                agent.energy = max(0, agent.energy - 3)
            return f"Moved to ({agent.x}, {agent.y})."
        if action.action == "forage":
            food = next((node for node in world.resources if node.kind in FOOD_KINDS and node.x == agent.x and node.y == agent.y and node.quantity > 0), None)
            if not food or food.quantity <= 0:
                return "Looked for food here but found none."
            food.quantity -= 1
            nutrition = {"food": 42, "fruit": 32, "vegetable": 27, "meat": 40, "cooked_meat": 43, "eggs": 30, "milk": 26}.get(food.kind, 30)
            agent.hunger = max(0, agent.hunger - nutrition)
            self._foodborne_risk(world, agent, food)
            # Young dependents are fed when a nearby parent finds food for the family.
            self._share_food_with_dependents(world, agent, food)
            self._remember(agent, "Found food here and ate it.")
            self._learn(agent, "foraging")
            return "Found food and ate."
        if action.action == "drink":
            water = self._resource_at(world, "water", agent.x, agent.y)
            if not water or water.quantity <= 0:
                return "Looked for water here but found none."
            water.quantity -= 1
            agent.thirst = max(0, agent.thirst - 55)
            if water.contamination >= 15 and self._random.random() < min(0.8, water.contamination / 100):
                self._infect(world, agent, "waterborne infection", EventSource.NATURAL)
            self._share_water_with_dependents(world, agent, water)
            self._remember(agent, "Found water here and drank.")
            self._learn(agent, "finding water")
            return "Found water and drank."
        if action.action == "rest":
            agent.energy = min(100, agent.energy + 30)
            if agent.last_rest_recovery_tick != world.tick:
                agent.health = min(100, agent.health + 2)
                agent.last_rest_recovery_tick = world.tick
            return "Rested and recovered some energy."
        if action.action in {"mourn", "bury"}:
            deceased = next((person for person in world.agents
                             if person.id == action.target_agent_id and not person.alive
                             and self._distance_to(agent.x, agent.y, person.x, person.y, world.width) <= 1), None)
            if not deceased:
                return "There was no deceased person nearby to attend to."
            related = self._is_related(agent, deceased)
            if action.action == "mourn":
                self._remember(agent, f"Mourned {deceased.name}, who died from {deceased.death_cause or 'unknown causes'}.")
                if related:
                    self._remember(agent, f"You grieved for your relative {deceased.name}.")
                self._record(world, EventSource.AGENT_ACTION, EventKind.MOURNING,
                             f"{agent.name} mourned {deceased.name}.", [agent.id, deceased.id],
                             {"relative": related, "cause": deceased.death_cause})
                return f"Mourned {deceased.name}."
            if deceased.buried:
                return f"{deceased.name} had already been buried."
            deceased.buried = True
            self._remember(agent, f"Helped bury {deceased.name}.")
            self._record(world, EventSource.AGENT_ACTION, EventKind.BURIAL,
                         f"{agent.name} buried {deceased.name}.", [agent.id, deceased.id],
                         {"relative": related, "cause": deceased.death_cause})
            return f"Buried {deceased.name}."
        if action.action == "gather":
            kind = action.resource_kind or "wood"
            node = self._resource_at(world, kind, agent.x, agent.y)
            if not node or node.quantity <= 0:
                return f"There was no {kind} to gather here."
            node.quantity -= 1
            agent.inventory[kind] = agent.inventory.get(kind, 0) + 1
            cell = self._terrain_at(world, agent.x, agent.y)
            if cell and kind == "wood":
                cell.condition = max(0, cell.condition - 2)
            self._learn(agent, f"gathering {kind}")
            return f"Gathered one unit of {kind}."
        if action.action == "tend_terrain":
            return self._tend_terrain(world, agent)
        if action.action == "hunt":
            return self._hunt(world, agent, action.target_animal_id)
        if action.action == "tame":
            return self._tame(world, agent, action.target_animal_id)
        if action.action == "tend_animal":
            return self._tend_animal(world, agent, action.target_animal_id)
        if action.action == "collect_animal_food":
            return self._collect_animal_food(world, agent, action.target_animal_id)
        if action.action == "plant":
            return self._plant_crop(world, agent, action.crop_kind or "vegetable")
        if action.action == "water_crop":
            plot = next((item for item in world.crops if self._distance_to(item.x, item.y, agent.x, agent.y) <= 1.5), None)
            water = next((node for node in world.resources if node.kind == "water" and node.quantity > 0
                          and self._distance_to(node.x, node.y, agent.x, agent.y) <= 1.5), None)
            if not plot or not water:
                return "Watering needs a growing crop and nearby fresh water."
            water.quantity -= 1
            plot.moisture = min(100, plot.moisture + 35)
            plot.condition = min(100, plot.condition + 4)
            return f"Watered the {plot.crop_kind} crop."
        if action.action == "harvest":
            return self._harvest_crop(world, agent)
        if action.action == "cook":
            return self._cook_meat(world, agent)
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
            if target.last_care_tick != world.tick:
                target.health = min(100, target.health + 4)
                target.energy = min(100, target.energy + 4)
                target.last_care_tick = world.tick
            food = next((node for node in world.resources if node.kind in FOOD_KINDS
                         and node.quantity > 0 and self._distance_to(node.x, node.y, agent.x, agent.y, world.width) <= 1), None)
            water = next((node for node in world.resources if node.kind == "water"
                          and node.quantity > 0 and self._distance_to(node.x, node.y, agent.x, agent.y, world.width) <= 1), None)
            if food and target.hunger > 35:
                food.quantity -= 1
                target.hunger = max(0, target.hunger - 25)
                self._foodborne_risk(world, target, food)
            if water and target.thirst > 35:
                water.quantity -= 1
                target.thirst = max(0, target.thirst - 30)
                if water.contamination >= 15 and self._random.random() < water.contamination / 100:
                    self._infect(world, target, "waterborne infection", EventSource.NATURAL)
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

    def _tend_terrain(self, world: WorldState, agent: Agent) -> str:
        """Local stewardship restores damaged habitat and cleans existing resources."""
        cell = self._terrain_at(world, agent.x, agent.y)
        if not cell or cell.kind == "ocean":
            return "Land care requires standing on land."
        if cell.last_tended_tick == world.tick:
            return "This habitat has already been tended today."
        cell.condition = min(100, cell.condition + 12)
        cell.fertility = min(100, cell.fertility + 8)
        cell.pollution = max(0, cell.pollution - 15)
        cell.last_tended_tick = world.tick
        nearby = [node for node in world.resources if self._distance_to(node.x, node.y, agent.x, agent.y, world.width) <= 1]
        water = next((node for node in nearby if node.kind == "water" and node.quantity > 0), None)
        if water and cell.moisture < 0.7:
            water.quantity -= 1
            cell.moisture = min(1, cell.moisture + 0.08)
        for node in nearby:
            node.contamination = max(0, node.contamination - 18)
        agent.energy = max(0, agent.energy - 4)
        self._learn(agent, "land stewardship")
        self._remember(agent, f"You tended the {cell.kind} and cleaned nearby resources.")
        self._record(world, EventSource.AGENT_ACTION, EventKind.TERRAIN_CARE,
                     f"{agent.name} restored local habitat.", [agent.id], {"x": agent.x, "y": agent.y})
        return f"Restored the {cell.kind.replace('_', ' ')} and cleaned nearby resources."

    def _foodborne_risk(self, world: WorldState, agent: Agent, food: ResourceNode) -> None:
        """Unsafe raw food and contamination can cause distinct foodborne diseases."""
        raw_risk = {"meat": 0.075, "fruit": 0.012, "vegetable": 0.018, "eggs": 0.03, "milk": 0.025}.get(food.kind, 0.008)
        contamination_risk = food.contamination / 100 * 0.75
        if food.kind == "cooked_meat":
            raw_risk = 0
        if self._random.random() < min(0.9, raw_risk + contamination_risk):
            disease = self._random.choice(("food poisoning", "intestinal parasite"))
            was_susceptible = agent.alive and not agent.disease and disease not in agent.immune_to
            self._infect(world, agent, disease, EventSource.NATURAL)
            if was_susceptible:
                self._record(world, EventSource.NATURAL, EventKind.FOODBORNE_ILLNESS,
                         f"{agent.name} became sick after eating unsafe {food.kind.replace('_', ' ')}.",
                         [agent.id], {"disease": disease, "source": "food", "contamination": food.contamination})

    def _hunt(self, world: WorldState, agent: Agent, animal_id: str | None) -> str:
        prey = next((animal for animal in world.animals if animal.id == animal_id and animal.alive), None)
        if not prey or self._distance(agent, prey) > 1:
            return "There was no reachable animal to hunt."
        agent.energy = max(0, agent.energy - 12)
        success = self._random.random() < max(0.16, min(0.92, 0.62 + agent.traits.get("aggression", 0.5) * 0.16 - prey.temperament * 0.35))
        if not success:
            prey.x, prey.y = self._random.choice(self._habitable_neighbors(world, prey.x, prey.y))
            prey.hunger = min(100, prey.hunger + 5)
            self._remember(agent, f"The {prey.species} escaped while you hunted.")
            return f"The {prey.species} escaped."
        prey.health = 0
        prey.alive = False
        meat = ResourceNode(kind="meat", x=prey.x, y=prey.y, quantity=4 if prey.species in {"antelope", "deer", "boar", "goat"} else 2, capacity=6, contamination=70 if prey.disease else 8)
        world.resources.append(meat)
        self._remember(agent, f"You hunted a {prey.species} and found meat.")
        self._learn(agent, "hunting")
        self._record(world, EventSource.AGENT_ACTION, EventKind.ACTION,
                     f"{agent.name} hunted a {prey.species}.", [agent.id],
                     {"action": "hunt", "animal_id": prey.id, "meat_yield": meat.quantity})
        return f"Hunted a {prey.species}; raw meat is available here."

    def _tame(self, world: WorldState, agent: Agent, animal_id: str | None) -> str:
        animal = next((item for item in world.animals if item.id == animal_id and item.alive), None)
        if not animal or animal.animal_type != "wild" or self._distance(agent, animal) > 1:
            return "There was no wild animal close enough to befriend."
        chance = max(0.03, min(0.9, 0.25 + agent.traits.get("cooperation", 0.5) * 0.45 + (1 - animal.temperament) * 0.35))
        if self._random.random() >= chance:
            animal.x, animal.y = self._random.choice(self._habitable_neighbors(world, animal.x, animal.y))
            return f"The {animal.species} was not ready to trust you and moved away."
        animal.animal_type = "domestic" if animal.species in {"goat", "boar", "chicken"} else "pet"
        animal.owner_agent_id = agent.id
        animal.temperament = max(0, animal.temperament - 0.25)
        self._learn(agent, f"animal care:{animal.species}")
        self._remember(agent, f"You befriended a {animal.species}.")
        self._record(world, EventSource.AGENT_ACTION, EventKind.ACTION,
                     f"{agent.name} tamed a {animal.species} as a {animal.animal_type}.",
                     [agent.id], {"action": "tame", "animal_id": animal.id, "animal_type": animal.animal_type})
        return f"The {animal.species} now trusts you as a {animal.animal_type}."

    def _tend_animal(self, world: WorldState, agent: Agent, animal_id: str | None) -> str:
        animal = next((item for item in world.animals if item.id == animal_id and item.alive), None)
        if not animal or animal.animal_type == "wild" or animal.owner_agent_id != agent.id or self._distance(agent, animal) > 1:
            return "No owned domestic animal or pet was close enough to care for."
        food = next((node for node in world.resources if node.kind in FOOD_KINDS and node.quantity > 0
                     and self._distance_to(node.x, node.y, agent.x, agent.y, world.width) <= 1), None)
        water = next((node for node in world.resources if node.kind == "water" and node.quantity > 0
                      and self._distance_to(node.x, node.y, agent.x, agent.y, world.width) <= 1), None)
        if food and animal.hunger > 10:
            food.quantity -= 1
            animal.hunger = max(0, animal.hunger - 28)
        if water and animal.thirst > 10:
            water.quantity -= 1
            animal.thirst = max(0, animal.thirst - 25)
        if animal.last_care_tick != world.tick:
            animal.health = min(100, animal.health + 5)
            animal.last_care_tick = world.tick
        agent.energy = max(0, agent.energy - 2)
        self._record(world, EventSource.AGENT_ACTION, EventKind.CARE,
                     f"{agent.name} cared for their {animal.species}.", [agent.id],
                     {"animal_id": animal.id, "animal_type": animal.animal_type})
        return f"Cared for the {animal.species}."

    def _collect_animal_food(self, world: WorldState, agent: Agent, animal_id: str | None) -> str:
        animal = next((item for item in world.animals if item.id == animal_id and item.alive), None)
        if not animal or animal.animal_type != "domestic" or animal.owner_agent_id != agent.id or self._distance(agent, animal) > 1:
            return "No owned food-producing animal was close enough."
        product_kind = {"chicken": "eggs", "goat": "milk"}.get(animal.species)
        if not product_kind:
            return f"The {animal.species} does not produce collectable food."
        if animal.health < 30 or animal.hunger > 90 or animal.thirst > 90:
            return f"The {animal.species} needs care before it can produce food."
        if animal.last_product_tick == world.tick:
            return f"The {animal.species} has already supplied food today."
        self._add_food_resource(world, product_kind, agent.x, agent.y, 2, contamination=animal.disease and 12 or 0)
        animal.last_product_tick = world.tick
        animal.hunger = min(100, animal.hunger + 3)
        agent.energy = max(0, agent.energy - 2)
        self._record(world, EventSource.AGENT_ACTION, EventKind.ACTION,
                     f"{agent.name} collected {product_kind} from a domestic {animal.species}.", [agent.id],
                     {"action": "collect_animal_food", "animal_id": animal.id, "food": product_kind})
        return f"Collected {product_kind}."

    def _plant_crop(self, world: WorldState, agent: Agent, crop_kind: str) -> str:
        cell = self._terrain_at(world, agent.x, agent.y)
        farm = next((structure for structure in world.structures
                     if structure.kind == "farm" and structure.condition >= 20
                     and self._distance_to(structure.x, structure.y, agent.x, agent.y) <= 1.5), None)
        if world.tech_level < 2 or not farm or not cell or cell.kind not in FARMABLE_TERRAIN:
            return "Planting needs a working nearby farm and suitable farmland."
        if any(plot.x == agent.x and plot.y == agent.y for plot in world.crops):
            return "This farmland already has a growing crop."
        world.crops.append(CropPlot(id=str(uuid4()), crop_kind=crop_kind, x=agent.x, y=agent.y,
                                    planted_by=agent.id, planted_tick=world.tick))
        self._record(world, EventSource.AGENT_ACTION, EventKind.ACTION,
                     f"{agent.name} planted {crop_kind} on the farm.", [agent.id],
                     {"action": "plant", "crop_kind": crop_kind})
        return f"Planted {crop_kind}."

    def _harvest_crop(self, world: WorldState, agent: Agent) -> str:
        plot = next((item for item in world.crops if item.x == agent.x and item.y == agent.y), None)
        if not plot or plot.growth_days < (28 if plot.crop_kind == "vegetable" else 42):
            return "There is no ripe crop here yet."
        if plot.condition <= 0:
            world.crops.remove(plot)
            return "The crop failed before harvest."
        amount = max(2, round(8 * plot.condition / 100))
        self._add_food_resource(world, plot.crop_kind, agent.x, agent.y, amount)
        world.crops.remove(plot)
        self._learn(agent, f"farming:{plot.crop_kind}")
        self._record(world, EventSource.AGENT_ACTION, EventKind.ACTION,
                     f"{agent.name} harvested {amount} {plot.crop_kind}.", [agent.id],
                     {"action": "harvest", "crop_kind": plot.crop_kind, "quantity": amount})
        return f"Harvested {amount} {plot.crop_kind}."

    def _cook_meat(self, world: WorldState, agent: Agent) -> str:
        meat = next((node for node in world.resources if node.kind == "meat" and node.x == agent.x and node.y == agent.y and node.quantity > 0), None)
        fire = next((item for item in world.structures if item.kind == "campfire" and item.condition >= 20 and self._distance_to(item.x, item.y, agent.x, agent.y) <= 1.5), None)
        if not meat or not fire:
            return "Cooking requires raw meat and a usable nearby campfire."
        meat.quantity -= 1
        self._add_food_resource(world, "cooked_meat", agent.x, agent.y, 1, contamination=0)
        self._learn(agent, "cooking")
        self._record(world, EventSource.AGENT_ACTION, EventKind.ACTION,
                     f"{agent.name} cooked meat at a campfire.", [agent.id],
                     {"action": "cook"})
        return "Cooked one portion of meat."

    @staticmethod
    def _add_food_resource(world: WorldState, kind: str, x: int, y: int, quantity: int, contamination: float = 0) -> None:
        existing = next((node for node in world.resources if node.kind == kind and node.x == x and node.y == y), None)
        if existing:
            existing.quantity = min(existing.capacity, existing.quantity + quantity)
            existing.contamination = max(existing.contamination, contamination)
        else:
            world.resources.append(ResourceNode(kind=kind, x=x, y=y, quantity=quantity,
                                                capacity=max(12, quantity), contamination=contamination))

    def _habitable_neighbors(self, world: WorldState, x: int, y: int) -> list[tuple[int, int]]:
        choices = []
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = (x + dx) % world.width, y + dy
            cell = self._terrain_at(world, nx, ny)
            if 0 <= ny < world.height and cell and cell.kind != "ocean":
                choices.append((nx, ny))
        return choices or [(x, y)]

    def _advance_biology(self, world: WorldState, agent: Agent) -> None:
        """Advance body state once per simulated day; all ages use the same hazard rules."""
        agent.age_days += 1
        shelter = self._has_shelter(world, agent)
        exposed = not shelter and world.weather in {"cold", "rain", "wind"}
        # Needs represent daily meals, water and sleep, rather than weeks between survival tasks.
        agent.hunger = min(100, agent.hunger + (14 if agent.age_days < 6 * 365 else 18) + (4 if exposed else 0))
        agent.thirst = min(100, agent.thirst + (18 if agent.age_days < 6 * 365 else 24))
        agent.energy = max(0, agent.energy - (8 if agent.age_days < 6 * 365 else 12))

        # Shelter protects from exposure, but not from direct hazards or disease.
        if exposed:
            agent.energy = max(0, agent.energy - 6)
            if world.weather == "cold":
                agent.health = max(0, agent.health - (0.4 if agent.age_days < 6 * 365 else 0.7))
            elif world.weather == "rain" and agent.disease is None and self._random.random() < 0.002:
                self._infect(world, agent, "respiratory illness", EventSource.NATURAL)

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
            agent.hunger = min(100, agent.hunger + 0.4)
            agent.thirst = min(100, agent.thirst + 0.3)
            if agent.pregnancy_days_remaining <= 0:
                self._give_birth(world, agent)
        if agent.age_days > 45 * 365:
            # Age raises risk gradually; other hazards can still kill at any age.
            daily_age_risk = min(0.002, (agent.age_days - 45 * 365) / (35 * 365 * 12000))
            if self._random.random() < daily_age_risk:
                agent.health = max(0, agent.health - 18)
                self._record(world, EventSource.NATURAL, EventKind.INJURY, f"{agent.name} suffered an age-related health decline.", [agent.id])
        self._check_death(world, agent, "illness or unmet biological needs")

    def _share_food_with_dependents(self, world: WorldState, parent: Agent, node: ResourceNode) -> None:
        """Consume one extra gathered unit to reduce hunger for a nearby child."""
        for child in self._nearby_dependents(world, parent, "hunger"):
            if node.quantity <= 0:
                break
            node.quantity -= 1
            child.hunger = max(0, child.hunger - 28)
            self._foodborne_risk(world, child, node)
            self._remember(child, f"{parent.name} shared food with you.")
            self._record(world, EventSource.AGENT_ACTION, EventKind.CARE,
                         f"{parent.name} fed {child.name}.", [parent.id, child.id], {"care": "food"})

    def _share_water_with_dependents(self, world: WorldState, parent: Agent, node: ResourceNode) -> None:
        """Consume one extra drink so nearby children receive basic care."""
        for child in self._nearby_dependents(world, parent, "thirst"):
            if node.quantity <= 0:
                break
            node.quantity -= 1
            child.thirst = max(0, child.thirst - 35)
            if node.contamination >= 15 and self._random.random() < min(0.8, node.contamination / 100):
                self._infect(world, child, "waterborne infection", EventSource.NATURAL)
            self._remember(child, f"{parent.name} shared water with you.")
            self._record(world, EventSource.AGENT_ACTION, EventKind.CARE,
                         f"{parent.name} gave water to {child.name}.", [parent.id, child.id], {"care": "water"})

    @staticmethod
    def _nearby_dependents(world: WorldState, parent: Agent, need: str) -> list[Agent]:
        child_ids = set(parent.children_ids)
        needs = {"hunger": lambda child: child.hunger, "thirst": lambda child: child.thirst}
        need_value = needs[need]
        return sorted(
            (child for child in world.agents if child.alive and child.id in child_ids
             and child.age_days < ADULT_AGE_DAYS
             and SimulationEngine._distance(parent, child) <= 1 and need_value(child) >= 25),
            key=need_value,
            reverse=True,
        )

    def _give_birth(self, world: WorldState, mother: Agent) -> None:
        father = self._get_agent(mother.other_parent_id) if mother.other_parent_id else None
        if not mother.alive:
            mother.pregnancy_days_remaining = None
            return
        if sum(person.alive for person in world.agents) >= MAX_POPULATION:
            mother.pregnancy_days_remaining = None
            mother.other_parent_id = None
            self._record(world, EventSource.SYSTEM, EventKind.POPULATION_LIMIT, "A birth did not occur because the world reached its population limit.", [mother.id], {"population_limit": MAX_POPULATION})
            return
        father = father if father and father.alive else None
        complicated_birth = bool(
            mother.health < 45 or mother.disease is not None
            or self._random.random() < 0.025
        )
        if complicated_birth:
            mother.health = max(0, mother.health - self._random.randint(12, 28))
            self._check_death(world, mother, "complications during childbirth")
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
            health=self._random.randint(35, 65) if complicated_birth else self._random.randint(65, 100),
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
        self._record(world, EventSource.NATURAL, EventKind.BIRTH, f"{child.name} was born to {', '.join(p.name for p in parents)}.", [child.id, *[p.id for p in parents]], {"sex": sex, "inherited_traits": inherited, "complicated_birth": complicated_birth})

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

    def _advance_ecology(self, world: WorldState) -> None:
        """Advance crops, spoilage, and the needs of wild and cared-for animals."""
        for node in world.resources:
            if node.kind in FOOD_KINDS and node.quantity > 0:
                node.days_old += 1
                spoilage_rate = 0.65 if node.kind in {"meat", "eggs", "milk"} else 0.16
                if node.kind == "cooked_meat":
                    spoilage_rate = 0.12
                node.contamination = min(100, node.contamination + spoilage_rate)
                if node.days_old % 12 == 0 and node.contamination > 75:
                    node.quantity = max(0, node.quantity - 1)
            elif node.kind == "water" and world.weather in {"rain", "flood"} and self._random.random() < 0.005:
                node.contamination = min(100, node.contamination + self._random.uniform(2, 8))

        self._advance_crops(world)
        self._advance_animals(world)
        self._spawn_wildlife(world)
        for cell in world.terrain:
            if cell.kind in FARMABLE_TERRAIN and cell.moisture > 0.2:
                cell.condition = min(100, cell.condition + 0.2)
                cell.fertility = min(100, cell.fertility + 0.1)
        for animal in world.animals:
            if not animal.alive and animal.death_tick is None:
                animal.death_tick = world.tick
        world.animals = [animal for animal in world.animals
                         if animal.alive or world.tick - (animal.death_tick if animal.death_tick is not None else world.tick) < 30]

    def _move_animal_npcs(self, world: WorldState) -> None:
        """Cheap spatial NPC updates run independently of human inference and biological days."""
        for animal in world.animals:
            if not animal.alive or self._random.random() > 0.08:
                continue
            choices = self._habitable_neighbors(world, animal.x, animal.y)
            owner = next((person for person in world.agents if person.id == animal.owner_agent_id and person.alive), None)
            if animal.animal_type == "pet" and owner:
                target = (owner.x, owner.y)
            else:
                needs = [node for node in world.resources if node.quantity > 0
                         and (node.kind == "water" if animal.thirst > 45 else node.kind in FOOD_KINDS)
                         and self._distance_to(node.x, node.y, animal.x, animal.y, world.width) <= 3]
                node = min(needs, key=lambda item: self._distance_to(item.x, item.y, animal.x, animal.y, world.width), default=None)
                target = (node.x, node.y) if node and max(animal.hunger, animal.thirst) > 45 else None
            animal.x, animal.y = min(choices, key=lambda point: self._distance_to(*point, *target, world.width)) if target else self._random.choice(choices)

    def _spawn_wildlife(self, world: WorldState) -> None:
        """Wildlife recolonizes suitable habitat; population follows habitat capacity, not a fixed total."""
        species = {"forest": ("deer", "boar", "dog"), "rainforest": ("chicken", "boar"),
                   "boreal_forest": ("hare", "deer"), "grassland": ("goat", "antelope"),
                   "plains": ("deer", "hare"), "farmland": ("chicken", "goat")}
        occupancy: dict[tuple[int, int], int] = {}
        for animal in world.animals:
            if animal.alive:
                key = (animal.x, animal.y)
                occupancy[key] = occupancy.get(key, 0) + 1
        for cell in world.terrain:
            capacity = max(1, int(cell.condition * cell.fertility / 3500))
            if (cell.kind not in species or cell.condition < 40 or cell.pollution > 60
                or occupancy.get((cell.x, cell.y), 0) >= capacity or self._random.random() > 0.015):
                continue
            animal = Animal(id=str(uuid4()), species=self._random.choice(species[cell.kind]),
                            sex=self._random.choice(("male", "female")), age_days=self._random.randint(100, 700),
                            x=cell.x, y=cell.y, temperament=self._random.uniform(0.1, 0.8))
            world.animals.append(animal)
            self._record(world, EventSource.NATURAL, EventKind.ANIMAL_SPAWNED,
                         f"A wild {animal.species} entered the habitat.", details={"animal_id": animal.id, "x": cell.x, "y": cell.y})

    def _advance_crops(self, world: WorldState) -> None:
        for plot in world.crops:
            cell = self._terrain_at(world, plot.x, plot.y)
            if world.weather == "rain":
                plot.moisture = min(100, plot.moisture + 16)
            elif world.weather == "heat":
                plot.moisture = max(0, plot.moisture - 10)
            else:
                plot.moisture = max(0, plot.moisture - 2)
            if any(node.kind == "water" and node.quantity > 0 and self._distance_to(node.x, node.y, plot.x, plot.y) <= 1.5 for node in world.resources):
                plot.moisture = min(100, plot.moisture + 3)
            if cell and (cell.kind in {"desert", "mountain", "ice"} or cell.fertility < 15 or cell.pollution > 60):
                plot.condition = max(0, plot.condition - 2)
            elif plot.moisture < 12:
                plot.condition = max(0, plot.condition - 4)
            else:
                plot.growth_days += 1 if world.season in {"spring", "summer"} else 0
                if world.weather == "drought":
                    plot.condition = max(0, plot.condition - 3)

    def _advance_animals(self, world: WorldState) -> None:
        """Run deterministic NPC needs, movement, illness, reproduction, and mortality."""
        living = [animal for animal in world.animals if animal.alive]
        for animal in living:
            animal.age_days += 1
            cell = self._terrain_at(world, animal.x, animal.y)
            if animal.animal_type == "wild":
                grazing_biome = cell and cell.kind in {"grassland", "plains", "farmland", "forest", "rainforest", "boreal_forest"}
                animal.hunger = max(0, animal.hunger + (0.2 if grazing_biome else 1.6))
                if animal.hunger > 40:
                    wild_food = next((node for node in world.resources if node.kind in FOOD_KINDS
                                      and node.quantity > 0
                                      and self._distance_to(node.x, node.y, animal.x, animal.y, world.width) <= 1), None)
                    if wild_food:
                        wild_food.quantity -= 1
                        animal.hunger = max(0, animal.hunger - 30)
                        if wild_food.contamination > 35 and self._random.random() < wild_food.contamination / 150:
                            animal.disease = "animal disease"
                            self._record(world, EventSource.NATURAL, EventKind.ANIMAL_DISEASE,
                                         f"A {animal.species} became ill after eating contaminated food.", [],
                                         {"animal_id": animal.id, "species": animal.species,
                                          "food_kind": wild_food.kind})
                if animal.hunger > 45 and self._random.random() < 0.16:
                    options = [
                        (node.x, node.y) for node in world.resources
                        if node.kind in FOOD_KINDS and node.quantity > 0
                        and self._distance_to(node.x, node.y, animal.x, animal.y) <= 2
                    ]
                    if options:
                        animal.x, animal.y = self._random.choice(options)
                elif self._random.random() < 0.12:
                    animal.x, animal.y = self._random.choice(self._habitable_neighbors(world, animal.x, animal.y))
            else:
                owner = next((person for person in world.agents if person.id == animal.owner_agent_id and person.alive), None)
                urgent_need = animal.hunger > 45 or animal.thirst > 35
                if animal.animal_type == "pet" and owner and not urgent_need and self._distance_to(animal.x, animal.y, owner.x, owner.y, world.width) > 1:
                    neighbors = self._habitable_neighbors(world, animal.x, animal.y)
                    animal.x, animal.y = min(neighbors, key=lambda point: self._distance_to(point[0], point[1], owner.x, owner.y, world.width))
                animal.hunger = min(100, animal.hunger + (1.5 if animal.animal_type == "pet" else 0.9))
                # Livestock can graze on suitable land; pets seek edible plants and need agent care.
                if animal.animal_type == "domestic" and cell and cell.kind in {"grassland", "plains", "farmland"}:
                    animal.hunger = max(0, animal.hunger - 5)
                if animal.hunger > 35:
                    edible = next((node for node in world.resources if node.kind in {"fruit", "vegetable", "food"}
                                   and node.quantity > 0
                                   and self._distance_to(node.x, node.y, animal.x, animal.y, world.width) <= 1), None)
                    if edible:
                        edible.quantity -= 1
                        animal.hunger = max(0, animal.hunger - 24)
                    elif animal.hunger > 55:
                        food_sources = [node for node in world.resources if node.kind in {"fruit", "vegetable", "food"}
                                        and node.quantity > 0
                                        and self._distance_to(node.x, node.y, animal.x, animal.y, world.width) <= 3]
                        if food_sources:
                            target = min(food_sources, key=lambda node: self._distance_to(node.x, node.y, animal.x, animal.y, world.width))
                            neighbors = self._habitable_neighbors(world, animal.x, animal.y)
                            animal.x, animal.y = min(neighbors, key=lambda point: self._distance_to(point[0], point[1], target.x, target.y, world.width))
            animal.thirst = min(100, animal.thirst + (1.2 if animal.animal_type != "wild" else 0.7))
            if animal.thirst > 25:
                springs = [node for node in world.resources if node.kind == "water" and node.quantity > 0
                           and self._distance_to(node.x, node.y, animal.x, animal.y, world.width) <= 4]
                spring = min(springs, key=lambda node: self._distance_to(node.x, node.y, animal.x, animal.y, world.width), default=None)
                if spring and self._distance_to(spring.x, spring.y, animal.x, animal.y, world.width) <= 1:
                    spring.quantity -= 1
                    animal.thirst = max(0, animal.thirst - 45)
                elif spring and (animal.animal_type != "pet" or animal.hunger <= 45):
                    neighbors = self._habitable_neighbors(world, animal.x, animal.y)
                    animal.x, animal.y = min(neighbors, key=lambda point: self._distance_to(point[0], point[1], spring.x, spring.y, world.width))
            if animal.hunger > 82:
                animal.health = max(0, animal.health - 1.5)
            if animal.thirst > 82:
                animal.health = max(0, animal.health - 2.5)
            if animal.disease:
                animal.health = max(0, animal.health - 2)
            elif self._random.random() < 0.0006:
                animal.disease = "animal disease"
                animal.health = max(0, animal.health - 4)
                self._record(world, EventSource.NATURAL, EventKind.ANIMAL_DISEASE,
                             f"A {animal.species} developed a natural illness.", [],
                             {"animal_id": animal.id, "species": animal.species})
            if animal.health <= 0:
                animal.alive = False
                self._add_food_resource(world, "meat", animal.x, animal.y, 1,
                                        contamination=75 if animal.disease else 32)
                self._record(world, EventSource.NATURAL, EventKind.DEATH,
                             f"A {animal.species} died from illness or unmet needs.", [],
                             {"animal_id": animal.id, "species": animal.species})
            elif animal.hunger < 45 and self._random.random() < (0.001 if animal.animal_type == "wild" else 0.0006):
                mate = next((other for other in living if other.id != animal.id and other.alive
                             and other.species == animal.species and other.sex != animal.sex
                             and other.animal_type == animal.animal_type
                             and (animal.animal_type == "wild" or other.owner_agent_id == animal.owner_agent_id)
                             and self._distance_to(animal.x, animal.y, other.x, other.y) <= 1), None)
                if mate and sum(item.alive and self._distance_to(item.x, item.y, animal.x, animal.y, world.width) <= 1
                                for item in world.animals) < 6:
                    offspring = Animal(
                        id=str(uuid4()), species=animal.species,
                        animal_type=animal.animal_type, owner_agent_id=animal.owner_agent_id,
                        sex=self._random.choice(("male", "female")), age_days=0,
                        x=animal.x, y=animal.y, hunger=10, temperament=self._random.uniform(0.2, 0.7),
                    )
                    world.animals.append(offspring)
                    self._record(world, EventSource.NATURAL, EventKind.ANIMAL_BIRTH,
                                 f"A {offspring.species} was born.", [],
                                 {"animal_id": offspring.id, "species": offspring.species,
                                  "animal_type": offspring.animal_type,
                                  "parent_ids": [animal.id, mate.id]})

    def _regenerate_resources(self, world: WorldState) -> None:
        if world.tick % 7:
            return
        for node in world.resources:
            if node.kind in {"food", "fruit", "vegetable"}:
                biome = self._terrain_at(world, node.x, node.y)
                growth = (1 if world.season == "winter" else 3) if biome and biome.kind in {"grassland", "plains", "forest", "rainforest", "boreal_forest", "river", "lake"} else 0
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
        """Use local feasible opportunities only when inference fails; never fabricate consent or culture."""
        choices = self._ollama.action_choices(agent, world)
        safe = [action for action in choices if action.action not in {
            "bond", "reproduce", "fight", "create_belief", "form_group", "join_group"
        }]
        if agent.last_action and agent.last_action.action == "communicate":
            safe = [action for action in safe if action.action != "communicate"] or safe
        return safe[0] if safe else AgentAction(action="rest", reason="No safe local opportunity")

    def _prepare_resource_action(self, world: WorldState, agent: Agent, action: AgentAction) -> AgentAction:
        """Turn a resource choice into one sensible step when its target is farther away."""
        resource_kind = {"drink": "water"}.get(action.action)
        food_target = self._nearest_food(world, agent) if action.action == "forage" else None
        if action.action == "gather":
            resource_kind = action.resource_kind or "wood"
        if action.action == "forage":
            if not food_target or (food_target.x == agent.x and food_target.y == agent.y):
                return action
            return self._move_or_act(world, agent, food_target, "forage", "Move toward an edible resource")
        if not resource_kind:
            return action
        local_resource = self._resource_at(world, resource_kind, agent.x, agent.y)
        if local_resource and local_resource.quantity > 0:
            return action
        # The engine may only route toward a resource that this person can currently observe.
        target = self._nearest_resource(world, resource_kind, agent)
        if not target:
            return action
        return self._move_or_act(
            world,
            agent,
            target,
            action.action,
            f"The model chose to {action.action}; move toward nearby {resource_kind} first",
            resource_kind if action.action == "gather" else None,
        )

    def _prepare_corpse_action(self, world: WorldState, agent: Agent, action: AgentAction) -> AgentAction:
        """Route agents toward a nearby body before they mourn or bury the deceased."""
        if action.action not in {"mourn", "bury"}:
            return action
        deceased = next((person for person in world.agents if person.id == action.target_agent_id
                         and not person.alive and (action.action == "mourn" or not person.buried)), None)
        if not deceased or self._distance(agent, deceased) <= 1:
            return action
        return self._move_or_act(world, agent, deceased, action.action,
                                 f"Approach {deceased.name}'s body to {action.action}")

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
            owner_agent_id=agent.id,
            group_id=next((group.id for group in world.groups if agent.id in group.member_ids), None),
            built_at_tick=world.tick,
        )
        world.structures.append(structure)
        self._learn(agent, f"building:{kind}")
        old_level = world.tech_level
        world.tech_level = max(old_level, min(3, len(world.structures) // 2))
        if world.tech_level > old_level:
            self._record(world, EventSource.AGENT_ACTION, EventKind.DISCOVERY, f"The community developed new building knowledge (level {world.tech_level}).", [agent.id])
        # A farm provides a place to cultivate. Food comes from planting, growth and harvesting.
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
        for person, new_partner in ((first, second), (second, first)):
            old_partner = next((agent for agent in world.agents if agent.id == person.bonded_partner_id), None)
            if old_partner and old_partner.id != new_partner.id:
                old_partner.bonded_partner_id = None
                self._adjust_relationship(person, old_partner, -15)
                self._record(world, EventSource.AGENT_ACTION, EventKind.RELATIONSHIP,
                             f"{person.name} ended a previous bond with {old_partner.name}.", [person.id, old_partner.id])
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
        elif sum(person.alive for person in world.agents) >= MAX_POPULATION:
            result = f"The world has reached its population limit of {MAX_POPULATION}."
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
                if hazard in {"storm", "flood"} and self._has_shelter(world, agent):
                    impact = max(1, round(impact * 0.45))
                agent.health = max(0, agent.health - impact)
                affected.append(agent.id)
                self._check_death(world, agent, hazard, source)
        return affected

    def _apply_hazard_to_resources(self, world: WorldState, x: int, y: int, radius: float, hazard: str) -> None:
        """Spread environmental damage to habitat, food, materials, and buildings."""
        for cell in world.terrain:
            distance = self._distance_to(cell.x, cell.y, x, y, world.width)
            if cell.kind == "ocean" or distance > radius:
                continue
            impact = max(0.1, 1 - distance / radius)
            cell.condition = max(0, cell.condition - impact * (35 if hazard == "wildfire" else 15))
            cell.fertility = max(0, cell.fertility - impact * 8)
            if hazard in {"wildfire", "flood"}:
                cell.pollution = min(100, cell.pollution + impact * 18)
        for node in world.resources:
            distance = self._distance_to(node.x, node.y, x, y)
            if distance > radius:
                continue
            falloff = max(0.12, 1 - distance / radius)
            if hazard in {"wildfire", "drought"} and node.kind in FOOD_KINDS:
                node.quantity = max(0, node.quantity - math.ceil(node.quantity * falloff))
            elif hazard == "wildfire" and node.kind == "wood":
                node.quantity = max(0, node.quantity - math.ceil(node.quantity * falloff * 0.65))
            elif hazard == "flood" and node.kind in FOOD_KINDS:
                node.quantity = max(0, node.quantity - math.ceil(node.quantity * falloff * 0.35))
                node.contamination = min(100, node.contamination + 35 * falloff)
            elif hazard == "flood" and node.kind == "water":
                node.contamination = min(100, node.contamination + 24 * falloff)
            elif hazard == "wildfire" and node.kind in FOOD_KINDS:
                node.contamination = min(100, node.contamination + 18 * falloff)
        for structure in world.structures:
            distance = self._distance_to(structure.x, structure.y, x, y)
            if distance > radius:
                continue
            falloff = max(0.12, 1 - distance / radius)
            vulnerability = 0.7 if structure.kind in {"lean_to", "hut"} else 0.4
            if hazard in {"wildfire", "storm", "flood"}:
                structure.condition = max(0, structure.condition - 100 * falloff * vulnerability)
        for animal in world.animals:
            if not animal.alive:
                continue
            distance = self._distance_to(animal.x, animal.y, x, y, world.width)
            if distance > radius:
                continue
            falloff = max(0.18, 1 - distance / radius * 0.78)
            animal_damage = {"wildfire": 28, "storm": 10, "flood": 22, "drought": 7}.get(hazard, 8)
            animal.health = max(0, animal.health - animal_damage * falloff)
            if animal.health <= 0:
                animal.alive = False
                self._add_food_resource(world, "meat", animal.x, animal.y, 1,
                                        contamination=75 if animal.disease else 38)
        for plot in world.crops:
            if self._distance_to(plot.x, plot.y, x, y, world.width) > radius:
                continue
            if hazard == "flood":
                plot.moisture = min(100, plot.moisture + 50)
                plot.condition = max(0, plot.condition - 15)
            elif hazard == "drought":
                plot.moisture = max(0, plot.moisture - 50)
                plot.condition = max(0, plot.condition - 25)
            elif hazard == "wildfire":
                plot.condition = 0

    @staticmethod
    def _has_shelter(world: WorldState, agent: Agent) -> bool:
        """A nearby usable roof protects from exposure and some weather damage."""
        return any(
            structure.kind in SHELTER_KINDS
            and structure.condition >= 20
            and SimulationEngine._distance_to(agent.x, agent.y, structure.x, structure.y) <= 1.5
            for structure in world.structures
        )

    def _check_death(self, world: WorldState, agent: Agent, cause: str, source: EventSource = EventSource.NATURAL) -> None:
        if agent.alive and agent.health <= 0:
            agent.alive = False
            agent.death_cause = cause
            related_people = [person for person in world.agents if person.alive and self._is_related(person, agent)]
            for relative in related_people:
                self._remember(relative, f"{agent.name}, your relative, died from {cause}. Their body remains nearby.")
            self._record(world, source, EventKind.DEATH, f"{agent.name} died at age {agent.age_years} from {cause}.", [agent.id], {"age_years": agent.age_years, "cause": cause})
            # Keep a group's leadership attached to living members after a death.
            for group in world.groups:
                if group.leader_agent_id == agent.id:
                    candidates = [member for member in world.agents if member.alive and member.id in group.member_ids]
                    if candidates:
                        group.leader_agent_id = max(
                            candidates,
                            key=lambda member: member.traits.get("sociability", 0.5),
                        ).id

    @staticmethod
    def _is_related(first: Agent, second: Agent) -> bool:
        """Recognize close family ties from lineage, a mutual bond, or a strong relationship."""
        return (
            second.id in first.parent_ids
            or second.id in first.children_ids
            or first.id in second.parent_ids
            or first.id in second.children_ids
            or first.bonded_partner_id == second.id
            or second.bonded_partner_id == first.id
            or first.relationship_scores.get(second.id, 0) >= 40
            or second.relationship_scores.get(first.id, 0) >= 40
        )

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
        horizontal = abs(first.x - second.x)
        horizontal = min(horizontal, max(0, 36 - horizontal))
        return horizontal + abs(first.y - second.y)

    @staticmethod
    def _distance_to(x1: int, y1: int, x2: int, y2: int, world_width: int = 36) -> float:
        # Longitude wraps around the spherical world; latitude does not wrap at the poles.
        horizontal = abs(x1 - x2)
        horizontal = min(horizontal, max(0, world_width - horizontal))
        return math.hypot(horizontal, y1 - y2)

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
        return self._reachable_local_resource(world, agent, {kind})

    def _nearest_food(self, world: WorldState, agent: Agent) -> ResourceNode | None:
        return self._reachable_local_resource(world, agent, FOOD_KINDS)

    def _reachable_local_resource(self, world: WorldState, agent: Agent, kinds: set[str]) -> ResourceNode | None:
        # Navigation must not reveal food on an unseen continent or loop against an ocean barrier.
        options = [node for node in world.resources if node.kind in kinds and node.quantity > 0
                   and OllamaClient._distance(agent.x, agent.y, node.x, node.y, world.width) <= 5]
        options.sort(key=lambda node: (self._distance_to(agent.x, agent.y, node.x, node.y, world.width), node.contamination))
        return next((node for node in options if self._move_or_act(
            world, agent, node, "gather", "Navigate to a visible resource").action != "rest"), None)

    def _move_or_act(
        self,
        world: WorldState,
        agent: Agent,
        node: ResourceNode,
        action: str,
        reason: str,
        resource_kind: str | None = None,
    ) -> AgentAction:
        start = (agent.x, agent.y)
        goal = (node.x, node.y)
        if start == goal:
            return AgentAction(action=action, reason=reason, resource_kind=resource_kind)
        # Breadth-first pathfinding follows habitable spherical cells and routes around oceans.
        queue = [start]
        previous: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
        for current in queue:
            if current == goal:
                break
            x, y = current
            for neighbor in (((x + 1) % world.width, y), ((x - 1) % world.width, y),
                             (x, y + 1), (x, y - 1)):
                nx, ny = neighbor
                if not (0 <= ny < world.height) or neighbor in previous:
                    continue
                terrain = self._terrain_at(world, nx, ny)
                if terrain and terrain.kind == "ocean":
                    continue
                previous[neighbor] = current
                queue.append(neighbor)
        if goal not in previous:
            return AgentAction(action="rest", reason="The target is separated by impassable ocean.")
        step = goal
        while previous[step] != start:
            step = previous[step]
            if step is None:
                return AgentAction(action="rest", reason="No safe route was found.")
        dx = (step[0] - start[0] + world.width // 2) % world.width - world.width // 2
        dy = step[1] - start[1]
        return AgentAction(action="move", dx=max(-1, min(1, dx)), dy=max(-1, min(1, dy)),
                           reason=reason, resource_kind=resource_kind)

    @staticmethod
    def _record_action(
        world: WorldState,
        agent: Agent,
        action: AgentAction,
        result: str,
        proposed_action: AgentAction | None = None,
    ) -> None:
        agent.last_action = action
        agent.last_result = result
        place = f"{agent.x}:{agent.y}"
        if place not in agent.visited_cells:
            agent.visited_cells.append(place)
            agent.visited_cells = agent.visited_cells[-128:]
        details: dict[str, object] = {"action": action.action, "reason": action.reason, "result": result,
                                     "decision_source": agent.decision_source, "intention_source": agent.intention_source,
                                     "x": agent.x, "y": agent.y}
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
        self._store.save(self.state, self._random.getstate())

    @staticmethod
    def _tuple_tree(value: object) -> object:
        """Restore tuple nesting lost when Python's PRNG state passes through JSON."""
        if isinstance(value, list):
            return tuple(SimulationEngine._tuple_tree(item) for item in value)
        return value


engine = SimulationEngine()
