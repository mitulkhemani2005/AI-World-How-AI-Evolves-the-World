"""A full year, parent chosen names and social motives in isolated saved worlds."""

import unittest
from unittest.mock import patch

import test_world as fixtures
from app.agent_brain.ollama_client import OllamaClient
from app.domain import AgentAction, Animal, EventKind
from app.settings import settings
from app.simulation.engine import SimulationEngine


class FamilyClockAndMotiveTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.WorldTests.setUp
    asyncTearDown = fixtures.WorldTests.asyncTearDown

    async def test_one_simulated_year_is_twelve_real_minutes_at_default_speed(self):
        world = self.engine.state
        self.assertEqual(world.rules_version, 3)
        self.assertFalse(world.auto_accelerate)
        self.assertEqual(world.time_scale, 1)
        self.assertAlmostEqual(world.day_length_seconds * 365, 720)
        # Empty the isolated test habitat so the clock check measures calendar math.
        world.agents.clear()
        world.animals.clear()
        with (patch.object(self.engine, "_advance_environment"),
              patch.object(self.engine, "_regenerate_resources"),
              patch.object(self.engine, "_advance_ecology"),
              patch.object(self.engine, "_natural_events")):
            self.engine._advance_time(world, elapsed_seconds=720)
        self.assertEqual(world.tick, 365)

    async def test_saved_world_clock_and_pregnancy_upgrade_once(self):
        world = self.engine.state
        world.rules_version = 2
        world.running = True
        world.day_length_seconds = 60
        world.day_progress_seconds = 30
        world.time_scale = 8
        world.base_time_scale = 2
        world.auto_accelerate = True
        world.agents[1].pregnancy_days_remaining = 90
        self.engine._save()
        restored = SimulationEngine(str(self.engine._store.path))
        self.assertEqual(restored.state.id, world.id)
        self.assertTrue(restored.state.running)
        self.assertEqual(restored.state.time_scale, 1)
        self.assertFalse(restored.state.auto_accelerate)
        self.assertAlmostEqual(restored.state.day_progress_seconds, settings.day_length_seconds / 2)
        self.assertEqual(restored.state.agents[1].pregnancy_days_remaining, 9)
        restored_again = SimulationEngine(str(self.engine._store.path))
        self.assertEqual(restored_again.state.agents[1].pregnancy_days_remaining, 9)

    async def test_parent_selects_name_before_random_sex_birth(self):
        world = self.engine.state
        father, mother = world.agents
        mother.pregnancy_days_remaining = 1
        mother.other_parent_id = father.id
        choices = OllamaClient.action_choices(father, world)
        proposed = next(action for action in choices if action.action == "name_child")
        self.assertIn("Suggested", self.engine._apply_action(world, father, proposed))
        self.assertEqual(mother.unborn_name_suggestions[father.id], proposed.message)
        # The sex comes from the world's random stream, independent of the name.
        with patch.object(self.engine._random, "choice", side_effect=lambda options:
                          "female" if options == ["male", "female"] else options[0]):
            self.engine._advance_time(world, force_day=True)
        child = world.agents[-1]
        self.assertEqual(child.name, proposed.message)
        self.assertEqual(child.sex, "female")
        self.assertEqual(set(child.parent_ids), {father.id, mother.id})
        self.assertEqual(mother.unborn_name_suggestions, {})
        birth = next(event for event in reversed(world.events) if event.kind == EventKind.BIRTH)
        self.assertEqual(birth.details["named_by"], father.id)

    async def test_birth_still_happens_if_short_gestation_outpaces_name_choice(self):
        world = self.engine.state
        father, mother = world.agents
        mother.pregnancy_days_remaining = 1
        mother.other_parent_id = father.id
        self.engine._advance_time(world, force_day=True)
        child = world.agents[-1]
        self.assertEqual(child.name, "Niru")
        birth = next(event for event in reversed(world.events) if event.kind == EventKind.BIRTH)
        self.assertEqual(birth.details["named_by"], "family_convention")
        self.assertEqual(child.name_status, "provisional")
        choice = next(action for action in OllamaClient.action_choices(mother, world)
                      if action.action == "name_child" and action.target_agent_id == child.id)
        self.assertIn("Named the child", self.engine._apply_action(world, mother, choice))
        self.assertEqual(child.name, choice.message)
        self.assertEqual(child.name_status, "final")

    async def test_danger_and_care_affect_feelings_and_action_menu(self):
        world = self.engine.state
        first, second = world.agents
        first.bonded_partner_id = second.id
        second.bonded_partner_id = first.id
        second.fear = 55
        second.stress = 60
        first.traits["aggression"] = 0.9
        self.assertNotIn("fight", [action.action for action in OllamaClient.action_choices(first, world)])
        care = next(action for action in OllamaClient.action_choices(first, world)
                    if action.action == "help" and action.target_agent_id == second.id)
        self.engine._apply_action(world, first, care)
        self.assertLess(second.fear, 55)
        self.assertLess(second.stress, 60)
        self.assertGreater(first.relationship_scores[second.id], 20)
        self.assertNotIn("help", [action.action for action in OllamaClient.action_choices(first, world)])
        wolf = Animal(id="threat", species="wolf", sex="female", x=second.x, y=second.y, hunger=70)
        world.animals = [wolf]
        with patch.object(self.engine._random, "random", side_effect=[0, 0.9]):
            self.engine._predator_encounters(world)
        self.assertGreater(second.fear, 40)
        self.assertIn("flee", [action.action for action in OllamaClient.action_choices(second, world)])

    async def test_lonely_parent_travels_to_family_and_reconnects(self):
        world = self.engine.state
        first, second = world.agents
        first.bonded_partner_id = second.id
        second.bonded_partner_id = first.id
        first.loneliness = 65
        second.x = first.x + 3
        visit = next(action for action in OllamaClient.action_choices(first, world)
                     if action.action == "visit" and action.target_agent_id == second.id)
        for _ in range(3):
            step = self.engine._prepare_social_action(world, first, visit)
            self.engine._apply_action(world, first, step)
        self.assertLessEqual(self.engine._distance(first, second), 1)
        self.assertIn("Spent time", self.engine._apply_action(world, first, visit))
        self.assertLess(first.loneliness, 65)
        self.assertEqual(first.last_social_tick, world.tick)

    async def test_relative_grieves_once_after_a_death(self):
        world = self.engine.state
        first, second = world.agents
        first.bonded_partner_id = second.id
        second.bonded_partner_id = first.id
        first.health = 0
        self.engine._check_death(world, first, "a fatal injury")
        self.assertGreaterEqual(second.stress, 30)
        result = self.engine._apply_action(world, second, AgentAction(action="mourn", target_agent_id=first.id))
        self.assertIn("Mourned", result)
        self.assertIn(first.id, second.mourned_ids)
        self.assertFalse(any(action.action == "mourn" and action.target_agent_id == first.id
                             for action in OllamaClient.action_choices(second, world)))


if __name__ == "__main__":
    unittest.main()
