# Codebase map and debugging guide

## Top-level layout

```text
.
├── README.md                           # Product overview, independent setup, and API
├── idea.md                             # Theme and intended simulation behavior
├── codebase.md                         # This file: file map and debugging guide
├── .env.example                        # Ollama and backend settings
├── frontend/
│   ├── index.html                      # Standalone Vite app shell
│   ├── vite.config.js                  # Dev server and FastAPI /api proxy
│   ├── package.json / package-lock.json# Three.js and Vite dependencies
│   └── src/
│       ├── app.js                      # Procedural globe, biomes, figures, ecology, and API UI
│       └── styles.css                  # White, responsive spectator interface
└── backend/
    ├── requirements.txt                # FastAPI, Uvicorn, and HTTPX dependencies
    └── app/
        ├── main.py                     # API-only FastAPI app, CORS, and lifecycle
        ├── settings.py                 # Ollama model, decision cadence, day length, and database settings
        ├── domain.py                   # Pydantic world, agent, action, and event types
        ├── api/routes.py               # HTTP API endpoints
        ├── agent_brain/ollama_client.py# Private observations, available choices, and model calls
        ├── simulation/engine.py        # Agent decisions plus authoritative biology, ecology, and NPC rules
        ├── simulation/rules.py         # Shared age, disease, population, and building constraints
        └── storage/sqlite_store.py     # SQLite snapshot persistence
```

The saved world stores a procedural terrain cell for every longitude/latitude coordinate, plus agents, animals, crop plots, resources, structures, and cultural state. The backend is authoritative for all movement, ecology, disease, and event consequences. The frontend wraps those coordinates onto a spherical globe and only renders the resulting snapshot.

## File responsibilities

| File | Responsibility | Inspect it when… |
| --- | --- | --- |
| `backend/app/domain.py` | Validated agent, world, action, event, and update schemas. The world stores one shared model name. | A request or persisted snapshot has invalid fields. |
| `backend/app/settings.py` | Ollama URL/model, request timeout, decision interval, day length, event probabilities, database path, and saved-event limit. | A runtime default or `.env` value is wrong. |
| `backend/app/agent_brain/ollama_client.py` | Builds private observations and requests bounded structured decisions from Ollama. | Model responses fail validation or agents make unexpected proposals. |
| `backend/app/simulation/engine.py` | Resolves quick action cycles, advances needs at day boundaries, runs animal NPC behavior, disease, hazards, relationships, teaching, birth/death, mourning, burial, and construction. | A world consequence is missing or inconsistent. |
| `backend/app/simulation/rules.py` | Shared rules consumed by the engine and Ollama decision filter, including adult age, population cap, diseases, traits, and building costs. | The model proposes something the engine cannot support, or a biological/building limit needs tuning. |
| `backend/app/api/routes.py` | Health, world controls, model selection, biological adjustments, and spectator events. | API request/response behavior is incorrect. |
| `backend/app/storage/sqlite_store.py` | Reads and writes the authoritative world snapshot. | State does not persist or migration looks wrong. |
| `backend/app/main.py` | API-only FastAPI setup, configurable CORS, and engine shutdown. | Backend startup, CORS, or shutdown fails. |
| `frontend/index.html` | Standalone spectator shell and overlay element IDs. | A UI control or overlay is missing. |
| `frontend/src/app.js` | Three.js terrain, resource scenery, human figures, labels, click selection, inspector, event drops, and API requests. | Terrain rendering, mapping, or browser interaction is wrong. |
| `frontend/src/styles.css` | White responsive styling and world overlays. | Layout, typography, mobile sizing, or colors look wrong. |
| `frontend/vite.config.js` | Frontend dev server and proxy from `/api` to FastAPI. | Local frontend API requests fail. |

## Decision and update flow

```text
Vite frontend polls GET /api/world
                ↓
FastAPI engine advances environment and day-level biology
                ↓
each decision-capable agent receives its own private observation
                ↓
the selected shared Ollama model proposes one bounded action per agent
       ↓ valid proposal                  ↓ inference/validation error
world rules resolve the action          recorded survival fallback
                ↓
events and world state persist in SQLite
                ↓
Vite renders the continuous land, figures, resources, and inspectable life records
```

The browser is a spectator and never advances biology by animating the display. The run loop accepts a new agent decision every 2.5 seconds and advances one complete day every 60 seconds. Age, needs, seasons, disease progression, and ecology update at day boundaries; agents can act several times during a day. The `POST /api/world/tick` endpoint remains a manual one-day step. Day progress is persisted and drives the globe lighting and clock. Animals have hardcoded NPC behavior and never call the LLM. Dead people remain visible until another agent chooses to mourn or bury them. LLM text cannot directly edit world state; the engine validates each action against world rules. The SQLite snapshot includes the random stream, so natural events continue consistently after restart.

Living population is capped at 128 to bound local LLM and simulation load. When the last person dies, the engine records world extinction and stops its background loop. A failed decision round is recorded and pauses the simulation so it can be inspected and restarted.

## Debugging path

1. Open `GET /api/health`; confirm whether Ollama is reachable and the selected model is installed.
2. Inspect `GET /api/world`; check `global_model`, `running`, `processing`, agent locations, needs, disease, and `last_action`.
3. Read the retained `events` in the response for `fallback_decision`, rejected actions, hazards, births, deaths, and spectator changes. The UI intentionally has no timeline, but the API preserves these records.
4. For an action without the expected result, inspect its action event and proposed action. The engine may have moved an agent toward a resource instead of completing the action immediately, or rejected a choice due to age, location, resources, or missing consent.
5. For an event drop, confirm the pointer ray intersects the walkable land and inspect the resulting event's `x`, `y`, `source`, and affected agent IDs.
6. For a visual mismatch, compare the API payload to `frontend/src/app.js`. Run `npm run build --prefix frontend`; Vite reports parse and bundling errors without writing into the backend.
7. The standalone frontend uses Vite at port 5173. Confirm FastAPI is running at 8000 and that `frontend/vite.config.js` proxies `/api`.
8. The SQLite snapshot is at `backend/data/world.sqlite3` by default. Preserve local data when debugging; `.gitignore` intentionally excludes it.

## Local startup

Install Python requirements and run `npm ci --prefix frontend`. Start FastAPI with `python -m uvicorn app.main:app --app-dir backend --reload --port 8000`, then in a second terminal start Vite with `npm run dev --prefix frontend`. Visit `http://localhost:5173`; FastAPI serves only the API and API documentation.

For production, `npm run build --prefix frontend` creates a separate `frontend/dist` static app. Host it independently and configure backend `FRONTEND_ORIGINS` with its browser origin(s).

## Current limits

- This is a small illustrative simulation, not a scientific reconstruction of millions of years of hominin evolution.
- Biome, animal, crop, disease, mortality, and hazard rules remain prototype simplifications.
- LLM behavior is limited to each agent's available action schema and the information in its individual observation. The Qwen 0.5B default is compact and quick, with less reasoning capacity than larger models.
- A single local SQLite snapshot is persisted. The browser uses polling, not a streaming transport.
- The 36×18 world is a compact spherical abstraction with fictional geography, not a scientific map of Earth or a reconstruction of millions of years of evolution.
