"""Environment-backed settings; defaults make the local Ollama setup turnkey."""

import os
from pathlib import Path


class Settings:
    """Runtime settings read from environment variables."""

    app_name = "AI World API"
    ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model = os.getenv("OLLAMA_MODEL", "gemma4:e2b")
    ollama_timeout_seconds = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "90"))
    natural_event_probability = float(os.getenv("NATURAL_EVENT_PROBABILITY", "0.01"))
    disease_emergence_probability = float(os.getenv("DISEASE_EMERGENCE_PROBABILITY", "0.002"))
    max_saved_events = int(os.getenv("MAX_SAVED_EVENTS", "1000"))
    database_path = os.getenv(
        "AI_WORLD_DATABASE",
        str(Path(__file__).resolve().parents[2] / "data" / "world.sqlite3"),
    )


settings = Settings()
