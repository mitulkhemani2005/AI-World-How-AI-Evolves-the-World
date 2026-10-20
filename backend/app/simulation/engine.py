from __future__ import annotations

import asyncio
import random
from uuid import uuid4

from app.agent_brain.ollama_client import OllamaClient, OllamaError
from app.domain import (
    Agent,
    AgentAction,
    EventKind,
    EventSource,
    ResourceNode,
    SpectatorEventRequest,
    WorldEvent,
    WorldState,
)
from app.settings import settings


class SimulationEngine:
    """Small in-memory world. One tick represents one simulated day."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._random = random.Random(7)
        self._ollama = OllamaClient()
        self._runner_task: asyncio.Task[None] | None = None
        self._tick_interval_seconds = 3.0
        self.state = self._new_world(seed=7)

    def _new_world(self, seed: int) -> WorldState:
        self._random.seed(seed)
        world_id = str(uuid4())
        state = WorldState(
            id=world_id,
            seed=seed,
            agents=[
                Agent(id="agent-1", name="Aru", sex="male", x=2, y=3, model=settings.ollama_model),
                Agent(id="agent-2", name="Nima", sex="female", x=3, y=3, model=settings.ollama_model),
            ],
            resources=[
                ResourceNode(kind="food", x=2, y=4, quantity=18, capacity=24),
                ResourceNode(kind="food", x=8, y=3, quantity=18, capacity=24),
                ResourceNode(kind="water", x=6, y=3, quantity=30, capacity=40),
                ResourceNode(kind="shelter", x=4, y=6, quantity=1, capacity=1),
            ],
        )
        self._record(
            state,
            EventSource.SYSTEM,
            EventKind.WORLD_STARTED,
            "A new world began with two independent agents.",
        )
        return state

    async def reset(self, seed: int = 7) -> WorldState:
        async with self._lock:
            self.state.running = False
            self.state = self._new_world(seed)
            return self.state.model_copy(deep=True)

    async def snapshot(self) -> WorldState:
        async with self._lock:
            return self.state.model_copy(deep=True)

    async def tick(self) -> WorldState:
        async with self._lock:
            state = self.state
            state.tick += 1
            self._regenerate_resources(state)
            self._natural_events(state)

            for agent in state.agents:
                if not agent.alive:
                    continue
                try:
                    action = await self._ollama.decide(agent, state)
                except OllamaError as exc:
                    action = self._fallback_action(agent, state)
                    self._record(
                        state,
                        EventSource.SYSTEM,
                        EventKind.FALLBACK_DECISION,
                        f"{agent.name}'s local model was unavailable or returned an invalid action; a basic survival rule chose instead.",
                        [agent.id],
                        {"error": str(exc)[:240], "fallback_action": action.action},
                    )
                agent.last_action = action
                self._apply_action(state, agent, action)

            for agent in state.agents:
                if agent.alive:
                    self._advance_biology(state, agent)

            state.events = state.events[-settings.max_saved_events :]
            return state.model_copy(deep=True)

    async def start(self, interval_seconds: float = 3.0) -> WorldState:
        async with self._lock:
            self._tick_interval_seconds = min(max(interval_seconds, 0.5), 60.0)
            self.state.running = True
            if self._runner_task is None or self._runner_task.done():
                self._runner_task = asyncio.create_task(self._run_loop())
            return self.state.model_copy(deep=True)

    async def pause(self) -> WorldState:
        async with self._lock:
            self.state.running = False
            return self.state.model_copy(deep=True)

    async def _run_loop(self) -> None:
        while True:
            await asyncio.sleep(self._tick_interval_seconds)
            async with self._lock:
                if not self.state.running:
                    self._runner_task = None
                    return
            await self.tick()

    async def change_model(self, agent_id: str, model: str) -> Agent:
        async with self._lock:
            agent = self._get_agent(agent_id)
            old_model = agent.model
            model = model.strip()
            if not model:
                raise ValueError("Model name cannot be empty")
            agent.model = model
            agent.memories.append(f"Simulation note: assigned model changed from {old_model} to {agent.model}.")
            self._record(
                self.state,
                EventSource.SPECTATOR,
                EventKind.MODEL_CHANGED,
                f"The spectator changed {agent.name}'s model.",
                [agent.id],
                {"old_model": old_model, "new_model": agent.model},
            )
            return agent.model_copy(deep=True)

    async def inject_event(self, request: SpectatorEventRequest) -> WorldState:
        async with self._lock:
            state = self.state
            agent = self._get_agent(request.target_agent_id) if request.target_agent_id else None
            x = request.x if request.x is not None else (agent.x if agent else state.width // 2)
            y = request.y if request.y is not None else (agent.y if agent else state.height // 2)
            x = min(max(x, 0), state.width - 1)
            y = min(max(y, 0), state.height - 1)
            affected: list[str] = []

            if request.kind == "injury":
                targets = [agent] if agent else [a for a in state.agents if a.alive]
                for target in targets:
                    if target and target.alive:
                        target.health = max(0, target.health - 25)
                        affected.append(target.id)
                        self._check_death(state, target, "an injury", EventSource.SPECTATOR)
            elif request.kind == "disease_outbreak":
                targets = [a for a in state.agents if a.alive and abs(a.x - x) + abs(a.y - y) <= 4]
                for target in targets:
                    self._infect(state, target, "fever", EventSource.SPECTATOR)
                    affected.append(target.id)
            elif request.kind == "wildfire":
                affected = self._hazard_damage(
                    state, x, y, radius=2, damage=30, hazard="wildfire", source=EventSource.SPECTATOR
                )
                for node in state.resources:
                    if node.kind == "food" and abs(node.x - x) + abs(node.y - y) <= 2:
                        node.quantity = 0
            elif request.kind == "storm":
                affected = self._hazard_damage(
                    state, x, y, radius=3, damage=12, hazard="storm", source=EventSource.SPECTATOR
                )

            self._record(
                state,
                EventSource.SPECTATOR,
                EventKind.SPECTATOR_EVENT,
                f"The spectator triggered a {request.kind.replace('_', ' ')}.",
                affected,
                {"event": request.kind, "x": x, "y": y},
            )
            return state.model_copy(deep=True)

    def _apply_action(self, state: WorldState, agent: Agent, action: AgentAction) -> None:
        source = EventSource.AGENT_ACTION
        message = f"{agent.name} chose to {action.action}."
        details: dict[str, object] = {"action": action.action, "reason": action.reason}

        if action.action == "move":
            old = {"x": agent.x, "y": agent.y}
            agent.x = min(max(agent.x + action.dx, 0), state.width - 1)
            agent.y = min(max(agent.y + action.dy, 0), state.height - 1)
            details["from"] = old
            details["to"] = {"x": agent.x, "y": agent.y}
        elif action.action == "forage":
            food = self._resource_at(state, "food", agent.x, agent.y)
            if food and food.quantity > 0:
                food.quantity -= 1
                agent.hunger = max(0, agent.hunger - 42)
                agent.memories.append("Found food here and ate it.")
                message = f"{agent.name} found food and ate."
            else:
                agent.memories.append("Looked for food here but found none.")
                message = f"{agent.name} searched for food but found none."
        elif action.action == "drink":
            water = self._resource_at(state, "water", agent.x, agent.y)
            if water and water.quantity > 0:
                water.quantity -= 1
                agent.thirst = max(0, agent.thirst - 55)
                agent.memories.append("Found water here and drank.")
                message = f"{agent.name} drank water."
            else:
                agent.memories.append("Looked for water here but found none.")
                message = f"{agent.name} searched for water but found none."
        elif action.action == "rest":
            agent.energy = min(100, agent.energy + 30)
            agent.health = min(100, agent.health + 2)
            message = f"{agent.name} rested."
        elif action.action == "communicate":
            target = next(
                (a for a in state.agents if a.id == action.target_agent_id and a.alive),
                None,
            )
            if target and abs(target.x - agent.x) + abs(target.y - agent.y) <= 2 and action.message:
                target.memories.append(f"{agent.name} said: {action.message}")
                agent.memories.append(f"Told {target.name}: {action.message}")
                message = f"{agent.name} shared an idea with {target.name}: {action.message}"
                self._record(state, source, EventKind.AGENT_SPOKE, message, [agent.id, target.id])
        elif action.action == "help":
            target = next(
                (a for a in state.agents if a.id == action.target_agent_id and a.alive),
                None,
            )
            if target and abs(target.x - agent.x) + abs(target.y - agent.y) <= 1:
                target.health = min(100, target.health + 8)
                target.memories.append(f"{agent.name} helped you.")
                message = f"{agent.name} helped {target.name}."

        self._record(state, source, EventKind.ACTION, message, [agent.id], details)

    def _advance_biology(self, state: WorldState, agent: Agent) -> None:
        agent.age_days += 1
        agent.hunger = min(100, agent.hunger + 1.4)
        agent.thirst = min(100, agent.thirst + 2.0)
        agent.energy = max(0, agent.energy - 1.0)

        if agent.hunger >= 85:
            agent.health = max(0, agent.health - 2.0)
        if agent.thirst >= 85:
            agent.health = max(0, agent.health - 4.0)
        if agent.energy <= 5:
            agent.health = max(0, agent.health - 1.0)

        if agent.disease:
            agent.health = max(0, agent.health - 2.5)
            agent.disease_days += 1
            if agent.disease_days >= 5 and self._random.random() < 0.35:
                disease = agent.disease
                agent.disease = None
                agent.disease_days = 0
                agent.immune_to.append(disease)
                self._record(
                    state,
                    EventSource.NATURAL,
                    EventKind.DISEASE_RECOVERED,
                    f"{agent.name} recovered from {disease} and may have some immunity.",
                    [agent.id],
                )
            elif agent.disease:
                for other in state.agents:
                    if (
                        other.alive
                        and other.id != agent.id
                        and not other.disease
                        and abs(other.x - agent.x) + abs(other.y - agent.y) <= 1
                        and self._random.random() < 0.08
                    ):
                        self._infect(state, other, agent.disease, EventSource.NATURAL)

        if agent.age_days > 45 * 365:
            age_risk = min(0.02, (agent.age_days - 45 * 365) / (35 * 365 * 1000))
            if self._random.random() < age_risk:
                agent.health = max(0, agent.health - 25)
                self._record(
                    state,
                    EventSource.NATURAL,
                    EventKind.INJURY,
                    f"{agent.name} suffered an age-related health decline.",
                    [agent.id],
                )

        self._check_death(state, agent, "illness or unmet biological needs")

    def _natural_events(self, state: WorldState) -> None:
        if self._random.random() < settings.natural_event_probability:
            living = [a for a in state.agents if a.alive]
            if living:
                agent = self._random.choice(living)
                damage = self._random.randint(4, 16)
                agent.health = max(0, agent.health - damage)
                self._record(
                    state,
                    EventSource.NATURAL,
                    EventKind.NATURAL_EVENT,
                    f"A natural mishap injured {agent.name}.",
                    [agent.id],
                    {"damage": damage},
                )
                self._check_death(state, agent, "a natural mishap")

        if self._random.random() < settings.disease_emergence_probability:
            susceptible = [a for a in state.agents if a.alive and not a.disease and "fever" not in a.immune_to]
            if susceptible:
                self._infect(state, self._random.choice(susceptible), "fever", EventSource.NATURAL)

    def _regenerate_resources(self, state: WorldState) -> None:
        if state.tick % 7 != 0:
            return
        for node in state.resources:
            if node.kind == "food":
                node.quantity = min(node.capacity, node.quantity + 2)
            elif node.kind == "water":
                node.quantity = min(node.capacity, node.quantity + 4)

    def _fallback_action(self, agent: Agent, state: WorldState) -> AgentAction:
        if agent.thirst >= 55:
            target = self._nearest_resource(state, "water", agent)
            if target:
                return self._move_or_act(agent, target, "drink", "Find water")
        if agent.hunger >= 50:
            target = self._nearest_resource(state, "food", agent)
            if target:
                return self._move_or_act(agent, target, "forage", "Find food")
        if agent.energy < 40 or agent.health < 55:
            return AgentAction(action="rest", reason="Recover energy and health")
        return AgentAction(action="rest", reason="No urgent need")

    @staticmethod
    def _move_or_act(agent: Agent, node: ResourceNode, action: str, reason: str) -> AgentAction:
        dx = 0 if node.x == agent.x else (1 if node.x > agent.x else -1)
        dy = 0 if node.y == agent.y else (1 if node.y > agent.y else -1)
        if dx == 0 and dy == 0:
            return AgentAction(action=action, reason=reason)
        return AgentAction(action="move", dx=dx, dy=dy, reason=reason)

    def _nearest_resource(self, state: WorldState, kind: str, agent: Agent) -> ResourceNode | None:
        options = [r for r in state.resources if r.kind == kind and r.quantity > 0]
        return min(options, key=lambda r: abs(r.x - agent.x) + abs(r.y - agent.y), default=None)

    @staticmethod
    def _resource_at(state: WorldState, kind: str, x: int, y: int) -> ResourceNode | None:
        return next((r for r in state.resources if r.kind == kind and r.x == x and r.y == y), None)

    def _infect(self, state: WorldState, agent: Agent, disease: str, source: EventSource) -> None:
        if not agent.alive or agent.disease or disease in agent.immune_to:
            return
        agent.disease = disease
        agent.disease_days = 0
        agent.memories.append(f"You began to feel sick with {disease}.")
        self._record(
            state,
            source,
            EventKind.DISEASE_STARTED,
            f"{agent.name} became ill with {disease}.",
            [agent.id],
            {"disease": disease},
        )

    def _hazard_damage(
        self,
        state: WorldState,
        x: int,
        y: int,
        radius: int,
        damage: int,
        hazard: str,
        source: EventSource,
    ) -> list[str]:
        affected: list[str] = []
        for agent in state.agents:
            if agent.alive and abs(agent.x - x) + abs(agent.y - y) <= radius:
                agent.health = max(0, agent.health - damage)
                affected.append(agent.id)
                self._check_death(state, agent, hazard, source)
        return affected

    def _check_death(
        self,
        state: WorldState,
        agent: Agent,
        cause: str,
        source: EventSource = EventSource.NATURAL,
    ) -> None:
        if agent.alive and agent.health <= 0:
            agent.alive = False
            self._record(
                state,
                source,
                EventKind.DEATH,
                f"{agent.name} died at age {agent.age_years} from {cause}.",
                [agent.id],
                {"age_years": agent.age_years, "cause": cause},
            )

    def _get_agent(self, agent_id: str | None) -> Agent:
        agent = next((a for a in self.state.agents if a.id == agent_id), None)
        if agent is None:
            raise KeyError(f"Unknown agent: {agent_id}")
        return agent

    @staticmethod
    def _record(
        state: WorldState,
        source: EventSource,
        kind: EventKind,
        message: str,
        agent_ids: list[str] | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        state.events.append(
            WorldEvent(
                id=str(uuid4()),
                tick=state.tick,
                source=source,
                kind=kind,
                message=message,
                agent_ids=agent_ids or [],
                details=details or {},
            )
        )


engine = SimulationEngine()
