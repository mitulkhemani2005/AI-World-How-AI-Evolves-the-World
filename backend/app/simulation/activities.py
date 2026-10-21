"""Physical shared items, construction travel, sea exploration and NPC predator encounters."""

from uuid import uuid4

from app.domain import AgentAction, CraftedItem, EventKind, EventSource
from app.simulation.planning import consume_materials, is_coast, item_needed, site_problem
from app.simulation.rules import ADULT_AGE_DAYS, ITEM_RECIPES, PREDATOR_SPECIES


class ActivityRules:
    """Engine mixin: every activity uses the authoritative world's materials and positions."""

    def _activity(self, world, person, action):
        handlers = {"craft": lambda: self._craft(world, person, action.item_kind),
            "experiment": lambda: self._experiment(world, person, action.item_kind),
            "use_item": lambda: self._use_item(world, person, action.target_item_id),
            "drop_item": lambda: self._drop_item(world, person),
            "repair": lambda: self._repair(world, person, action),
            "board": lambda: self._board(world, person, action.target_item_id),
            "sail": lambda: self._sail(world, person, action.dx, action.dy),
            "disembark": lambda: self._disembark(world, person),
            "defend": lambda: self._defend(world, person, action.target_animal_id),
            "flee": lambda: self._flee(world, person),
            "explore": lambda: self._finish_exploration(world, person, action)}
        return handlers[action.action]() if action.action in handlers else None

    def _prepare_construction(self, world, person, action):
        if action.action == "explore":
            target = self._terrain_at(world, action.destination_x, action.destination_y)
            if target and (target.x, target.y) != (person.x, person.y):
                return self._move_or_act(world, person, target, "explore", "Continue the chosen exploration journey")
            return action
        coastal = action.action == "craft" and action.item_kind == "raft"
        if action.action != "build" and not coastal:
            return action
        suitable = lambda x, y: is_coast(world, x, y) if coastal else not site_problem(world, action.structure_type or "lean_to", x, y)
        if suitable(person.x, person.y):
            return action
        sites = [cell for cell in world.terrain if self._distance(person, cell) <= 4 and suitable(cell.x, cell.y)]
        for cell in sorted(sites, key=lambda cell: self._distance(person, cell)):
            step = self._move_or_act(world, person, cell, action.action, "Walk to a suitable construction site")
            if step.action != "rest":
                return step
        return AgentAction(action="rest", reason="No suitable reachable construction site is locally visible")

    def _finish_exploration(self, world, person, action):
        if (person.x, person.y) != (action.destination_x, action.destination_y):
            return "The selected exploration destination is not within reach."
        if person.vehicle_id:
            cell = self._terrain_at(world, person.x, person.y)
            if cell and cell.kind != "ocean":
                self._disembark(world, person)
        self._remember(person, f"Completed your chosen journey to ({person.x}, {person.y}).")
        self._record(world, EventSource.AGENT_ACTION, EventKind.EXPLORATION,
                     f"{person.name} completed an exploration journey.", [person.id], {"x": person.x, "y": person.y})
        return "Reached the selected frontier; this place is now part of your experience."

    def _experiment(self, world, person, kind):
        lesson = "raft building" if kind == "raft" else "weapon making"
        if lesson in person.knowledge:
            return "This technique is already known; use it instead of repeating the experiment."
        if kind == "raft" and not is_coast(world, person.x, person.y):
            return "Water-crossing experiments require a dry coastal site."
        if not consume_materials(world, person, {"wood": 1} if kind == "raft" else {"wood": 1, "stone": 1}):
            return "The experiment needs real materials."
        person.energy = max(0, person.energy - 6)
        if self._random.random() > 0.75:
            return "The experiment failed; the used materials were lost, but another attempt is possible."
        self._learn(person, lesson)
        self._record(world, EventSource.AGENT_ACTION, EventKind.DISCOVERY,
                     f"{person.name} discovered {lesson} through experimentation.", [person.id], {"lesson": lesson})
        return f"Discovered {lesson}; this technique can now be taught to others."

    def _craft(self, world, person, kind):
        if kind not in ITEM_RECIPES:
            return "Unknown item recipe."
        lesson = "raft building" if kind == "raft" else "weapon making"
        if lesson not in person.knowledge:
            return f"Experiment or learn {lesson} before crafting this item."
        if not item_needed(world, person, kind):
            person.crafting_project = None
            return "A usable shared item already meets this local need."
        if kind == "raft" and not is_coast(world, person.x, person.y):
            return "Build the raft on a dry coast."
        if not consume_materials(world, person, ITEM_RECIPES[kind]):
            return "Not enough materials to craft this item."
        item = CraftedItem(id=str(uuid4()), kind=kind, x=person.x, y=person.y,
                           creator_agent_id=person.id, created_tick=world.tick, capacity=4 if kind == "raft" else 1)
        world.items.append(item)
        person.crafting_project = None
        self._record(world, EventSource.AGENT_ACTION, EventKind.CRAFTING,
                     f"{person.name} made a shared {kind.replace('_', ' ')}.", [person.id],
                     {"item_id": item.id, "kind": kind, "cost": ITEM_RECIPES[kind], "x": item.x, "y": item.y})
        return f"Crafted a {kind.replace('_', ' ')}; anyone nearby can use it."

    def _use_item(self, world, person, item_id):
        item = next((item for item in world.items if item.id == item_id and item.durability > 0), None)
        if not item or self._distance(person, item) > 1:
            return "No usable shared item is within reach."
        if item.kind == "raft":
            return self._board(world, person, item.id)
        holder = next((other for other in world.agents if other.id == item.holder_agent_id and other.alive), None)
        if holder and holder.id != person.id:
            if holder.relationship_scores.get(person.id, 0) < -10:
                self._adjust_relationship(holder, person, -3)
                return "The current user refused the handover; the dispute remains unresolved."
            holder.equipped_item_id = None
            self._adjust_relationship(person, holder, 1)
        self._drop_item(world, person)
        item.holder_agent_id = person.id
        person.equipped_item_id = item.id
        item.x, item.y = person.x, person.y
        self._record(world, EventSource.AGENT_ACTION, EventKind.ITEM_USED,
                     f"{person.name} took the shared {item.kind.replace('_', ' ')} for use.", [person.id], {"item_id": item.id})
        return f"Equipped the shared {item.kind.replace('_', ' ')}."

    def _drop_item(self, world, person):
        item = next((item for item in world.items if item.id == person.equipped_item_id), None)
        if item:
            item.holder_agent_id = None
            item.x, item.y = person.x, person.y
        person.equipped_item_id = None
        return "Left the item here for anyone to use."

    def _move_equipment(self, world, person):
        for item in world.items:
            if item.holder_agent_id == person.id and item.kind != "raft":
                item.x, item.y = person.x, person.y

    def _repair(self, world, person, action):
        target = next((item for item in world.items if item.id == action.target_item_id), None)
        building = next((item for item in world.structures if item.id == action.target_structure_id), None)
        target = target or building
        if not target or self._distance(person, target) > 1:
            return "The damaged object is not within reach."
        value = target.condition if building else target.durability
        if value >= 80:
            return "This object does not need repair."
        if not consume_materials(world, person, {"wood": 1}):
            return "Repair needs one real unit of wood."
        if building:
            target.condition = min(100, value + 35)
        else:
            target.durability = min(100, value + 35)
        return "Repaired the shared object instead of making a duplicate."

    def _board(self, world, person, item_id):
        boat = next((item for item in world.items if item.id == item_id and item.kind == "raft" and item.durability > 0), None)
        if not boat or self._distance(person, boat) > 1:
            return "No seaworthy raft is within reach."
        if person.vehicle_id == boat.id:
            return "Already aboard this raft."
        infants = [child for child in world.agents if child.alive and child.age_days < 3 * 365
                   and next((parent_id for parent_id in child.parent_ids if any(parent.id == parent_id and parent.alive for parent in world.agents)), None) == person.id
                   and (child.x, child.y) == (person.x, person.y)]
        aboard = sum(other.alive and other.vehicle_id == boat.id for other in world.agents)
        if aboard + 1 + len(infants) > boat.capacity:
            return "The raft has no safe capacity for this person and their infants."
        for passenger in [person, *infants]:
            passenger.vehicle_id = boat.id
            passenger.has_sailed = False
            passenger.x, passenger.y = boat.x, boat.y
        return "Boarded the shared raft. Nearby people may board if there is room."

    def _sail(self, world, person, dx, dy):
        boat = next((item for item in world.items if item.id == person.vehicle_id and item.kind == "raft"), None)
        if not boat or boat.durability <= 0 or abs(dx) + abs(dy) != 1:
            return "Sailing needs a seaworthy raft and one cardinal movement step."
        nx, ny = (person.x + dx) % world.width, person.y + dy
        cell = self._terrain_at(world, nx, ny)
        origin = self._terrain_at(world, person.x, person.y)
        if not cell or cell.kind in {"mountain", "ice"}:
            return "This coast cannot be landed on safely."
        if cell.kind != "ocean" and origin and origin.kind != "ocean":
            return "Disembark before travelling inland; the raft needs water."
        boat.x, boat.y = nx, ny
        boat.durability = max(0, boat.durability - (4 if world.weather in {"storm", "wind"} else 0.5))
        for passenger in world.agents:
            if passenger.alive and passenger.vehicle_id == boat.id:
                passenger.x, passenger.y = nx, ny
                passenger.has_sailed = True
                self._move_equipment(world, passenger)
        person.energy = max(0, person.energy - 2)
        if cell.kind != "ocean":
            self._learn(person, "seafaring")
            self._record(world, EventSource.AGENT_ACTION, EventKind.EXPLORATION,
                         f"{person.name} reached land by raft.", [person.id], {"x": nx, "y": ny, "item_id": boat.id})
        return f"Sailed to ({nx}, {ny}); {'land reached' if cell.kind != 'ocean' else 'crossing open water'}."

    def _disembark(self, world, person):
        cell = self._terrain_at(world, person.x, person.y)
        if not cell or cell.kind == "ocean":
            return "Disembark only after reaching land."
        boat_id = person.vehicle_id
        person.vehicle_id = None
        person.has_sailed = False
        for child in world.agents:
            if (child.age_days < 3 * 365 and child.vehicle_id == boat_id and next((parent_id for parent_id in child.parent_ids
                if any(parent.id == parent_id and parent.alive for parent in world.agents)), None) == person.id):
                child.vehicle_id = None
        return "Disembarked on land; the raft remains available to everyone."

    def _weapon(self, world, person):
        return next((item for item in world.items if item.id == person.equipped_item_id
                     and item.kind in {"spear", "stone_axe"} and item.durability > 0), None)

    def _predator_encounters(self, world):
        for animal in world.animals:
            if not animal.alive or animal.animal_type != "wild" or animal.species not in PREDATOR_SPECIES:
                continue
            targets = [person for person in world.agents if person.alive and not person.vehicle_id and self._distance(person, animal) <= 1]
            if not targets or animal.last_attack_tick == world.tick or animal.hunger < 30 or self._random.random() > 0.12:
                continue
            animal.last_attack_tick = world.tick
            target = min(targets, key=lambda person: self._distance(person, animal))
            # Witnessing a predator also affects nearby people, even if no one is injured.
            for witness in targets:
                witness.fear = min(100, witness.fear + (24 if witness.id == target.id else 12))
                witness.stress = min(100, witness.stress + 6)
            # A nearby caregiver may defend an infant with a real equipped weapon.
            guards = [person for person in targets if person.age_days >= ADULT_AGE_DAYS and self._weapon(world, person)]
            guard = next((person for person in guards if target.id in person.children_ids), target)
            weapon = self._weapon(world, guard)
            protected = self._has_shelter(world, target) or any(building.kind == "campfire" and building.condition >= 20
                         and self._distance(target, building) <= 1 for building in world.structures)
            if weapon:
                weapon.durability = max(0, weapon.durability - 8)
            defended = self._random.random() < (0.8 if weapon else 0.55 if protected else 0.15)
            damage = 0 if defended else max(1, self._random.randint(8, 22) // (2 if protected else 1))
            if defended:
                animal.health = max(0, animal.health - (30 if weapon else 3))
                animal.x, animal.y = max(self._habitable_neighbors(world, animal.x, animal.y),
                                         key=lambda point: self._distance_to(*point, target.x, target.y, world.width))
                animal.hunger = max(0, animal.hunger - 5)
                if animal.health <= 0:
                    animal.alive = False
                    self._add_food_resource(world, "meat", animal.x, animal.y, 3)
            else:
                self._hurt(world, target, damage, f"a {animal.species} attack")
                animal.hunger = max(0, animal.hunger - 20)
            self._remember(target, f"A {animal.species} attacked; {'defence kept you safe' if defended else 'you were injured'}.")
            self._record(world, EventSource.NATURAL, EventKind.PREDATOR_ATTACK,
                         f"A {animal.species} attacked {target.name}; {'the attack was repelled' if defended else str(damage) + ' health was lost'}.",
                         [target.id], {"animal_id": animal.id, "damage": damage, "defended": defended,
                                       "weapon": weapon.kind if weapon else None, "x": target.x, "y": target.y})

    def _defend(self, world, person, animal_id):
        animal = next((animal for animal in world.animals if animal.id == animal_id and animal.alive), None)
        if not animal or self._distance(person, animal) > 1:
            return "No threatening animal is within reach."
        weapon = self._weapon(world, person)
        if not weapon:
            return "A usable equipped weapon is needed for a deliberate defence."
        weapon.durability = max(0, weapon.durability - 5)
        person.energy = max(0, person.energy - 6)
        animal.x, animal.y = max(self._habitable_neighbors(world, animal.x, animal.y),
                                 key=lambda point: self._distance_to(*point, person.x, person.y, world.width))
        self._record(world, EventSource.AGENT_ACTION, EventKind.ACTION, f"{person.name} drove the predator away.",
                     [person.id], {"action": "defend", "animal_id": animal.id})
        return "Drove the threatening animal away with a weapon."

    def _flee(self, world, person):
        threats = [animal for animal in world.animals if animal.alive and animal.species in PREDATOR_SPECIES and self._distance(person, animal) <= 3]
        if not threats:
            return "No nearby predator to flee from."
        nx, ny = max(self._habitable_neighbors(world, person.x, person.y), key=lambda point:
                     min(self._distance_to(*point, animal.x, animal.y, world.width) for animal in threats))
        dx = (nx - person.x + world.width // 2) % world.width - world.width // 2
        return self._apply_action(world, person, AgentAction(action="move", dx=dx, dy=ny - person.y, reason="Flee a predator"))
