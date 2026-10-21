"""Regressions for observed failures; every test uses an isolated temporary world database."""

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

# Importing the engine creates the application singleton; never point that at a spectator's world.
_isolated = tempfile.TemporaryDirectory(prefix="ai-world-tests-")
os.environ["AI_WORLD_DATABASE"] = str(Path(_isolated.name) / "singleton.sqlite3")

from app.agent_brain.ollama_client import OllamaClient, OllamaError
from app.domain import Agent, AgentAction, Animal, EventKind, EventSource, ResourceNode
from app.simulation.engine import SimulationEngine


class WorldTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="ai-world-case-")
        self.engine = SimulationEngine(str(Path(self.directory.name) / "world.sqlite3"))
        world = self.engine.state
        # A fully observable habitat makes material and caregiving assertions deterministic.
        for cell in world.terrain:
            cell.kind = "grassland"
            cell.moisture = 0.5
        for person in world.agents:
            person.x, person.y = 17, 8
        world.animals = []
        world.resources = [ResourceNode(kind=kind, x=17, y=8, quantity=30, capacity=40)
                           for kind in ("wood", "stone", "water", "fruit")]

    async def asyncTearDown(self):
        await self.engine.pause()
        tasks = [task for task in (self.engine._runner_task, self.engine._clock_task) if task]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.directory.cleanup()

    async def test_fallback_constructs_shelter_without_advancing_age_or_conjuring_materials(self):
        async def unavailable(*_):
            raise OllamaError("offline")

        self.engine._ollama.decide = unavailable
        world = self.engine.state
        starting_age = world.agents[0].age_days
        for _ in range(5):
            await self.engine._tick_once()
        self.assertTrue(any(structure.kind == "lean_to" for structure in world.structures))
        self.assertEqual(world.tick, 0)
        self.assertEqual(world.agents[0].age_days, starting_age)
        self.assertIn(world.agents[0].decision_source, {"fallback", "continuation"})
        self.assertEqual(world.agents[0].intention_source, "fallback")
        wood = next(node for node in world.resources if node.kind == "wood")
        spent = sum(2 if structure.kind == "lean_to" else 2 if structure.kind == "campfire" else 4
                    for structure in world.structures)
        self.assertEqual(wood.quantity + sum(person.inventory.get("wood", 0) for person in world.agents) + spent, 30)

    async def test_model_proposal_is_not_silently_replaced_by_shelter_policy(self):
        async def decide(*_):
            return AgentAction(action="rest", reason="My own decision")

        self.engine._ollama.decide = decide
        await self.engine._tick_once()
        self.assertEqual(self.engine.state.agents[0].last_action.action, "rest")
        self.assertEqual(self.engine.state.agents[0].decision_source, "llm")

    async def test_survival_needs_match_one_minute_biological_days(self):
        world = self.engine.state
        person = world.agents[0]
        person.hunger, person.thirst, person.energy = 10, 10, 75
        world.month_length_seconds = 60
        self.engine._advance_biology(world, person)

        self.assertEqual(person.hunger, 28)
        self.assertEqual(person.thirst, 34)
        self.assertEqual(person.energy, 63)
        self.assertTrue(person.alive)

    async def test_clock_advances_while_model_is_waiting(self):
        gate = asyncio.Event()

        async def delayed(*_):
            await gate.wait()
            return AgentAction(action="rest")

        self.engine._ollama.decide = delayed
        self.engine.state.month_length_seconds = 1
        starting_age = self.engine.state.agents[0].age_days
        await self.engine.start(0.5)
        try:
            await asyncio.sleep(1.6)
            snapshot = await self.engine.snapshot()
            self.assertTrue(snapshot.processing, "inference is still waiting")
            self.assertGreaterEqual(snapshot.tick, 1)
            self.assertGreater(snapshot.agents[0].age_days, starting_age)
        finally:
            gate.set()

    async def test_pause_discards_late_model_result(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed(*_):
            entered.set()
            await release.wait()
            return AgentAction(action="move", dx=1)
        self.engine._ollama.decide = delayed
        before = [(person.x, person.y) for person in self.engine.state.agents]
        round_task = asyncio.create_task(self.engine._tick_once())
        await entered.wait()
        await self.engine.pause()
        release.set()
        await round_task
        self.assertEqual(before, [(person.x, person.y) for person in self.engine.state.agents])
        self.assertFalse(self.engine.state.processing)

    async def test_small_model_contract_uses_numbered_choices_and_validates_response(self):
        original_client = httpx.AsyncClient
        captured = []
        choice = next(index for index, action in enumerate(OllamaClient.action_choices(
            self.engine.state.agents[0], self.engine.state)) if action.action == "gather")

        def respond(request):
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={"message": {"content": json.dumps({"choice": choice, "reason": "Build shelter"})}})

        with patch("app.agent_brain.ollama_client.httpx.AsyncClient", side_effect=lambda **kwargs:
                   original_client(transport=httpx.MockTransport(respond), **kwargs)):
            action = await OllamaClient().decide(self.engine.state.agents[0], self.engine.state)
        self.assertEqual(action.action, "gather")
        self.assertEqual(action.resource_kind, "wood")
        self.assertEqual(captured[0]["model"], "qwen2.5:0.5b")
        self.assertEqual(captured[0]["options"]["num_gpu"], 999)
        self.assertGreaterEqual(captured[0]["options"]["num_predict"], 128)
        self.assertNotIn("target_agent_id", captured[0]["format"]["properties"])

    async def test_choices_have_no_zero_moves_and_children_cannot_perform_adult_actions(self):
        agent = self.engine.state.agents[0]
        for action in OllamaClient.action_choices(agent, self.engine.state):
            if action.action == "move":
                self.assertEqual(abs(action.dx) + abs(action.dy), 1)
        agent.age_days = 5 * 365
        forbidden = {"build", "bond", "reproduce", "hunt", "tame", "fight", "form_group"}
        self.assertFalse(any(action.action in forbidden for action in OllamaClient.action_choices(agent, self.engine.state)))

    async def test_livestock_food_has_daily_limit_and_does_not_access_nonexistent_energy(self):
        world = self.engine.state
        owner = world.agents[0]
        animal = Animal(id="goat", species="goat", animal_type="domestic", owner_agent_id=owner.id,
                        sex="female", x=owner.x, y=owner.y)
        world.animals = [animal]
        self.assertIn("Collected milk", self.engine._collect_animal_food(world, owner, animal.id))
        self.assertIn("already supplied", self.engine._collect_animal_food(world, owner, animal.id))
        self.assertEqual(sum(node.quantity for node in world.resources if node.kind == "milk"), 2)

    async def test_care_requires_real_food_and_water_to_reduce_needs(self):
        world = self.engine.state
        carer, child = world.agents
        child.age_days, child.hunger, child.thirst = 100, 80, 80
        world.resources = []
        self.engine._apply_action(world, carer, AgentAction(action="help", target_agent_id=child.id))
        self.assertEqual((child.hunger, child.thirst), (80, 80))
        world.resources = [ResourceNode(kind=kind, x=carer.x, y=carer.y, quantity=1, capacity=1)
                           for kind in ("fruit", "water")]
        self.engine._apply_action(world, carer, AgentAction(action="help", target_agent_id=child.id))
        self.assertLess(child.hunger, 80)
        self.assertLess(child.thirst, 80)
        self.assertTrue(all(node.quantity == 0 for node in world.resources))

    async def test_teaching_requires_knowledge_and_death_leaves_body_until_burial(self):
        world = self.engine.state
        teacher, learner = world.agents
        learner.age_days = 5 * 365
        action = AgentAction(action="teach", target_agent_id=learner.id, message="foraging")
        self.engine._apply_action(world, teacher, action)
        self.assertNotIn("foraging", learner.knowledge)
        teacher.knowledge.append("foraging")
        self.engine._apply_action(world, teacher, action)
        self.assertIn("foraging", learner.knowledge)
        learner.health = 0
        self.engine._check_death(world, learner, "test injury")
        self.assertFalse(learner.alive)
        self.assertFalse(learner.buried)
        self.engine._apply_action(world, teacher, AgentAction(action="bury", target_agent_id=learner.id))
        self.assertTrue(learner.buried)
        self.assertTrue(any(event.kind == EventKind.BURIAL for event in world.events))

    async def test_farm_needs_planting_and_growth_before_harvest(self):
        world = self.engine.state
        farmer = world.agents[0]
        world.tech_level = 2
        farmer.inventory["wood"] = 6
        farmer.hunger = 50  # A food shortage provides a real reason to make a farm.
        before = sum(node.quantity for node in world.resources if node.kind in {"fruit", "vegetable", "food"})
        self.assertTrue(self.engine._build(world, farmer, "farm").startswith("Built"))
        self.assertEqual(sum(node.quantity for node in world.resources if node.kind in {"fruit", "vegetable", "food"}), before)
        world.tech_level = 2
        self.assertTrue(self.engine._plant_crop(world, farmer, "vegetable").startswith("Planted"))
        self.assertFalse(self.engine._harvest_crop(world, farmer).startswith("Harvested"))
        plot = world.crops[0]
        plot.growth_days = 28
        self.assertTrue(self.engine._harvest_crop(world, farmer).startswith("Harvested"))
        self.assertFalse(world.crops)

    async def test_unilateral_reproduction_does_not_start_pregnancy_and_child_must_be_taught(self):
        world = self.engine.state
        male, female = world.agents
        async def unilateral(person, _world):
            return AgentAction(action="reproduce", target_agent_id=female.id) if person.id == male.id else AgentAction(action="rest")
        self.engine._ollama.decide = unilateral
        await self.engine._tick_once()
        self.assertIsNone(female.pregnancy_months_remaining)
        async def mutual(person, _world):
            return AgentAction(action="reproduce", target_agent_id=female.id if person.id == male.id else male.id)
        self.engine._ollama.decide = mutual
        for _ in range(20):
            await self.engine._tick_once()
            if female.pregnancy_months_remaining is not None:
                break
        self.assertIsNotNone(female.pregnancy_months_remaining)
        female.knowledge.append("foraging")
        self.engine._give_birth(world, female)
        child = world.agents[-1]
        self.assertEqual(child.age_days, 0)
        self.assertEqual(set(child.parent_ids), {male.id, female.id})
        self.assertEqual(child.knowledge, [], "knowledge is learned; it is not genetically copied")
        self.assertEqual(child.model, world.global_model)

    async def test_disease_progression_and_seeded_geography_persist(self):
        world = self.engine.state
        agent = world.agents[0]
        self.engine._infect(world, agent, "food poisoning", EventSource.NATURAL)
        before = agent.health
        self.engine._advance_time(world, elapsed_seconds=world.month_length_seconds)
        self.assertEqual(agent.disease_days, 1)
        self.assertLess(agent.health, before)
        self.engine._save()
        restored = SimulationEngine(str(Path(self.directory.name) / "world.sqlite3"))
        self.assertEqual(restored.state.agents[0].disease, "food poisoning")
        self.assertEqual(restored.state.tick, world.tick)
        first = self.engine._generate_terrain(36, 18, 7)
        self.assertEqual(first, self.engine._generate_terrain(36, 18, 7))
        self.assertNotEqual(first, self.engine._generate_terrain(36, 18, 8))

    async def test_http_controls_stats_models_and_event_provenance(self):
        from app.main import app
        async def decide(person, world):
            return AgentAction(action="rest")
        self.engine._ollama.decide = decide
        with patch("app.api.routes.engine", self.engine), patch.object(
            OllamaClient, "installed_models", new=AsyncMock(return_value=["qwen2.5:0.5b"])
        ):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://world") as client:
                self.assertEqual((await client.get("/api/world")).status_code, 200)
                self.assertEqual((await client.get("/api/models")).json()["models"], ["qwen2.5:0.5b"])
                self.assertEqual((await client.patch("/api/world/model", json={"model": "another-model"})).status_code, 422)
                person = self.engine.state.agents[0]
                result = await client.patch(f"/api/agents/{person.id}/state", json={"health": 90})
                self.assertEqual(result.json()["health"], 90)
                result = await client.post("/api/events", json={"kind": "injury", "x": person.x, "y": person.y})
                self.assertEqual(result.status_code, 200)
                self.assertTrue(any(event["source"] == "spectator" and event["kind"] == "spectator_event"
                                    for event in result.json()["events"]))
                result = await client.post("/api/world/tick")
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json()["tick"], 1)
                self.assertTrue((await client.post("/api/world/run")).json()["running"])
                speed = await client.patch("/api/world/speed", json={"time_scale": 4, "auto_accelerate": False})
                self.assertEqual(speed.json()["time_scale"], 1)
                self.assertTrue(speed.json()["running"])
                result = await client.post("/api/events", json={"kind": "storm", "x": 0, "y": 0})
                self.assertTrue(result.json()["running"], "an intervention must never pause the world")
                self.assertFalse((await client.post("/api/world/pause")).json()["running"])


if __name__ == "__main__":
    unittest.main()
