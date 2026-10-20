"""Shared constants for agent decisions and authoritative world validation."""

ADULT_AGE_DAYS = 16 * 365
PREGNANCY_DAYS = 270
MAX_POPULATION = 128
DISEASES = ("fever", "respiratory illness", "wound infection")
TRAIT_NAMES = ("curiosity", "cooperation", "aggression", "resilience", "sociability")

# Minimum knowledge level and individual material costs for each buildable property.
BUILDING_RULES: dict[str, tuple[int, dict[str, int]]] = {
    "lean_to": (0, {"wood": 2}),
    "hut": (1, {"wood": 4}),
    "home": (1, {"wood": 5, "stone": 1}),
    "communal_house": (2, {"wood": 8, "stone": 3}),
    "granary": (2, {"wood": 5, "stone": 1}),
    "farm": (2, {"wood": 6}),
    "shrine": (2, {"wood": 4, "stone": 2}),
    "workshop": (3, {"wood": 8, "stone": 4}),
}
