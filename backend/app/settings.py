"""Environment-backed settings; defaults make the local Ollama setup turnkey."""

import os
from pathlib import Path


class Settings:
    """Runtime settings read from environment variables."""

    app_name = "AI World API"
    ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    # The simulation intentionally pins one shared, small Qwen brain for every person.
    ollama_model = "qwen2.5:0.5b"
    ollama_timeout_seconds = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "20"))
    decision_interval_seconds = float(os.getenv("DECISION_INTERVAL_SECONDS", "1.2"))
    # Request all layers on GPU; a GPU allocation failure may retry once using RAM/CPU.
    ollama_gpu_layers = 999
    auto_acceleration_seconds = float(os.getenv("AUTO_ACCELERATION_SECONDS", "120"))
    # 365 biological days consume exactly twelve real minutes at the default 1x speed.
    # The simulation scales daily survival pressure against this compressed clock.
    day_length_seconds = float(os.getenv("DAY_LENGTH_SECONDS", str(720 / 365)))
    natural_event_probability = float(os.getenv("NATURAL_EVENT_PROBABILITY", "0.01"))
    disease_emergence_probability = float(os.getenv("DISEASE_EMERGENCE_PROBABILITY", "0.002"))
    max_saved_events = int(os.getenv("MAX_SAVED_EVENTS", "1000"))
    database_path = os.getenv(
        "AI_WORLD_DATABASE",
        str(Path(__file__).resolve().parents[2] / "data" / "world.sqlite3"),
    )


settings = Settings()
