"""Family choices must be answerable over time, and food NPCs must remain bounded."""

import unittest
from unittest.mock import patch

import test_world as fixtures
from app.agent_brain.ollama_client import OllamaClient
from app.domain import AgentAction, Animal, EventKind
from app.simulation.rules import animal_capacity, reproduction_block


class FamilyAndEcologyTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.WorldTests.setUp
    asyncTearDown = fixtures.WorldTests.asyncTearDown

    async def test_separate_family_proposals_lead_to_pregnancy_and_birth(self):
        world = self.engine.state
        male, female = world.agents
        async def propose(person, _):
            return AgentAction(action="reproduce", target_agent_id=female.id) if person.id == male.id else AgentAction(action="rest")
        self.engine._ollama.decide = propose
        await self.engine._tick_once()
        self.assertIsNone(female.pregnancy_days_remaining)
        self.assertEqual(male.family_offer.action, "reproduce")
        observation = OllamaClient._observation(female, world)
        self.assertEqual(observation["nearby_agents"][0]["family_offer"], "reproduce")
        choices = OllamaClient.action_choices(female, world)
        self.assertIn("reproduce", [action.action for action in choices[:3]])
        async def accept(person, _):
            return AgentAction(action="reproduce", target_agent_id=male.id) if person.id == female.id else AgentAction(action="rest")
        self.engine._ollama.decide = accept
        await self.engine._tick_once()
        self.assertIsNotNone(female.pregnancy_days_remaining)
        self.assertIsNone(male.family_offer)
        female.pregnancy_days_remaining = 1
        self.engine._advance_time(world, force_day=True)
        self.assertEqual(len(world.agents), 3)
        child = world.agents[-1]
        self.assertEqual(set(child.parent_ids), {male.id, female.id})
        self.assertEqual(child.knowledge, [])
        self.assertTrue(any(event.kind == EventKind.BIRTH for event in world.events))
        self.assertIn("recovery", reproduction_block(world, male, female))

    async def test_expired_consent_and_childhood_cannot_create_pregnancy(self):
        world = self.engine.state
        male, female = world.agents
        male.family_offer = AgentAction(action="reproduce", target_agent_id=female.id)
        male.family_offer_until_tick = world.tick - 1
        async def choice(person, _):
            return AgentAction(action="reproduce", target_agent_id=male.id) if person.id == female.id else AgentAction(action="rest")
        self.engine._ollama.decide = choice
        await self.engine._tick_once()
        self.assertIsNone(female.pregnancy_days_remaining)
        male.age_days = 100
        self.assertTrue(reproduction_block(world, male, female))
        self.assertNotIn("reproduce", [action.action for action in OllamaClient.action_choices(male, world)])

    async def test_family_choice_walks_to_partner_and_does_not_require_identical_turns(self):
        world = self.engine.state
        male, female = world.agents
        female.x += 3
        async def choice(person, _):
            return AgentAction(action="bond", target_agent_id=female.id) if person.id == male.id else AgentAction(action="rest")
        self.engine._ollama.decide = choice
        await self.engine._tick_once()
        self.assertEqual(male.last_action.action, "move")
        self.assertIsNotNone(male.pending_action)
        for _ in range(2):
            await self.engine._tick_once()
        self.assertLessEqual(self.engine._distance(male, female), 1)

    async def test_reflexes_consume_real_resources_while_mind_is_busy(self):
        world = self.engine.state
        person = world.agents[0]
        person.thirst, person.hunger = 95, 90
        water = next(node for node in world.resources if node.kind == "water")
        food = next(node for node in world.resources if node.kind == "fruit")
        water_before, food_before = water.quantity, food.quantity
        self.engine._survival_reflexes(world, 100)
        self.assertLess(person.thirst, 95)
        self.assertLess(water.quantity, water_before)
        self.engine._survival_reflexes(world, 101)
        self.assertLess(person.hunger, 90)
        self.assertLess(food.quantity, food_before)
        self.assertEqual(person.decision_source, "reflex")
        self.assertIsNone(person.family_offer, "reflexes never invent consent")

    async def test_animal_budget_covers_spawn_births_and_migration_without_carcass_piles(self):
        world = self.engine.state
        world.animals = [Animal(id=f"wild-{index}", species="goat", sex="female" if index % 2 else "male",
                               age_days=500, x=17, y=8) for index in range(200)]
        before_resources = len(world.resources)
        self.engine._rebalance_animals(world)
        self.assertEqual(len(world.animals), animal_capacity(world))
        self.assertEqual(len(world.resources), before_resources)
        with patch.object(self.engine._random, "random", return_value=0.005):
            for _ in range(15):
                self.engine._spawn_wildlife(world)
                self.engine._advance_animals(world)
        self.assertLessEqual(sum(animal.alive for animal in world.animals), animal_capacity(world))

    async def test_infant_travels_with_primary_caregiver_and_remembers_dead_parent(self):
        world = self.engine.state
        male, female = world.agents
        female.other_parent_id = male.id
        male.alive = False
        self.engine._give_birth(world, female)
        child = world.agents[-1]
        self.assertIn(male.id, child.parent_ids)
        self.engine._apply_action(world, female, AgentAction(action="move", dx=1))
        self.assertEqual((child.x, child.y), (female.x, female.y))
