# Codebase map and debugging guide

## Top-level layout

```text
.
├── README.md                           # Product overview, independent setup, and API
├── idea.md                             # Theme and intended simulation behavior
├── codebase.md                         # This file: file map and debugging guide
├── implementation-status.md            # Verified mechanisms, prototype limits, and further stages
├── .env.example                        # Ollama and backend settings
├── frontend/
│   ├── index.html                      # Standalone Vite app shell
│   ├── vite.config.js                  # Dev server and FastAPI /api proxy
│   ├── package.json / package-lock.json# Three.js and Vite dependencies
│   └── src/
│       ├── app.js                      # 3D globe, figures, API UI, and 2D fallback for unavailable WebGL
│       ├── surface-motion.js           # Quaternion-based movement over a spherical surface
│       ├── world-effects.js            # Geographic event animation and resource disposal
│       ├── world-inspection.js         # Hover descriptions for world entities and terrain
│       └── styles.css                  # White, responsive spectator interface
└── backend/
    ├── requirements.txt                # FastAPI, Uvicorn, and HTTPX dependencies
    └── app/
        ├── main.py                     # API-only FastAPI app, CORS, and lifecycle
        ├── settings.py                 # Ollama model, decision cadence, month length, and database settings
        ├── domain.py                   # Pydantic world, agent, action, and event types
        ├── api/routes.py               # HTTP API endpoints
        ├── agent_brain/ollama_client.py# Private observations, available choices, and model calls
        ├── simulation/engine.py        # Agent decisions plus authoritative biology, ecology, and NPC rules
        ├── simulation/planning.py      # Shared demand, dry-land sites, capacity and family material pools
        ├── simulation/activities.py    # Shared tools, repairs, raft exploration and predator encounters
        ├── simulation/rules.py         # Shared age, disease, population, and building constraints
        └── storage/sqlite_store.py     # SQLite snapshot persistence
```

The saved world stores a procedural terrain cell for every longitude/latitude coordinate, plus agents, animals, crop plots, resources, structures, and cultural state. The backend is authoritative for all movement, ecology, disease, and event consequences. The frontend wraps those coordinates onto a spherical globe and only renders the resulting snapshot.

## File responsibilities

| File | Responsibility | Inspect it when… |
| --- | --- | --- |
| `backend/app/domain.py` | Validated agent, world, action, event, and update schemas. The world stores one shared model name. | A request or persisted snapshot has invalid fields. |
| `backend/app/settings.py` | Ollama URL/model, request timeout, decision interval, month length, event probabilities, database path, and saved-event limit. | A runtime default or `.env` value is wrong. |
| `backend/app/agent_brain/ollama_client.py` | Builds private observations and requests bounded structured decisions from Ollama. | Model responses fail validation or agents make unexpected proposals. |
| `backend/app/simulation/engine.py` | Resolves quick action cycles, advances needs at day boundaries, runs animal NPC behavior, disease, hazards, relationships, teaching, birth/death, mourning, burial, and construction. | A world consequence is missing or inconsistent. |
| `backend/app/simulation/rules.py` | Shared rules consumed by the engine and Ollama decision filter, including adult age, population cap, diseases, traits, and building costs. | The model proposes something the engine cannot support, or a biological/building limit needs tuning. |
| `backend/app/api/routes.py` | Health, world controls, model selection, biological adjustments, and spectator events. | API request/response behavior is incorrect. |
| `backend/app/storage/sqlite_store.py` | Reads and writes the authoritative world snapshot. | State does not persist or migration looks wrong. |
| `backend/app/main.py` | API-only FastAPI setup, configurable CORS, and engine shutdown. | Backend startup, CORS, or shutdown fails. |
| `frontend/index.html` | Standalone spectator shell and overlay element IDs. | A UI control or overlay is missing. |
| `frontend/src/app.js` | Three.js terrain, resource scenery, human figures, labels, click selection, inspector, event drops, filterable agent/work/birth/death timeline, and API requests. | Terrain rendering, mapping, timeline entries, or browser interaction is wrong. |
| `frontend/src/styles.css` | White responsive styling and world overlays. | Layout, typography, mobile sizing, or colors look wrong. |
| `frontend/src/surface-motion.js` | Interpolates direction with quaternions and radius separately. `Vector3.slerp` does not exist in Three.js. | A populated scene freezes or people move through the globe. |
| `frontend/src/world-effects.js` | Consumes new events into location-specific particles; animation never controls the backend. | Effects fail to appear, deduplicate or expire. |
| `frontend/src/world-inspection.js` | Resolves figure ancestry into current agent, NPC, resource, building, crop or terrain details. | Hover details are missing or stale. |
| `frontend/tests/world-features.test.js` | Event lifecycle and hover descriptors using real Three.js objects. | A particular event or object type regresses. |
| `backend/tests/test_continuous_world.py` | Acceleration, error recovery, restart/reset, close founders, GPU fallback and habitat care/spawning. | Continuous running or compute placement changes. |
| `frontend/tests/world-runtime.test.js` | Executes the app update/frame flow using real geometry/math and stub browser/GPU surfaces. | A production build passes but rendering or selection fails at runtime. |
| `backend/tests/test_world.py` | Isolated temporary-world regression checks. | Biology, material accounting, consent, timing, inference or persistence changes. |
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

