"""Physical construction, shared items, sea travel, predator defence and attributable deaths."""

import unittest
from unittest.mock import patch

import test_world as fixtures
from app.agent_brain.ollama_client import OllamaClient
from app.domain import AgentAction, Animal, CraftedItem, EventKind, Structure
from app.simulation.planning import material_stock
from app.simulation.rules import PREGNANCY_DAYS
from app.simulation.engine import SimulationEngine


class SettlementTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.WorldTests.setUp
    asyncTearDown = fixtures.WorldTests.asyncTearDown

    async def test_fatal_damage_records_specific_cause_and_snapshot(self):
        world = self.engine.state
        # This unit test exercises one full biological day at normal time scale.
        world.day_length_seconds = 60
        person = world.agents[0]
        for cause, hunger, thirst, disease in (("starvation", 100, 0, None), ("dehydration", 0, 100, None),
                                              ("food poisoning", 0, 0, "food poisoning")):
            person.alive, person.health, person.energy = True, 1, 80
            person.hunger, person.thirst, person.disease = hunger, thirst, disease
            self.engine._advance_biology(world, person)
            self.assertFalse(person.alive)
            self.assertEqual(person.death_cause, cause)
            self.assertEqual(person.death_details["last_injury"]["cause"], cause)
            self.assertEqual(world.events[-1].kind, EventKind.DEATH)

    async def test_9_day_pregnancy_reaches_birth(self):
        world = self.engine.state
        first, second = world.agents
        self.engine._resolve_reproduction(world, first, second)
        self.assertEqual(PREGNANCY_DAYS, 9)
        self.assertEqual(second.pregnancy_days_remaining, 9)
        for _ in range(9):
            second.hunger = second.thirst = 0
            second.energy, second.health, second.disease = 80, 100, None
            world.tick += 1
            self.engine._advance_biology(world, second)
        self.assertEqual(len(world.agents), 3)

    async def test_shared_family_materials_and_duplicate_prevention(self):
        world = self.engine.state
        first, second = world.agents
        first.bonded_partner_id, second.bonded_partner_id = second.id, first.id
        first.inventory["wood"], second.inventory["wood"] = 1, 1
        self.assertEqual(material_stock(world, first)["wood"], 2)
        self.assertTrue(self.engine._build(world, first, "lean_to").startswith("Built"))
        self.assertEqual(material_stock(world, first)["wood"], 0)
        second.x += 1
        second.inventory["wood"] = 5
        self.assertTrue(self.engine._has_shelter(world, second), "creator ownership never blocks shelter use")
        self.assertIn("already meet", self.engine._build(world, second, "lean_to"))
        self.assertEqual(second.inventory["wood"], 5)
        self.assertFalse(any(action.action == "build" and action.structure_type in {"lean_to", "hut", "home"}
                             for action in OllamaClient.action_choices(second, world)))

    async def test_building_requires_suitable_site_and_routes_without_spending_materials(self):
        world = self.engine.state
        person = world.agents[0]
        person.inventory["wood"] = 6
        cell = self.engine._terrain_at(world, person.x, person.y)
        cell.kind = "river"
        self.assertIn("dry land", self.engine._build(world, person, "lean_to"))
        self.assertEqual(person.inventory["wood"], 6)
        move = self.engine._prepare_construction(world, person, AgentAction(action="build", structure_type="lean_to"))
        self.assertEqual(move.action, "move")
        self.engine._apply_action(world, person, move)
        self.assertTrue(self.engine._build(world, person, "lean_to").startswith("Built"))

    async def test_shared_crafting_handover_and_repair(self):
        world = self.engine.state
        first, second = world.agents
        world.animals = [Animal(id="food", species="deer", sex="male", x=first.x, y=first.y)]
        first.knowledge.append("weapon making")
        first.inventory.update(wood=4, stone=3)
        self.assertTrue(self.engine._craft(world, first, "spear").startswith("Crafted"))
        item = world.items[-1]
        self.assertIn("Equipped", self.engine._use_item(world, first, item.id))
        self.assertIn("Equipped", self.engine._use_item(world, second, item.id))
        self.assertIsNone(first.equipped_item_id)
        self.assertEqual(second.equipped_item_id, item.id)
        self.engine._apply_action(world, second, AgentAction(action="move", dx=1))
        self.assertEqual((item.x, item.y), (second.x, second.y))
        item.durability = 20
        second.inventory["wood"] = 1
        self.engine._repair(world, second, AgentAction(action="repair", target_item_id=item.id))
        self.assertEqual(item.durability, 55)
        self.assertEqual(second.inventory["wood"], 0)

    async def test_experiment_craft_board_sail_to_other_island_and_disembark(self):
        world = self.engine.state
        person = world.agents[0]
        # Two isolated dry islands separated by two water steps.
        for cell in world.terrain:
            cell.kind = "ocean"
        person.x, person.y = 10, 8
        for x in (10, 13):
            self.engine._terrain_at(world, x, 8).kind = "grassland"
        person.inventory["wood"] = 7
        self.assertIn("before", self.engine._craft(world, person, "raft"))
        with patch.object(self.engine._random, "random", return_value=0):
            self.assertIn("Discovered", self.engine._experiment(world, person, "raft"))
        self.assertIn("Crafted", self.engine._craft(world, person, "raft"))
        boat = world.items[-1]
        self.assertIn("Boarded", self.engine._board(world, person, boat.id))
        for _ in range(3):
            choices = OllamaClient.action_choices(person, world)
            self.assertNotIn("move", [action.action for action in choices], "walking is not a feasible action aboard a raft")
            self.assertIn("Sailed", self.engine._sail(world, person, 1, 0))
        self.assertEqual((person.x, person.y), (13, 8))
        self.assertIn("Disembarked", self.engine._disembark(world, person))
        self.assertIn("seafaring", person.knowledge)
        self.assertTrue(any(event.kind == EventKind.EXPLORATION for event in world.events))

    async def test_predator_attack_and_armed_defence(self):
        world = self.engine.state
        person = world.agents[0]
        wolf = Animal(id="predator", species="wolf", sex="female", x=person.x, y=person.y, hunger=60)
        world.animals = [wolf]
        person.health = 1
        with patch.object(self.engine._random, "random", side_effect=[0, 0.99]):
            self.engine._predator_encounters(world)
        self.assertFalse(person.alive)
        self.assertEqual(person.death_cause, "a wolf attack")
        person.alive, person.health = True, 100
        world.tick += 1
        wolf.hunger = 60
        item = CraftedItem(id="weapon", kind="spear", x=person.x, y=person.y,
                           creator_agent_id=person.id, holder_agent_id=person.id, created_tick=world.tick)
        world.items = [item]
        person.equipped_item_id = item.id
        with patch.object(self.engine._random, "random", side_effect=[0, 0.2]):
            self.engine._predator_encounters(world)
        self.assertEqual(person.health, 100)
        self.assertLess(item.durability, 100)
        self.assertTrue(world.events[-1].details["defended"])

    async def test_internal_family_conflict_is_possible_and_recorded(self):
        world = self.engine.state
        first, second = world.agents
        first.bonded_partner_id = second.id
        self.engine._fight(world, first, second.id)
        event = next(event for event in reversed(world.events) if event.kind == EventKind.FIGHT)
        self.assertEqual(event.details["scope"], "family")
        self.assertLess(second.health, 100)

    async def test_boarding_finishes_instead_of_becoming_an_endless_pending_action(self):
        world = self.engine.state
        person = world.agents[0]
        boat = CraftedItem(id="raft", kind="raft", x=person.x, y=person.y, capacity=4,
                           creator_agent_id=person.id, created_tick=0)
        world.items = [boat]
        async def decide(actor, _):
            return AgentAction(action="board", target_item_id=boat.id) if actor.id == person.id else AgentAction(action="rest")
        self.engine._ollama.decide = decide
        await self.engine._tick_once()
        self.assertEqual(person.vehicle_id, boat.id)
        self.assertIsNone(person.pending_action)

    async def test_old_pregnancy_migrates_once_and_preserves_world(self):
        world = self.engine.state
        world.rules_version = 1
        world.running = True
        world.agents[1].pregnancy_days_remaining = 180
        self.engine._save()
        restored = SimulationEngine(str(self.engine._store.path))
        self.assertEqual(restored.state.id, world.id)
        self.assertTrue(restored.state.running)
        self.assertEqual(restored.state.agents[1].pregnancy_days_remaining, 6)
        restored = SimulationEngine(str(self.engine._store.path))
        self.assertEqual(restored.state.agents[1].pregnancy_days_remaining, 6)

    async def test_model_chosen_exploration_continues_through_boarding_sailing_and_landing(self):
        world = self.engine.state
        person = world.agents[0]
        world.agents = [person]
        person.x, person.y = 10, 8
        for cell in world.terrain:
            cell.kind = "ocean"
        for x in (10, 13):
            self.engine._terrain_at(world, x, 8).kind = "grassland"
        world.items = [CraftedItem(id="raft", kind="raft", x=10, y=8, capacity=4,
                                  creator_agent_id=person.id, created_tick=0)]
        calls = 0
        async def choose(actor, _):
            nonlocal calls
            calls += 1
            return AgentAction(action="explore", destination_x=13, destination_y=8)
        self.engine._ollama.decide = choose
        for _ in range(5):
            await self.engine._tick_once()
        self.assertEqual((person.x, person.y), (13, 8))
        self.assertEqual(calls, 1, "physical journey continues one independent brain choice")
        self.assertIsNone(person.vehicle_id)
        self.assertIsNone(person.pending_action)
