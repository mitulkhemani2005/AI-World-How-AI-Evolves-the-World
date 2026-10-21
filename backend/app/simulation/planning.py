"""Shared needs, site and material rules used by both private brains and the world resolver."""

from app.domain import Agent, WorldState
from app.simulation.rules import FOOD_KINDS, SHELTER_CAPACITY, SHELTER_KINDS


def distance(world: WorldState, x: int, y: int, nx: int, ny: int) -> int:
    horizontal = abs(x - nx) % world.width
    return min(horizontal, world.width - horizontal) + abs(y - ny)


def is_coast(world: WorldState, x: int, y: int) -> bool:
    cells = {(cell.x, cell.y): cell.kind for cell in world.terrain}
    return cells.get((x, y)) not in {None, "ocean", "lake", "river"} and any(
        cells.get(((x + dx) % world.width, y + dy)) == "ocean"
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))


def local_land(world: WorldState, agent: Agent, radius: int = 3) -> set[tuple[int, int]]:
    """A nearby building across an ocean channel does not serve this settlement."""
    kinds = {(cell.x, cell.y): cell.kind for cell in world.terrain}
    start = (agent.x, agent.y)
    reached, queue = {start}, [start]
    for x, y in queue:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            point = ((x + dx) % world.width, y + dy)
            if point not in reached and kinds.get(point) not in {None, "ocean"} and distance(world, *start, *point) <= radius:
                reached.add(point)
                queue.append(point)
    return reached


def site_problem(world: WorldState, kind: str, x: int, y: int) -> str | None:
    cell = next((cell for cell in world.terrain if (cell.x, cell.y) == (x, y)), None)
    if not cell or cell.kind in {"ocean", "river", "lake", "mountain", "ice"}:
        return "Construction needs stable dry land, away from open water, mountains and ice."
    if cell.condition < 30 or cell.pollution > 60:
        return "Restore this damaged or polluted site before building."
    if kind == "farm" and (cell.kind not in {"plains", "grassland", "farmland"}
                           or cell.fertility < 30 or cell.moisture < 0.2):
        return "A farm needs open fertile soil with enough moisture."
    if any((building.x, building.y) == (x, y) and building.condition >= 20
           and building.kind != "campfire" and kind != "campfire" for building in world.structures):
        return "Another usable building occupies this site."
    return None


def building_need(world: WorldState, agent: Agent, kind: str) -> bool:
    """Build for local demand; creator identity never makes an existing building unavailable."""
    neighborhood = local_land(world, agent)
    local = lambda item: (item.x, item.y) in neighborhood
    buildings = [building for building in world.structures if local(building) and building.condition >= 20]
    people = [person for person in world.agents if person.alive and local(person)]
    demand = max(1, len(people) + sum(person.pregnancy_months_remaining is not None for person in people))
    if kind in SHELTER_KINDS:
        capacity = sum(SHELTER_CAPACITY.get(building.kind, 0) for building in buildings)
        return capacity < demand and not any(building.kind == kind for building in buildings)
    if any(building.kind == kind for building in buildings):
        return False
    if kind == "campfire":
        return world.weather in {"cold", "rain"} or any(node.kind == "meat" and node.quantity and local(node) for node in world.resources) or any(animal.alive and local(animal) for animal in world.animals)
    if kind == "farm":
        food = sum(node.quantity for node in world.resources if node.kind in FOOD_KINDS and local(node))
        return food < demand * 12 or any(person.hunger >= 45 for person in people)
    if kind == "granary":
        return any(building.kind == "farm" for building in buildings) or sum(
            node.quantity for node in world.resources if node.kind in FOOD_KINDS and local(node)) >= demand * 12
    if kind == "workshop":
        return len([item for item in world.items if local(item)]) >= 2
    if kind == "shrine":
        return any(len(belief.believer_ids) >= 3 and agent.id in belief.believer_ids for belief in world.beliefs)
    return False


def material_donors(world: WorldState, agent: Agent) -> list[Agent]:
    """Nearby relatives and group members pool materials; quantities are still consumed once."""
    group_ids = {group.id for group in world.groups if agent.id in group.member_ids}
    partners = {agent.id, agent.bonded_partner_id, *agent.parent_ids, *agent.children_ids}
    for group in world.groups:
        if group.id in group_ids:
            partners.update(group.member_ids)
    neighborhood = local_land(world, agent, 2)
    return [agent] + [person for person in world.agents if person.id != agent.id and person.alive
        and person.id in partners and (person.x, person.y) in neighborhood]


def material_stock(world: WorldState, agent: Agent) -> dict[str, int]:
    return {kind: sum(person.inventory.get(kind, 0) for person in material_donors(world, agent)) for kind in ("wood", "stone")}


def consume_materials(world: WorldState, agent: Agent, cost: dict[str, int]) -> bool:
    stock = material_stock(world, agent)
    if any(stock.get(kind, 0) < amount for kind, amount in cost.items()):
        return False
    for kind, amount in cost.items():
        for person in material_donors(world, agent):
            used = min(amount, person.inventory.get(kind, 0))
            if used:
                person.inventory[kind] -= used
                amount -= used
    return True


def item_needed(world: WorldState, agent: Agent, kind: str) -> bool:
    nearby = [item for item in world.items if item.kind == kind and item.durability >= 20
              and distance(world, agent.x, agent.y, item.x, item.y) <= 4]
    if kind == "raft":
        return not nearby and "raft building" in agent.knowledge and any(
            is_coast(world, cell.x, cell.y) and distance(world, agent.x, agent.y, cell.x, cell.y) <= 3 for cell in world.terrain)
    if kind == "spear":
        adults = sum(person.alive and person.age_days >= 16 * 365
                     and distance(world, agent.x, agent.y, person.x, person.y) <= 3 for person in world.agents)
        return len(nearby) < max(1, adults) and any(animal.alive and animal.animal_type == "wild"
            and distance(world, agent.x, agent.y, animal.x, animal.y) <= 5 for animal in world.animals)
    return not nearby and agent.inventory.get("wood", 0) < 2 and bool(agent.construction_project)
