# Codebase map and debugging guide

## Repository layout

```text
.
├── README.md                         # Product overview, setup, features, and API
├── idea.md                           # Theme and desired simulation behavior
├── codebase.md                       # This file: implementation map and debugging
├── .env.example                      # Local runtime settings
├── frontend/
│   ├── package.json                  # Three.js and esbuild dependencies/scripts
│   ├── package-lock.json              # Reproducible JavaScript dependency versions
│   ├── build.mjs                     # Bundles the spectator into FastAPI static files
│   └── app.js                        # Three.js scene and browser-side interactions
└── backend/
    ├── requirements.txt               # FastAPI, Uvicorn, and HTTPX
    └── app/
        ├── main.py                    # FastAPI application and static page serving
        ├── settings.py                # Environment-backed model and simulation settings
        ├── domain.py                  # Pydantic world, agent, action, and event schemas
        ├── api/routes.py              # HTTP API endpoints
        ├── agent_brain/ollama_client.py # Private observations and shared Ollama model calls
        ├── simulation/engine.py       # Authoritative world rules and state transitions
        ├── storage/sqlite_store.py    # SQLite snapshot persistence
        └── static/
            ├── index.html             # Spectator page structure
            ├── styles.css             # Dark responsive layout and 3D scene overlays
            └── app.bundle.js          # Generated Three.js/browser bundle; rebuild from frontend/
```

## What owns what

| File | Responsibility | Inspect it when… |
| --- | --- | --- |
| `backend/app/domain.py` | Agent, world, resource, event, action, and spectator update schemas. `WorldState.global_model` defines the shared model. | API data validation or serialization is wrong. |
| `backend/app/settings.py` | Ollama URL/model, timeouts, natural-event probabilities, database path, event limit. | A runtime default differs from the expected environment. |
| `backend/app/agent_brain/ollama_client.py` | Creates bounded, individual agent observations; asks the shared model for structured actions; validates Ollama responses. | A brain chooses poorly, responses time out, or fallback entries appear. |
| `backend/app/simulation/engine.py` | Advances world time, needs, movement, action effects, teaching, relationships, reproduction, inheritance, disease, death, disasters, and ecology. | A simulated outcome is inconsistent with the prior state or rule. |
| `backend/app/api/routes.py` | Health, world run/pause/tick/reset, installed models, shared model changes, agent stat edits, and spectator events. | An endpoint returns the wrong status or data. |
| `backend/app/storage/sqlite_store.py` | Saves/loads the complete world snapshot. | The world does not persist or restored data looks wrong. |
| `backend/app/main.py` | FastAPI app lifespan and same-origin static file hosting. | Server startup, shutdown, or page delivery fails. |
| `frontend/app.js` | Three.js land, human figures, scenery, orbit controls, click selection, drag/drop events, stat inspector, and API requests. | A visual interaction or browser request does not work. |
| `frontend/build.mjs` | Bundles the browser code and Three.js as `/assets/app.bundle.js`. | The served JavaScript is stale or bundling fails. |
| `backend/app/static/index.html` | Accessible page structure and panel IDs. | A needed control or panel is absent. |
| `backend/app/static/styles.css` | Dark theme, responsive layout, event palette, inspector, labels, and scene styling. | A layout, color, or small-screen issue appears. |

## Decision and update flow

```text
browser asks FastAPI for the current world
                  ↓
simulation advances day, environment, ecology, and natural hazards
                  ↓
each living agent gets its own observation and personal memory
                  ↓
the shared Ollama model sees a state-specific action schema and proposes an individual action
      ↓ successful decision                     ↓ Ollama/error response
validated action proposal                visible survival fallback
                  ↓
simulation applies resource, consent, relationship, and biology rules
  + visible but distant resource choices become one cardinal path step
                  ↓
events + SQLite snapshot → FastAPI → animated 3D spectator scene
```

One tick is one simulated day. The model suggests an action; it cannot directly edit world state. Bonding and reproduction require matching independent proposals. Environmental damage uses a circular, distance-scaled footprint, and spectator events are tagged as spectator-sourced. The API does not hold the world state lock while waiting for model inference, so inspection and interventions remain responsive.

The Ollama adapter disables optional model thinking and limits output length to reduce decision latency. Up to two agents can request decisions concurrently. The action schema omits clearly wasteful or impossible choices (for example, eating when hunger is already low). When a model chooses a visible resource that is nearby but not underfoot, the engine applies one step of movement toward it and records both the proposed and resolved action. If an Ollama call or action validation fails, the engine chooses a basic survival fallback and records the reason in a `fallback_decision` event.

## Debugging checklist

1. Call `GET /api/health`. Confirm Ollama is reachable and the configured model is installed.
2. Call `GET /api/world`. Inspect `global_model`, `processing`, living population, each person's `last_action`, needs, and location.
3. Inspect the event timeline for `fallback_decision`. Its details include the inference/validation failure; without that event, the action came from the model.
4. If an action was proposed but had no effect, inspect the matching `action` event and its `result`. Check `proposed_action` when the engine resolved a resource choice as movement. The engine may also reject an action for age, resources, or missing consent.
5. For a spectator event, check the event's `source`, `x`, `y`, `affected`, and nearby agents/resource quantities. The requested center is a world coordinate.
6. For an incorrect visual, compare the API payload with `frontend/app.js` before editing simulation rules. Check browser console errors and verify `npm run build --prefix frontend` was run after a JS change.
7. If a restored snapshot appears to have separate models, engine startup migrates each person's model to the snapshot's world-wide `global_model`.

Avoid treating free-form model text as proof that an action succeeded. The backend state transition and timeline event are authoritative.

## Local development notes

- Install JavaScript dependencies with `npm ci --prefix frontend` and regenerate the static bundle with `npm run build --prefix frontend`.
- Start the server with `python -m uvicorn app.main:app --app-dir backend --reload`.
- The SQLite world lives at `backend/data/world.sqlite3` unless `AI_WORLD_DATABASE` overrides it. Do not remove or reset it while debugging another copy of the app.
- The installed UI bundle is generated output; edit `frontend/app.js` rather than editing compressed `app.bundle.js` directly.
- Each current and newborn agent receives `world.global_model`. Memories, observations, traits, relationships, and knowledge remain individual.

## Current limits

- This is a small illustrative world, not a biological or historical reconstruction of the full 6–7 million years since early hominins.
- Ollama choices are constrained to the action schema; social behavior is emergent only within the implemented rules.
- Simulated disease and hazard numbers are tunable assumptions rather than medical/scientific estimates.
- The world is a single local SQLite snapshot; the browser uses polling rather than a streaming connection.
- Two decision calls run in parallel at most. Very large populations need batching, memory management, and scheduling controls.
