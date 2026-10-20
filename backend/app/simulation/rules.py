"""Shared constants for agent decisions and authoritative world validation."""

ADULT_AGE_DAYS = 16 * 365
PREGNANCY_DAYS = 270
MAX_POPULATION = 128
DISEASES = (
    "fever", "respiratory illness", "wound infection", "food poisoning",
    "intestinal parasite", "waterborne infection",
)
FOOD_KINDS = {"food", "fruit", "vegetable", "meat", "cooked_meat", "eggs", "milk"}
FARMABLE_TERRAIN = {"plains", "grassland", "farmland", "forest", "river", "lake"}
SHELTER_KINDS = {"lean_to", "hut", "home", "communal_house"}
TRAIT_NAMES = ("curiosity", "cooperation", "aggression", "resilience", "sociability")

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
