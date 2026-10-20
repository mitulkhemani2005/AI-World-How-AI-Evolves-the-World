"""Shared constants for agent decisions and authoritative world validation."""

ADULT_AGE_DAYS = 16 * 365
PREGNANCY_DAYS = 90
MAX_POPULATION = 128
# Keep wildlife a modest renewable food source instead of filling every terrain cell.
MAX_WILD_ANIMALS = 24
MAX_KEPT_ANIMALS = 24
FAMILY_OFFER_DAYS = 7
POSTPARTUM_DAYS = 120
DISEASES = (
    "fever", "respiratory illness", "wound infection", "food poisoning",
    "intestinal parasite", "waterborne infection",
)
FOOD_KINDS = {"food", "fruit", "vegetable", "meat", "cooked_meat", "eggs", "milk"}
FARMABLE_TERRAIN = {"plains", "grassland", "farmland", "forest", "river", "lake"}
SHELTER_KINDS = {"lean_to", "hut", "home", "communal_house"}
SHELTER_CAPACITY = {"lean_to": 2, "hut": 4, "home": 6, "communal_house": 12}
PREDATOR_SPECIES = {"wolf", "big_cat"}
# Crafting is explicit material work. Raft construction also requires an agent's discovery.
ITEM_RECIPES = {"spear": {"wood": 2, "stone": 1}, "stone_axe": {"wood": 1, "stone": 2}, "raft": {"wood": 6}}
TRAIT_NAMES = ("curiosity", "cooperation", "aggression", "resilience", "sociability")


def animal_capacity(world, *, wild: bool = True) -> int:
    """One shared budget is used by spawning, births, and saved-world migration."""
    if not wild:
        return min(MAX_KEPT_ANIMALS, 4 + 2 * sum(person.alive for person in world.agents))
    healthy_land = sum(cell.kind in {"plains", "grassland", "farmland", "forest", "rainforest", "boreal_forest"}
                       and cell.condition >= 40 and cell.pollution <= 60 for cell in world.terrain)
    return min(MAX_WILD_ANIMALS, max(3, healthy_land // 12)) if healthy_land else 0


def reproduction_block(world, first, second) -> str | None:
    """Shared physical requirements keep model opportunities and action validation in agreement."""
    if first.id == second.id or not first.alive or not second.alive or first.sex == second.sex:
        return "Reproduction was not biologically possible for this pair."
    if min(first.age_days, second.age_days) < ADULT_AGE_DAYS:
        return "Both people must be adults."
    mother = first if first.sex == "female" else second
    if mother.pregnancy_days_remaining is not None:
        return f"{mother.name} is already pregnant."
    if world.tick - mother.last_birth_tick < POSTPARTUM_DAYS:
        return f"{mother.name} needs recovery time after giving birth."
    if sum(person.alive for person in world.agents) + sum(
        person.alive and person.pregnancy_days_remaining is not None for person in world.agents) >= MAX_POPULATION:
        return "The world has reached its population limit."
    if min(first.health, second.health) < 45 or max(first.hunger, second.hunger, first.thirst, second.thirst) >= 75:
        return "Their health or immediate needs made reproduction unsafe."
    return None

# Minimum knowledge level and individual material costs for each buildable property.
BUILDING_RULES: dict[str, tuple[int, dict[str, int]]] = {
    "lean_to": (0, {"wood": 2}),
    "campfire": (0, {"wood": 2, "stone": 1}),
    "hut": (1, {"wood": 4}),
    "home": (1, {"wood": 5, "stone": 1}),
    "communal_house": (2, {"wood": 8, "stone": 3}),
    "granary": (2, {"wood": 5, "stone": 1}),
    "farm": (2, {"wood": 6}),
    "shrine": (2, {"wood": 4, "stone": 2}),
    "workshop": (3, {"wood": 8, "stone": 4}),
}