The browser never advances biology. The base decision delay is 1.2 seconds divided by the square root of current speed (minimum 0.35 seconds), plus inference latency. A separate clock multiplies elapsed real running time by `time_scale`; 60 scaled seconds advance one simulation month, so default fixed 1× advances exactly one month per real minute. Explicit spectator speeds are 1×–16×. A model-selected trip, including family reunion, can continue without asking the LLM to reselect its intention at every step. `decision_source` distinguishes fresh choices from continuation and fallback, while `intention_source` records the task's original source. `pending_action`, `construction_project`, `visited_cells` and `last_result` persist individual progress. The `POST /api/world/tick` endpoint remains a manual one-month step. Local computer time drives visible lighting/clock; simulated year/month are separate. Animals never call the LLM. Bodies persist until burial. Pause invalidates model proposals still in flight. SQLite includes the random stream and pending work.

Living population is capped at 128 to bound local LLM and simulation load. Human extinction is recorded while ecology continues. Recoverable action errors retry with backoff; failed ecology updates roll back the partial update and retry. Only explicit pause stops a running world. Startup resumes saved running worlds; shutdown preserves that choice. Wildlife is capped by healthy habitat and a global maximum of 24. Kept animals have a separate population budget capped at 24. Spawn, reproduction and migration all use `animal_capacity` from `rules.py`. Migration removes surplus animals without creating carcasses.

## Debugging path

1. Open `GET /api/health`; confirm Ollama is reachable, Qwen is installed, and `compute.device`/`vram_bytes` report actual residency. Requests ask for all GPU layers; GPU allocation failure retries with `num_gpu=0`. Warmup and `keep_alive=-1` avoid repeated unloads.
2. Inspect `GET /api/world`; check `global_model`, `running`, `processing`, `time_scale`, `auto_accelerate`, agent locations, needs, disease, and `last_action`.
3. Read the retained `events` in the response for `fallback_decision`, rejected actions, hazards, births, deaths, and spectator changes. The frontend groups these records into All, Work, Newborns, and Deaths timeline sections.
4. For an action without the expected result, inspect its action event and proposed action. The engine may have moved an agent toward a resource instead of completing the action immediately, or rejected a choice due to age, location, resources, or missing consent.
5. For an event drop, confirm the pointer ray intersects the walkable land and inspect the resulting event's `x`, `y`, `source`, and affected agent IDs.
6. For a visual mismatch, compare the payload to `frontend/src/app.js`. Run `npm test --prefix frontend` before the production build: bundling alone cannot detect unsupported runtime methods. The viewport shows frame errors instead of leaving a silently frozen ocean. Texture UV longitude must align with `worldToScene`; camera matrices must update before labels and picking.
7. The standalone frontend uses Vite at port 5173. Confirm FastAPI is running at 8000 and that `frontend/vite.config.js` proxies `/api`.
8. The SQLite snapshot is at `backend/data/world.sqlite3` by default. Preserve local data when debugging; `.gitignore` intentionally excludes it.
9. For malformed model output, inspect `OllamaClient.decide`: Qwen returns a short numbered choice, reason and optional message. The server maps the choice back to a concrete bounded action. Do not restore the old 48-token full-action schema, which truncated IDs and drove nearly continuous fallbacks.

Run backend checks with `$env:PYTHONPATH='backend'; python -m unittest discover -s backend/tests -v`. Each check uses temporary databases. Tests include biology advancing while model calls wait and pause discarding a late model result.

## Local startup

Install Python requirements and run `npm ci --prefix frontend`. Start FastAPI with `python -m uvicorn app.main:app --app-dir backend --reload --port 8000`, then in a second terminal start Vite with `npm run dev --prefix frontend`. Visit `http://localhost:5173`; FastAPI serves only the API and API documentation.

