"""Continuous-world controls and GPU placement, isolated from the spectator database."""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx

import test_world as fixtures
from app.agent_brain.ollama_client import OllamaClient
from app.domain import AgentAction, Animal, EventKind
from app.simulation.engine import SimulationEngine
from app.simulation.rules import animal_capacity


class ContinuousWorldTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.WorldTests.setUp
    asyncTearDown = fixtures.WorldTests.asyncTearDown

    async def test_close_founders(self):
        for seed in range(12):
            world = self.engine._new_world(seed)
            first, second = world.agents
            self.assertLessEqual(self.engine._distance(first, second), 1)
            self.assertEqual({first.sex, second.sex}, {"male", "female"})
            self.assertTrue(all(person.age_days >= 18 * 365 for person in world.agents))
            self.assertTrue(all(self.engine._terrain_at(world, person.x, person.y).kind != "ocean" for person in world.agents))
            self.assertIsNone(second.pregnancy_months_remaining, "proximity does not force reproduction")


    async def test_terrain_care(self):
        world, agent = self.engine.state, self.engine.state.agents[0]
        cell = self.engine._terrain_at(world, agent.x, agent.y)
        cell.condition, cell.fertility, cell.pollution, cell.moisture = 20, 10, 70, 0.2
        for node in world.resources:
            node.contamination = 60
        self.assertIn("tend_terrain", [action.action for action in OllamaClient.action_choices(agent, world)])
        before_water = next(node for node in world.resources if node.kind == "water").quantity
        self.engine._apply_action(world, agent, AgentAction(action="tend_terrain"))
        self.assertEqual((cell.condition, cell.fertility, cell.pollution), (32, 18, 55))
        self.assertEqual(next(node for node in world.resources if node.kind == "water").quantity, before_water - 1)
        self.assertTrue(all(node.contamination == 42 for node in world.resources))
        self.engine._apply_action(world, agent, AgentAction(action="tend_terrain"))
        self.assertEqual(cell.condition, 32, "one care action per cell per day")
        self.assertNotIn("tend_terrain", [action.action for action in OllamaClient.action_choices(agent, world)])
        self.engine._apply_hazard_to_resources(world, agent.x, agent.y, 3, "wildfire")
        self.assertLess(cell.condition, 32)
        self.assertGreater(cell.pollution, 55)


    async def test_wildlife_spawn_and_npc_movement(self):
        world = self.engine.state
        world.animals = [Animal(id=f"npc-{index}", species="goat", sex="female", x=0, y=0) for index in range(205)]
        self.engine._rebalance_animals(world)
        self.assertLessEqual(len(world.animals), animal_capacity(world))
        world.animals = world.animals[:2]
        with patch.object(self.engine._random, "random", return_value=0):
            self.engine._spawn_wildlife(world)
            self.assertGreater(len(world.animals), 2, "missing food wildlife can repopulate")
            self.assertLessEqual(len(world.animals), animal_capacity(world))
            self.assertTrue(any(event.kind == EventKind.ANIMAL_SPAWNED for event in world.events))
            before = [(animal.x, animal.y) for animal in world.animals]
            self.engine._move_animal_npcs(world)
        self.assertNotEqual(before, [(animal.x, animal.y) for animal in world.animals])
        self.assertTrue(all(self.engine._terrain_at(world, animal.x, animal.y).kind != "ocean" for animal in world.animals))


    async def test_clock_stays_at_one_x(self):
        world = self.engine.state
        self.engine._ollama.decide = AsyncMock(return_value=AgentAction(action="rest"))
        await self.engine.change_speed(2, True)
        world.running_elapsed_seconds = 240
        await self.engine.start()
        await asyncio.sleep(0.6)
        self.assertEqual(world.time_scale, 1)
        self.assertFalse(world.auto_accelerate)
        self.assertLess(world.month_progress_seconds, 2)
        await self.engine.change_speed(4, False)
        await asyncio.sleep(0.6)
        self.assertEqual(world.time_scale, 1)
        self.assertFalse(world.auto_accelerate)
        self.assertTrue(world.running)


    async def test_extinction_keeps_ecosystem_running(self):
        world = self.engine.state
        for person in world.agents:
            person.alive = False
        world.month_length_seconds = 1
        await self.engine.start(0.5)
        await asyncio.sleep(1.2)
        self.assertTrue(world.running)
        self.assertGreaterEqual(world.tick, 1)
        self.assertTrue(any(event.kind == EventKind.WORLD_EXTINCT for event in world.events))
        self.assertFalse(self.engine._clock_task.done())


    async def test_run_choice_survives_shutdown_reset_and_restore(self):
        self.engine._ollama.decide = AsyncMock(return_value=AgentAction(action="rest"))
        await self.engine.start()
        before_id = self.engine.state.id
        await self.engine.reset(19)
        self.assertNotEqual(before_id, self.engine.state.id)
        self.assertTrue(self.engine.state.running)
        await self.engine.shutdown()
        restored = SimulationEngine(str(self.engine._store.path))
        self.assertTrue(restored.state.running)
        await restored.pause()
        paused = SimulationEngine(str(self.engine._store.path))
        self.assertFalse(paused.state.running)


    async def test_failed_round_retries_without_stopping(self):
        original = self.engine._tick_once
        calls = 0
        retried = asyncio.Event()
        async def once(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("temporary action failure")
            retried.set()
            return await original(*args, **kwargs)
        self.engine._tick_once = once
        self.engine._ollama.decide = AsyncMock(return_value=AgentAction(action="rest"))
        await self.engine.start(0.5)
        # Wait for the actual retry so a busy Windows filesystem cannot make a fixed sleep flaky.
        await asyncio.wait_for(retried.wait(), timeout=8)
        self.assertGreaterEqual(calls, 2)
        self.assertTrue(self.engine.state.running)
        self.assertTrue(any(event.kind == EventKind.SIMULATION_ERROR and event.details.get("recoverable") for event in self.engine.state.events))

    async def test_partial_ecology_failure_rolls_back_and_keeps_clock_running(self):
        original = self.engine._advance_time
        calls = 0
        def once(world, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                world.tick = 999
                raise RuntimeError("temporary ecology failure")
            return original(world, *args, **kwargs)
        self.engine._advance_time = once
        self.engine._ollama.decide = AsyncMock(return_value=AgentAction(action="rest"))
        self.engine.state.month_length_seconds = 2
        await self.engine.start()
        await asyncio.sleep(1.2)
        self.assertTrue(self.engine.state.running)
        self.assertNotEqual(self.engine.state.tick, 999)
        self.assertGreater(self.engine.state.month_progress_seconds, 0)
        self.assertFalse(self.engine._clock_task.done())


    async def test_gpu_first_warmup_and_ram_fallback(self):
        original_client, captured = httpx.AsyncClient, []
        def respond(request):
            body = json.loads(request.content)
            captured.append(body)
            if body["options"]["num_gpu"]:
                return httpx.Response(500, text="CUDA allocation out of memory")
            return httpx.Response(200, json={"done": True})
        with patch("app.agent_brain.ollama_client.httpx.AsyncClient", side_effect=lambda **kwargs:
                   original_client(transport=httpx.MockTransport(respond), **kwargs)):
            self.assertTrue(await OllamaClient().warm_model())
        self.assertEqual([body["options"]["num_gpu"] for body in captured], [999, 0])
        self.assertTrue(all(body["model"] == "qwen2.5:0.5b" and body["keep_alive"] == -1 for body in captured))

    async def test_backend_starts_installed_local_ollama_when_service_is_down(self):
        from app import main

        with patch.object(main.OllamaClient, "is_available", new=AsyncMock(side_effect=[False, True])), \
             patch.object(main.shutil, "which", return_value="ollama.exe"), \
             patch.object(main.subprocess, "Popen") as launch:
            await main._ensure_local_ollama()

        launch.assert_called_once()
        self.assertEqual(launch.call_args.args[0], ["ollama.exe", "serve"])


    async def test_runtime_reports_actual_gpu_residency(self):
        original_client = httpx.AsyncClient
        def respond(request):
            return httpx.Response(200, json={"models": [{"name": "qwen2.5:0.5b", "size_vram": 481810185}]})
        with patch("app.agent_brain.ollama_client.httpx.AsyncClient", side_effect=lambda **kwargs:
                   original_client(transport=httpx.MockTransport(respond), **kwargs)):
            info = await OllamaClient().runtime_info()
        self.assertEqual(info["device"], "gpu")
        self.assertGreater(info["vram_bytes"], 0)
