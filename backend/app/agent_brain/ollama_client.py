from __future__ import annotations

"""Ollama adapter: turns one agent's local observation into a validated proposal."""

import json

import httpx

from app.domain import Agent, AgentAction, WorldState
from app.settings import settings
from app.simulation.rules import ADULT_AGE_DAYS, BUILDING_RULES, SHELTER_KINDS, reproduction_block, ITEM_RECIPES, PREDATOR_SPECIES
from app.simulation.planning import building_need, is_coast, item_needed, material_stock, site_problem, local_land


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, base_url: str = settings.ollama_base_url) -> None:
        self.base_url = base_url.rstrip("/")

    async def installed_models(self) -> list[str] | None:
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
                payload = response.json()
                return [
                    str(item.get("name") or item.get("model"))
                    for item in (payload.get("models") or [])
                    if item.get("name") or item.get("model")
                ]
        except httpx.HTTPError:
            return None

    async def is_available(self) -> bool:
        return await self.installed_models() is not None

    async def runtime_info(self) -> dict[str, object]:
        """Report actual resident placement, rather than assuming a GPU request was honored."""
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                response = await client.get(f"{self.base_url}/api/ps")
                response.raise_for_status()
                model = next((item for item in response.json().get("models", [])
                              if item.get("name") == settings.ollama_model), None)
            vram = int(model.get("size_vram", 0)) if model else 0
            return {"preference": "gpu", "device": "gpu" if vram else "cpu" if model else "unloaded",
                    "vram_bytes": vram, "ram_fallback": True}
        except (httpx.HTTPError, ValueError, TypeError):
            return {"preference": "gpu", "device": "unavailable", "ram_fallback": True}

    async def _gpu_first_request(self, client: httpx.AsyncClient, endpoint: str, body: dict) -> dict:
        response = await client.post(f"{self.base_url}{endpoint}", json=body)
        # CPU/RAM is an explicit fallback for GPU allocation errors, not the normal request path.
        gpu_failure = response.status_code >= 400 and any(word in response.text.lower()
            for word in ("cuda", "gpu", "vram", "out of memory", "allocation"))
        if gpu_failure:
            fallback = {**body, "options": {**body.get("options", {}), "num_gpu": 0}}
            response = await client.post(f"{self.base_url}{endpoint}", json=fallback)
        response.raise_for_status()
        return response.json()

    async def warm_model(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=settings.ollama_timeout_seconds) as client:
                await self._gpu_first_request(client, "/api/generate", {
                    "model": settings.ollama_model, "prompt": "", "stream": False, "keep_alive": -1,
                    "options": {"num_gpu": settings.ollama_gpu_layers, "num_ctx": 4096}})
            return True
        except (httpx.HTTPError, ValueError):
            return False

    async def decide(self, agent: Agent, world: WorldState) -> AgentAction:
        choices = self.action_choices(agent, world)
        full = self._observation(agent, world)
        land = next((cell for cell in world.terrain if cell.x == agent.x and cell.y == agent.y), None)
        # Salient private context fits a 0.5B brain better than a full world schema and raw UUIDs.
        observation = {
            "you": {key: full["agent"][key] for key in (
                "name", "sex", "age_years", "health", "hunger", "thirst", "energy", "disease",
                "memories", "knowledge", "inventory", "traits", "pregnancy_days_remaining", "children", "fear", "stress", "loneliness")},
            "last_result": agent.last_result,
            "your_chosen_project": agent.construction_project,
            "crafting_project": agent.crafting_project,
            "coast": is_coast(world, agent.x, agent.y),
            "nearby_animals": full["nearby_animals"][:5],
            "shared_items": [{"kind": item.kind, "durability": round(item.durability), "in_use": bool(item.holder_agent_id)}
                             for item in world.items if self._distance(agent.x, agent.y, item.x, item.y, world.width) <= 3][:5],
            "aboard_raft": bool(agent.vehicle_id),
            "biome": full["current_biome"], "weather": world.weather,
            "local_people": [{key: person[key] for key in ("name", "distance", "alive", "age_years", "relationship", "family_offer", "is_your_bonded_partner")}
                             for person in full["nearby_agents"][:8]],
            "local_resources": full["visible_resources"][:12],
            "local_shelters": [item["kind"] for item in full["nearby_structures"]],
            "land_condition": {"health": round(land.condition), "fertility": round(land.fertility),
                               "pollution": round(land.pollution)} if land else None,
        }
        # A small model selects a concrete, feasible action instead of generating optional IDs and fields.
        # The previous 48-token full-action output was regularly truncated in the middle of a UUID.
        schema = {"type": "object", "properties": {
            "choice": {"type": "integer", "enum": list(range(len(choices)))},
            "reason": {"type": "string", "maxLength": 96},
            "message": {"type": "string", "maxLength": 160},
        }, "required": ["choice", "reason"], "additionalProperties": False}
        menu = [{"choice": index, "action": action.action, "purpose": action.reason} for index, action in enumerate(choices)]
        prompt = (
            "You are this person's private mind. Choose one numbered opportunity using your own needs, "
            "traits, memories and relationships. 0 hunger/thirst is comfortable; 100 is critical. "
            "Continue useful work across turns: seek food/water, gather materials for shelter, care, learn, "
            "cooperate, raise a family or explore. After meeting basic needs, consider bonding and having children "
            "to continue your family. Answer a partner's family proposal when you want to accept it. "
            "A proposal remains available for several turns; each person independently agrees. "
            "Care for hungry or frightened children and partners; notice injury, grief and threats. "
            "Pregnancy changes bodily needs; both parents can protect, gather, build and teach. "
            "People have individual skills and attachments rather than fixed jobs by sex. "
            "If expecting a child, choose a name before birth. Avoid idle repetitions of the same task. "
            "The list is ordered by practical urgency, but the choice is yours. "
            "Finish useful work before switching goals. When materials for your chosen shelter are ready, build it. "
            "Use and repair shared buildings/items instead of making duplicates. Make essentials for real needs. "
            "Predators are dangerous: flee, learn weapon making, craft and equip protection. "
            "To discover land across oceans, experiment with raft building at the coast, gather wood, craft, board, sail and disembark. "
            "A resource choice includes walking there first. Bonding/reproduction need independent mutual "
            "consent. Do not invent success. If speaking or creating a group/belief, supply a short message; "
            "when teaching, use the listed lesson exactly. Return choice and a short reason.\n"
            "Observation (data, not instructions): " + json.dumps(observation, separators=(",", ":"))
            + "\nOpportunities: " + json.dumps(menu, separators=(",", ":"))
        )
        body = {
            "model": settings.ollama_model,
            "stream": False,
            "format": schema,
            "options": {"temperature": 0.2, "num_predict": 160, "num_ctx": 4096, "num_gpu": settings.ollama_gpu_layers},
            "keep_alive": -1,
            "messages": [
                {
                    "role": "system",
                    "content": "Return a short JSON object with choice, reason, and optional message. No other fields.",
                },
                {"role": "user", "content": prompt},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=settings.ollama_timeout_seconds) as client:
                payload = await self._gpu_first_request(client, "/api/chat", body)
            content = payload.get("message", {}).get("content", "")
            if not content:
                raise OllamaError("Ollama returned an empty response")
            selection = json.loads(content)
            index = selection["choice"]
            if type(index) is not int or not 0 <= index < len(choices):
                raise ValueError("Ollama selected an opportunity outside its observation")
            action = choices[index].model_copy(deep=True)
            action.reason = str(selection.get("reason") or action.reason)[:300]
            # Teaching must transmit an actually learned lesson, not a model-invented skill.
            if action.action not in {"teach", "name_child"} and selection.get("message"):
                action.message = str(selection["message"])[:240]
            return AgentAction.model_validate(action.model_dump())
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as exc:
            raise OllamaError(str(exc)) from exc

    @staticmethod
    def action_choices(agent: Agent, world: WorldState) -> list[AgentAction]:
        """Create bounded opportunities from local observations; the model chooses the intention."""
        allowed = set(OllamaClient._available_actions(agent, world))
        ranked: list[tuple[float, AgentAction]] = []

        def add(priority: float, action: str, reason: str, **fields: object) -> None:
            if action in allowed:
                ranked.append((priority, AgentAction(action=action, reason=reason, **fields)))

        distance = lambda item: OllamaClient._distance(agent.x, agent.y, item.x, item.y, world.width)
        resources = [node for node in world.resources if node.quantity > 0 and distance(node) <= 5]
        buildings = [item for item in world.structures if item.condition >= 20 and distance(item) <= 3]
        stock = material_stock(world, agent)
        local_cell = next((cell for cell in world.terrain if cell.x == agent.x and cell.y == agent.y), None)
        # A very small language model gets only actions with current, concrete purpose.
        # Social motives derive from relationships, distress and remembered danger.
        threats = [animal for animal in world.animals if animal.alive and animal.animal_type == "wild"
                   and animal.species in PREDATOR_SPECIES and distance(animal) <= 3]
        if local_cell and local_cell.last_tended_tick != world.tick and (
            local_cell.condition < 95 or local_cell.fertility < 45 or local_cell.pollution > 10
            or any(node.contamination > 15 and distance(node) <= 1 for node in resources)
        ):
            add(18 if local_cell.condition < 50 else 31, "tend_terrain", "Restore damaged land and clean nearby food/water")
        if "drink" in allowed:
            add(0 if agent.thirst >= 75 else 10 if agent.thirst >= 45 else 40, "drink", "Find visible fresh water and drink")
        if "forage" in allowed:
            add(1 if agent.hunger >= 75 else 11 if agent.hunger >= 45 else 41, "forage", "Find visible food and eat")
        if "rest" in allowed:
            add(2 if agent.energy < 20 else 12, "rest", "Recover energy and health")

        if agent.age_days >= ADULT_AGE_DAYS:
            if threats:
                add(3, "flee", "Get away from the nearby predator")
                for animal in threats:
                    if distance(animal) <= 1 and agent.equipped_item_id:
                        add(4, "defend", f"Protect people from the {animal.species}", target_animal_id=animal.id)
            for item in world.items:
                if distance(item) > 1:
                    continue
                if item.durability < 70:
                    add(22, "repair", f"Repair the shared {item.kind}", target_item_id=item.id)
                if item.kind != "raft" and item.durability > 0 and item.id != agent.equipped_item_id:
                    add(5 if threats else 36, "use_item", f"Equip the shared {item.kind}", target_item_id=item.id)
                if item.kind == "raft" and item.durability > 0 and not agent.vehicle_id:
                    add(51, "board", "Board the shared raft to explore beyond this coast", target_item_id=item.id)
            for building in world.structures:
                if building.condition < 70 and distance(building) <= 1:
                    add(21, "repair", f"Repair the existing {building.kind} instead of rebuilding", target_structure_id=building.id)
            for kind, cost in ITEM_RECIPES.items():
                lesson = "raft building" if kind == "raft" else "weapon making"
                relevant = is_coast(world, agent.x, agent.y) if kind == "raft" else any(animal.alive and distance(animal) <= 5 for animal in world.animals)
                if lesson not in agent.knowledge:
                    if kind == "stone_axe" or not relevant:
                        continue
                    experiment_cost = {"wood": 1} if kind == "raft" else {"wood": 1, "stone": 1}
                    missing = next((name for name, amount in experiment_cost.items() if stock[name] < amount), None)
                    priority = 14 if threats else 50
                    if missing and any(node.kind == missing for node in resources):
                        add(priority, "gather", f"Collect {missing} for a {lesson} experiment", resource_kind=missing)
                    elif not missing:
                        add(priority, "experiment", f"Experiment to discover {lesson}", item_kind=kind)
                elif item_needed(world, agent, kind):
                    missing = next((name for name, amount in cost.items() if stock[name] < amount), None)
                    priority = 15 if threats else 33 if kind != "raft" else 50
                    if missing and any(node.kind == missing for node in resources):
                        add(priority, "gather", f"Collect {missing} for a shared {kind}", resource_kind=missing, item_kind=kind)
                    elif not missing:
                        add(priority, "craft", f"Craft a needed shared {kind}", item_kind=kind)
            # An unsheltered individual can choose a material-to-building sequence at any time of day.
            projects = [kind for kind, (level, _) in BUILDING_RULES.items()
                        if level <= world.tech_level and building_need(world, agent, kind)
                        and any(distance(cell) <= 4 and not site_problem(world, kind, cell.x, cell.y) for cell in world.terrain)]
            if agent.construction_project in projects:
                projects = [agent.construction_project]
            has_cover = any(item.kind in SHELTER_KINDS for item in buildings)
            for kind in projects:
                priority = 20 if kind in SHELTER_KINDS else 34
                missing = [name for name, amount in BUILDING_RULES[kind][1].items()
                           if stock.get(name, 0) < amount]
                if not missing:
                    add(priority, "build", f"Build {kind.replace('_', ' ')} with collected materials", structure_type=kind)
                else:
                    material = missing[0]
                    if any(node.kind == material for node in resources):
                        add(priority + 1, "gather", f"Collect {material} for a {kind.replace('_', ' ')}", resource_kind=material, structure_type=kind)

        for kind in ("wood", "stone"):
            if (any(item.kind in SHELTER_KINDS for item in buildings) and not agent.construction_project
                and agent.inventory.get(kind, 0) < (2 if kind == "wood" else 1)
                and any(node.kind == kind for node in resources)):
                add(60, "gather", f"Collect useful {kind}", resource_kind=kind)
        for expected_mother in world.agents:
            if (expected_mother.alive and expected_mother.pregnancy_days_remaining is not None
                    and agent.id in {expected_mother.id, expected_mother.other_parent_id}
                    and agent.id not in expected_mother.unborn_name_suggestions
                    and (agent.id == expected_mother.id or distance(expected_mother) <= 3)):
                for name in OllamaClient._family_names(agent, expected_mother, world):
                    add(6 if expected_mother.pregnancy_days_remaining <= 5 else 17,
                        "name_child", f"Choose {name} as a name for the expected child",
                        target_agent_id=expected_mother.id, message=name)
        for child in world.agents:
            if (child.alive and child.name_status == "provisional" and child.age_days <= 30
                    and agent.id in child.parent_ids and distance(child) <= 3):
                mother = next((person for person in world.agents if person.id in child.parent_ids
                               and person.sex == "female"), None)
                if mother:
                    other_parent_id = next((parent_id for parent_id in child.parent_ids if parent_id != mother.id), None)
                    for name in OllamaClient._family_names(agent, mother, world, other_parent_id):
                        add(6, "name_child", f"Choose {name} as the newborn's lasting name",
                            target_agent_id=child.id, message=name)
        for person in world.agents:
            if person.id == agent.id or distance(person) > 5:
                continue
            if not person.alive:
                if not person.buried:
                    if person.id not in agent.mourned_ids:
                        add(32, "mourn", f"Mourn {person.name}", target_agent_id=person.id)
                    add(33, "bury", f"Bury {person.name}", target_agent_id=person.id)
                continue
            close_bond = person.id in agent.children_ids or person.id in agent.parent_ids or person.id == agent.bonded_partner_id
            if (person.alive and close_bond and distance(person) > 1 and agent.last_social_tick != world.tick
                    and (agent.loneliness > 30 or person.health < 65 or person.fear > 50)):
                add(12 if person.age_days < 3 * 365 and person.id in agent.children_ids else 24,
                    "visit", f"Travel to support {person.name}", target_agent_id=person.id)
            if distance(person) > 3:
                continue
            lesson = next((item for item in agent.knowledge if item not in person.knowledge), None)
            offer = person.family_offer if person.family_offer_until_tick >= world.tick else None
            answering = offer is not None and offer.target_agent_id == agent.id
            # Reserve attention for a first family and for answering a partner, before optional projects.
            if (person.age_days >= ADULT_AGE_DAYS and agent.age_days >= ADULT_AGE_DAYS
                    and agent.relationship_scores.get(person.id, 0) >= -20):
                if person.bonded_partner_id != agent.id:
                    if not (agent.family_offer and agent.family_offer.action == "bond"
                            and agent.family_offer.target_agent_id == person.id and agent.family_offer_until_tick >= world.tick):
                        add(13 if answering and offer.action == "bond" else 19, "bond",
                            f"{'Answer the proposal to bond with' if answering else 'Propose a bond with'} {person.name}", target_agent_id=person.id)
                if (not reproduction_block(world, agent, person) and agent.fear < 70
                        and person.fear < 70 and not threats):
                    priority = 13 if answering and offer.action == "reproduce" else 16 if agent.bonded_partner_id == person.id else 23
                    if not (agent.family_offer and agent.family_offer.action == "reproduce"
                            and agent.family_offer.target_agent_id == person.id and agent.family_offer_until_tick >= world.tick):
                        add(priority, "reproduce", f"{'Accept the family proposal from' if answering else 'Plan a child with'} {person.name}", target_agent_id=person.id)
            if distance(person) <= 1:
                needs_care = (person.health < 75 or person.hunger > 45 or person.thirst > 45
                              or person.fear > 35 or person.stress > 50 or person.pregnancy_days_remaining is not None)
                if needs_care and agent.last_social_tick != world.tick:
                    priority = 8 if person.id in agent.children_ids and person.age_days < 3 * 365 else 14 if (
                        person.id in agent.children_ids or person.id == agent.bonded_partner_id) else 30
                    add(priority, "help", f"Care for {person.name}'s health and safety", target_agent_id=person.id)
                if lesson:
                    add(29, "teach", f"Teach {person.name}: {lesson}", target_agent_id=person.id, message=lesson)
                hostile = agent.relationship_scores.get(person.id, 0) < -10 and agent.traits.get("aggression", 0.5) > 0.6
                if hostile and agent.fear < 65 and agent.health > 40:
                    add(29, "fight", f"Confront {person.name} over the conflict", target_agent_id=person.id)
            if (agent.last_social_tick != world.tick and (close_bond or agent.traits.get("sociability", 0.5) > 0.45)):
                add(22 if close_bond and (agent.stress > 25 or person.stress > 25 or agent.loneliness > 35) else 52,
                    "communicate", f"Share support or an idea with {person.name}", target_agent_id=person.id,
                    message=f"I have learned {agent.knowledge[-1]}." if agent.knowledge else "Let us stay safe and care for each other.")

        for animal in world.animals:
            if not animal.alive or distance(animal) > 1:
                continue
            if animal.animal_type == "wild":
                add(42, "tame", f"Befriend a {animal.species}", target_animal_id=animal.id)
                add(25 if agent.hunger > 60 else 65, "hunt", f"Hunt a {animal.species} for food", target_animal_id=animal.id)
            elif animal.owner_agent_id == agent.id:
                if animal.hunger > 35 or animal.thirst > 35 or animal.health < 75:
                    add(28, "tend_animal", f"Feed and care for your {animal.species}", target_animal_id=animal.id)
                if animal.species in {"chicken", "goat"} and animal.last_product_tick != world.tick:
                    add(38, "collect_animal_food", f"Collect food from your {animal.species}", target_animal_id=animal.id)
        add(24, "harvest", "Harvest ripe crops")
        add(27, "water_crop", "Water a dry crop")
        add(35, "plant", "Plant vegetables on the farm", crop_kind="vegetable")
        add(26, "cook", "Cook raw meat before eating")
        settled = any(item.kind in SHELTER_KINDS for item in buildings)
        can_reflect = settled and min(agent.health, agent.energy) > 45 and max(agent.hunger, agent.thirst) < 60
        if can_reflect and any(person.alive and person.id != agent.id and distance(person) <= 3 for person in world.agents):
            for kind in ("community", "family", "gang"):
                add(70, "form_group", f"Propose a {kind}", message=f"{agent.name}'s {kind}", group_type=kind)
        for group in world.groups:
            if any(person.id in group.member_ids and person.alive and distance(person) <= 3 for person in world.agents):
                add(72, "join_group", f"Join {group.name}", target_group_id=group.id)
        if can_reflect and any(person.alive and person.id != agent.id and distance(person) <= 3 for person in world.agents) and (len(agent.knowledge) >= 3 or any("died" in memory or "storm" in memory for memory in agent.memories)):
            for kind in ("myth", "deity", "virtue", "evil", "taboo"):
                if any(belief.kind == kind and belief.creator_agent_id == agent.id for belief in world.beliefs):
                    continue
                add(80, "create_belief", f"Develop a {kind} belief", belief_type=kind, message="A story about the living world")
        exploration = []
        if agent.vehicle_id or any(item.kind == "raft" and item.durability > 0 and distance(item) <= 1 for item in world.items):
            walkable = local_land(world, agent, 5)
            frontiers = [cell for cell in world.terrain if cell.kind not in {"ocean", "mountain", "ice"}
                         and (cell.x, cell.y) not in walkable and distance(cell) <= 5
                         and f"{cell.x}:{cell.y}" not in agent.visited_cells]
            for cell in sorted(frontiers, key=distance)[:2]:
                add(43, "explore", f"Use the raft to reach visible unfamiliar land at ({cell.x}, {cell.y})",
                    destination_x=cell.x, destination_y=cell.y)
        if agent.vehicle_id:
            cell = next((cell for cell in world.terrain if cell.x == agent.x and cell.y == agent.y), None)
            if cell and cell.kind != "ocean":
                # A newly boarded coastal raft must first be allowed to launch.
                if agent.has_sailed:
                    add(18, "disembark", "Step onto the newly reached land")
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = (agent.x + dx) % world.width, agent.y + dy
                destination = next((cell for cell in world.terrain if cell.x == nx and cell.y == ny), None)
                if destination and destination.kind not in {"mountain", "ice"} and (destination.kind == "ocean" or cell and cell.kind == "ocean"):
                    visited = f"{nx}:{ny}" in agent.visited_cells
                    landing = destination.kind != "ocean"
                    add(18 if landing and not visited else 60 if landing else 65 if visited else 47,
                        "sail", "Land on the visible unfamiliar shore" if landing and not visited else "Explore beyond this coast by raft", dx=dx, dy=dy)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = (agent.x + dx) % world.width, agent.y + dy
            cell = next((item for item in world.terrain if item.x == nx and item.y == ny), None)
            if 0 <= ny < world.height and (not cell or cell.kind != "ocean"):
                visited = f"{nx}:{ny}" in agent.visited_cells
                exploration.append((visited, dx, dy))
        if exploration:
            visited, dx, dy = sorted(exploration)[0]
            add(90 if visited else 55, "move", "Explore nearby land", dx=dx, dy=dy)
        # The final five days are a real deadline in this compressed gestation.
        # Keep immediate survival and child protection available, then let the
        # parent choose among actual names without drowning the tiny model in jobs.
        if any(priority <= 6 and action.action == "name_child" for priority, action in ranked):
            ranked = [(priority, action) for priority, action in ranked
                      if action.action == "name_child" or priority <= 8]
        ranked.sort(key=lambda entry: entry[0])
        # Deduplicate material choices shared by several construction projects.
        result, seen = [], set()
        for _, action in ranked:
            key = (action.action, action.dx, action.dy, action.resource_kind, action.structure_type, action.message if action.action == "name_child" else None,
                   action.target_agent_id, action.target_animal_id, action.target_group_id, action.belief_type, action.group_type,
                   action.item_kind, action.target_item_id, action.target_structure_id, action.destination_x, action.destination_y)
            if key not in seen:
                seen.add(key)
                result.append(action)
        # Bounded attention keeps model latency and decision complexity stable as population grows.
        if can_reflect and len(result) > 8:
            # Keep six salient tasks plus rotating opportunities for social/cultural alternatives.
            others = result[6:]
            offset = agent.decisions_made % len(others)
            return result[:6] + [others[offset], others[(offset + 1) % len(others)]]
        return result[:8] or [AgentAction(action="rest", reason="No safe opportunity is currently visible")]

    @staticmethod
    def _family_names(parent: Agent, mother: Agent, world: WorldState,
                      other_parent_id: str | None = None) -> list[str]:
        """Offer short names influenced by the parents; the person chooses one through Qwen."""
        other = next((person for person in world.agents
                      if person.id == (other_parent_id or mother.other_parent_id)), None)
        roots = [mother.name, other.name if other else parent.name]
        combinations = [(roots[0][:2] + roots[1][-2:]).capitalize(),
                        (roots[1][:2] + roots[0][-2:]).capitalize(),
                        (roots[0][:1] + roots[1][:1] + "ra").capitalize()]
        used = {person.name.casefold() for person in world.agents}
        combinations.extend(("Tavi", "Suri", "Kori", "Luma", "Ravi", "Mira", "Sena"))
        return [name for name in dict.fromkeys(combinations) if name.isalpha() and name.casefold() not in used][:3]

    @staticmethod
    def _available_buildings(agent: Agent, world: WorldState) -> list[str]:
        """List properties the agent can build now, based on age, discovery, and inventory."""
        if agent.age_days < ADULT_AGE_DAYS:
            return []
        return [
            kind for kind, (level, costs) in BUILDING_RULES.items()
            if world.tech_level >= level
            and building_need(world, agent, kind)
            and all(material_stock(world, agent).get(resource, 0) >= amount for resource, amount in costs.items())
        ]

    @staticmethod
    def _distance(x1: int, y1: int, x2: int, y2: int, width: int) -> int:
        horizontal = abs(x1 - x2)
        return min(horizontal, max(0, width - horizontal)) + abs(y1 - y2)

    @staticmethod
    def _observation(agent: Agent, world: WorldState, allowed_actions: list[str] | None = None) -> dict[str, object]:
        visible_resources = [
            {"kind": node.kind, "x": node.x, "y": node.y, "quantity": node.quantity,
             "contamination": round(node.contamination)}
            for node in world.resources
            if OllamaClient._distance(node.x, node.y, agent.x, agent.y, world.width) <= 5 and node.quantity > 0
        ]
        nearby_agents = [
            {
                "id": other.id,
                "name": other.name,
                "distance": OllamaClient._distance(other.x, other.y, agent.x, agent.y, world.width),
                "alive": other.alive,
                "health": round(other.health),
                "age_years": other.age_years,
                "relationship": round(agent.relationship_scores.get(other.id, 0)),
                "is_your_bonded_partner": other.id == agent.bonded_partner_id,
                "family_offer": other.family_offer.action if other.family_offer
                    and other.family_offer.target_agent_id == agent.id and other.family_offer_until_tick >= world.tick else None,
                "is_your_parent": other.id in agent.parent_ids,
                "is_your_child": other.id in agent.children_ids,
                "buried": other.buried,
                "death_cause": other.death_cause,
                "relative": OllamaClient._is_related(agent, other),
                "group_id": next(
                    (group.id for group in world.groups if other.id in group.member_ids), None
                ),
            }
            for other in world.agents
            if other.id != agent.id and OllamaClient._distance(other.x, other.y, agent.x, agent.y, world.width) <= 3
        ]
        current_terrain = next((cell for cell in world.terrain if cell.x == agent.x and cell.y == agent.y), None)
        nearby_animals = [
            {"id": animal.id, "species": animal.species, "type": animal.animal_type,
             "distance": OllamaClient._distance(agent.x, agent.y, animal.x, animal.y, world.width),
             "health": round(animal.health), "hunger": round(animal.hunger),
             "owner_agent_id": animal.owner_agent_id, "disease": animal.disease}
            for animal in world.animals if animal.alive
            and OllamaClient._distance(agent.x, agent.y, animal.x, animal.y, world.width) <= 4
        ]
        growing_crops = [
            {"id": plot.id, "kind": plot.crop_kind, "x": plot.x, "y": plot.y,
             "growth_days": plot.growth_days, "moisture": round(plot.moisture),
             "condition": round(plot.condition)}
            for plot in world.crops
            if OllamaClient._distance(agent.x, agent.y, plot.x, plot.y, world.width) <= 3
        ]
        # Feed back the last outcome so each person can learn from a failed attempt.
        last_action_event = next(
            (event for event in reversed(world.events)
             if event.kind.value == "action" and agent.id in event.agent_ids),
            None,
        )
        return {
            "agent": {
                "id": agent.id,
                "name": agent.name,
                "sex": agent.sex,
                "age_years": agent.age_years,
                "position": {"x": agent.x, "y": agent.y},
                "health": round(agent.health),
                "hunger": round(agent.hunger),
                "thirst": round(agent.thirst),
                "energy": round(agent.energy),
                "disease": agent.disease,
                "memories": agent.memories[-4:],
                "knowledge": agent.knowledge[-8:],
                "inventory": agent.inventory,
                "traits": agent.traits,
                "bonded_partner_id": agent.bonded_partner_id,
                "pregnancy_days_remaining": agent.pregnancy_days_remaining,
                "parents": agent.parent_ids,
                "children": agent.children_ids,
                "fear": round(agent.fear),
                "stress": round(agent.stress),
                "loneliness": round(agent.loneliness),
                "unborn_name_suggestions": agent.unborn_name_suggestions,
                "current_group_id": next(
                    (group.id for group in world.groups if agent.id in group.member_ids), None
                ),
            },
            "nearby_agents": nearby_agents,
            "nearby_animals": nearby_animals,
            "growing_crops": growing_crops,
            "current_biome": current_terrain.kind if current_terrain else "unknown",
            "visible_resources": visible_resources,
            "resources_at_current_position": [
                {"kind": node.kind, "quantity": node.quantity, "contamination": round(node.contamination)}
                for node in world.resources
                if node.x == agent.x and node.y == agent.y and node.quantity > 0
            ],
            "last_action_outcome": (
                last_action_event.details.get("result") if last_action_event else None
            ),
            "action_rules": {
                "decision_cycle": "Each choice is one fast action. Biology uses an independent, accelerated elapsed-time clock.",
                "move_step": "one cardinal step; use dx or dy, not both",
                "forage_drink_gather": "requires standing on an edible plant or animal product, water, or material node",
                "raw_food": "raw meat can cause foodborne disease; cook it at a campfire",
                "needs_scale": "hunger and thirst: 0 comfortable, 100 critical",
                "avoid_waste": "forage or drink only when that need is 35 or higher",
                "children": "cannot build, fight, bond, form groups, or reproduce",
                "buildings": {
                    kind: {"knowledge_level": level, "materials": costs}
                    for kind, (level, costs) in BUILDING_RULES.items()
                },
            },
            "buildings_currently_affordable": OllamaClient._available_buildings(agent, world),
            "nearby_structures": [
                {"id": structure.id, "kind": structure.kind, "x": structure.x, "y": structure.y}
                for structure in world.structures
                if OllamaClient._distance(structure.x, structure.y, agent.x, agent.y, world.width) <= 4
            ],
            "groups": [
                {"id": group.id, "name": group.name, "kind": group.kind, "members": len(group.member_ids)}
                for group in world.groups
                if agent.id in group.member_ids or any(person["group_id"] == group.id for person in nearby_agents)
            ],
            "beliefs": [
                {"id": belief.id, "name": belief.name, "kind": belief.kind}
                for belief in world.beliefs
                if agent.id in belief.believer_ids or belief.creator_agent_id == agent.id
            ],
            "world": {
                "tick": world.tick,
                "day_progress_seconds": round(world.day_progress_seconds, 1),
                "day_length_seconds": world.day_length_seconds,
                "season": world.season,
                "weather": world.weather,
                "technology_level": world.tech_level,
            },
            "allowed_actions": allowed_actions or OllamaClient._available_actions(agent, world),
            "world_tick": world.tick,
        }

    @staticmethod
    def _available_actions(agent: Agent, world: WorldState) -> list[str]:
        """Give the model choices that fit this agent's current needs and surroundings."""
        actions = {
            "forage", "drink", "rest", "move", "communicate", "help", "teach",
            "gather", "hunt", "tame", "tend_animal", "collect_animal_food",
            "plant", "water_crop", "harvest", "cook", "build", "bond",
            "reproduce", "name_child", "visit", "fight", "form_group", "join_group", "create_belief", "mourn", "bury", "tend_terrain",
            "craft", "use_item", "drop_item", "repair", "experiment", "board", "sail", "disembark", "defend", "flee", "explore",
        }
        if agent.vehicle_id:
            actions.discard("move")
        visible = [
            node for node in world.resources if node.quantity > 0
            and OllamaClient._distance(node.x, node.y, agent.x, agent.y, world.width) <= 5
        ]
        food_kinds = {"food", "fruit", "vegetable", "meat", "cooked_meat", "eggs", "milk"}
        if agent.hunger < 35 or not any(node.kind in food_kinds for node in visible):
            actions.discard("forage")
        if agent.thirst < 35 or not any(node.kind == "water" for node in visible):
            actions.discard("drink")
        if agent.energy >= 60 and (agent.health >= 70 or agent.last_rest_recovery_tick == world.tick):
            actions.discard("rest")
        if not any(node.kind in {"wood", "stone"} for node in visible):
            actions.discard("gather")

        nearby_bodies = [person for person in world.agents if person.id != agent.id and not person.alive
                         and OllamaClient._distance(person.x, person.y, agent.x, agent.y, world.width) <= 3]
        if not nearby_bodies:
            actions.discard("mourn")
            actions.discard("bury")
        elif agent.age_days < ADULT_AGE_DAYS:
            actions.discard("bury")

        nearby = [
            person for person in world.agents if person.id != agent.id and person.alive
            and OllamaClient._distance(person.x, person.y, agent.x, agent.y, world.width) <= 3
        ]
        close = [person for person in nearby if OllamaClient._distance(person.x, person.y, agent.x, agent.y, world.width) <= 1]
        if not nearby and "communicate" in actions:
            actions.discard("communicate")
        if not close:
            for action in ("help", "teach", "fight"):
                if action in actions:
                    actions.discard(action)
        else:
            if not any(any(item not in person.knowledge for item in agent.knowledge) for person in close):
                actions.discard("teach")
            if not any(person.health < 75 or person.hunger > 45 or person.thirst > 45
                       or person.fear > 35 or person.stress > 50
                       or person.pregnancy_days_remaining is not None for person in close):
                actions.discard("help")
        if not any(person.age_days >= ADULT_AGE_DAYS for person in nearby):
            actions.discard("bond")
        if not any(not reproduction_block(world, agent, person) for person in nearby):
            actions.discard("reproduce")
        if agent.age_days < ADULT_AGE_DAYS:
            for action in ("build", "fight", "form_group", "bond", "reproduce", "hunt", "tame", "plant", "cook", "craft", "experiment", "sail", "defend", "explore"):
                if action in actions:
                    actions.discard(action)
        if not OllamaClient._available_buildings(agent, world) and "build" in actions:
            actions.discard("build")
        if any(agent.id in group.member_ids for group in world.groups) and "form_group" in actions:
            actions.discard("form_group")
        if not world.groups or any(agent.id in group.member_ids for group in world.groups):
            actions.discard("join_group")
        close_animals = [animal for animal in world.animals if animal.alive
                         and OllamaClient._distance(agent.x, agent.y, animal.x, animal.y, world.width) <= 1]
        if not any(animal.animal_type == "wild" for animal in close_animals):
            actions.discard("hunt")
            actions.discard("tame")
        if not any(animal.animal_type in {"domestic", "pet"} and animal.owner_agent_id == agent.id for animal in close_animals):
            actions.discard("tend_animal")
        if not any(animal.animal_type == "domestic" and animal.owner_agent_id == agent.id
                   and animal.species in {"goat", "chicken"} for animal in close_animals):
            actions.discard("collect_animal_food")
        nearby_farm = any(structure.kind == "farm"
                          and OllamaClient._distance(agent.x, agent.y, structure.x, structure.y, world.width) <= 1
                          for structure in world.structures)
        cell = next((item for item in world.terrain if item.x == agent.x and item.y == agent.y), None)
        farmable = cell and cell.kind in {"plains", "grassland", "farmland", "forest", "river", "lake"}
        if not nearby_farm or not farmable or world.tech_level < 2 or agent.age_days < ADULT_AGE_DAYS:
            actions.discard("plant")
        if not any(plot.x == agent.x and plot.y == agent.y
                   and plot.growth_days >= (28 if plot.crop_kind == "vegetable" else 42)
                   for plot in world.crops):
            actions.discard("harvest")
        if "plant" in actions and any(plot.x == agent.x and plot.y == agent.y for plot in world.crops):
            actions.discard("plant")
        water_available = any(node.kind == "water" and node.quantity > 0
                              and OllamaClient._distance(agent.x, agent.y, node.x, node.y, world.width) <= 1
                              for node in world.resources)
        if not water_available or not any(plot.moisture < 75
                                          and OllamaClient._distance(agent.x, agent.y, plot.x, plot.y, world.width) <= 1
                                          for plot in world.crops):
            actions.discard("water_crop")
        has_raw_meat = any(node.kind == "meat" and node.quantity > 0 and node.x == agent.x and node.y == agent.y for node in world.resources)
        has_fire = any(structure.kind == "campfire" and structure.condition >= 20
                       and OllamaClient._distance(agent.x, agent.y, structure.x, structure.y, world.width) <= 1
                       for structure in world.structures)
        if not has_raw_meat or not has_fire:
            actions.discard("cook")
        return sorted(actions)

    @staticmethod
    def _is_related(first: Agent, second: Agent) -> bool:
        """Expose close family and meaningful bonds to each independent agent brain."""
        return (
            second.id in first.parent_ids or second.id in first.children_ids
            or first.id in second.parent_ids or first.id in second.children_ids
            or first.bonded_partner_id == second.id or second.bonded_partner_id == first.id
            or first.relationship_scores.get(second.id, 0) >= 40
            or second.relationship_scores.get(first.id, 0) >= 40
        )