For production, `npm run build --prefix frontend` creates a separate `frontend/dist` static app. Host it independently and configure backend `FRONTEND_ORIGINS` with its browser origin(s).

## Current limits

- This is a small illustrative simulation, not a scientific reconstruction of millions of years of hominin evolution.
- Biome, animal, crop, disease, mortality, and hazard rules remain prototype simplifications.
- LLM behavior is limited to each agent's available action schema and the information in its individual observation. The Qwen 0.5B default is compact and quick, with less reasoning capacity than larger models.
- A single local SQLite snapshot is persisted. The browser uses polling, not a streaming transport.
- The 36×18 world is a compact spherical abstraction with fictional geography, not a scientific map of Earth or a reconstruction of millions of years of evolution.

## Family and food ecology debugging

- Inspect `family_offer`, `family_offer_until_tick`, `last_birth_tick`, and `pregnancy_months_remaining` on an agent. A partner sees incoming offers in their own private observation, and must choose the matching action. An offer lasts seven simulated months. Both same-round proposals and later answers work. Family travel is a continued model intention.
- `reproduction_block` in `rules.py` is shared by the choice menu and resolver: adults, health/needs, existing pregnancy, capacity reservations, and postpartum recovery must agree in both places.
- `_survival_reflexes` is the explicitly recorded physical response to urgent needs while model calls wait. Its actions obey normal routing and resource use; it never proposes bonds or reproduction. Infants travel with the primary living parent.
- `_rebalance_animals`, `_spawn_wildlife`, `_seed_animals`, `_advance_animals`, and `_tame` use the shared animal budget. Migration removes surplus saved-world animals rather than killing them into meat stockpiles.
- `backend/tests/test_family_and_ecology.py` covers cross-round consent, expiry, partner approach, birth, recovery, resource-consuming reflexes, animal limits, infant travel, and preserved lineage after parent death.

## Construction, shared tools, exploration and timeline records

| File | Debugging responsibility |
| --- | --- |
| `backend/app/simulation/planning.py` | Shared `building_need`, `site_problem`, land-connected settlements, material pools/consumption, and `item_needed`. Both the LLM menu and resolver use these rules. |
| `backend/app/simulation/activities.py` | Engine mixin for experiments, crafting, public item handovers, repair, boarding, sailing, landing, fleeing and predator defence. |
| `backend/tests/test_settlements_and_exploration.py` | Specific fatal causes, 9-month gestation/migration, real shared material costs, site validation, duplicate rejection, shared equipment, island crossings, boarding completion, and predator/family conflict. |
| `backend/tests/test_family_clock_and_motives.py` | One-minute day, saved-world clock/pregnancy migration, parent naming and fallback, random sex, fear/care and family reunion. |

`WorldState.items` contains shared physical objects with creator, current holder, location, capacity and durability. `Agent.equipped_item_id`, `vehicle_id` and `has_sailed` distinguish carried weapons from boat passengers. Objects follow their user; abandoned equipment can be reused. Tool ownership does not grant exclusive use, but a hostile current holder can refuse a handover.

Boarding/sailing are discrete completed actions. A resource or construction intention may continue through those travel steps, but a direct board action must not remain pending and repeat forever. `_move_or_act` allows water routes only with a seaworthy raft, and requests boarding, sailing or disembarking as appropriate. Walking choices are excluded while aboard. Nearby unfamiliar landing sites receive attention before further ocean wandering. A model-selected `explore` intention stores `destination_x`/`destination_y` and continues through the physical transport steps until landing, rather than asking for a new random direction at every step.

`_hurt` attributes fatal damage before later effects obscure it. `_check_death` saves the cause, month tick, need levels, disease and recent injury, releases carried equipment, clears social offers and emits a death event. `frontend/src/app.js` renders action and life events in a persistent filterable timeline; selecting a person opens their detailed life record. Old snapshots retain a legacy attribution label when exact fatal damage was never recorded.

`rules_version=2` migrated older pregnancy countdowns, and `rules_version=3` compressed them to nine steps. `rules_version=4` migrated saved worlds to a 60-second clock. `rules_version=5` names that clock in months while preserving its fraction, world identity, people and run/pause state. The serialized model accepts the old day-named clock and pregnancy fields so SQLite snapshots upgrade without reset. `Agent.unborn_name_suggestions` records each parent's model-selected name; `_give_birth` samples sex, chooses a proposal or a parent-derived provisional fallback, creates the child and records who named them. `Agent.name_status` marks provisional newborns for a parent's later naming choice. `fear`, `stress` and `loneliness` persist on each person and influence care, reunion, conflict and family opportunities.
