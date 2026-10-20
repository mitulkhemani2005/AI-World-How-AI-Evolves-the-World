# Codebase Map and Debugging Guide

## Current structure

```text
.
├── .env.example
├── .gitignore
├── README.md
├── idea.md
├── codebase.md
├── LICENSE
└── backend/
    ├── requirements.txt
    └── app/
        ├── __init__.py
        ├── main.py
        ├── settings.py
        ├── domain.py
        ├── api/
        │   ├── __init__.py
        │   └── routes.py
        ├── agent_brain/
        │   ├── __init__.py
        │   └── ollama_client.py
        ├── simulation/
        │   ├── __init__.py
        │   └── engine.py
        ├── storage/
        │   ├── __init__.py
        │   └── sqlite_store.py
        └── static/
            ├── index.html
            ├── styles.css
            └── app.js
```

## File responsibilities

| File | Responsibility | Inspect when… |
| --- | --- | --- |
| `.env.example` | Documents local Ollama and simulation settings without secrets. | A local setting needs to be changed. |
| `.gitignore` | Excludes Python bytecode, local environment files, and SQLite data. | Generated files appear in Git status. |
| `README.md` | Product summary, implemented feature list, setup, and API routes. | You need to run or understand the project. |
| `idea.md` | Full simulation theme, agent, biology, society, and spectator vision. | A feature or behavior needs to match the intended product. |
| `codebase.md` | This file: implementation map and debugging path. | You need to find which module owns a behavior. |
| `backend/requirements.txt` | FastAPI, Uvicorn, and HTTPX dependencies. | Dependency installation fails. |
| `backend/app/main.py` | FastAPI app, local CORS policy, lifespan cleanup, and static frontend serving. | The server fails to start or the page is not served. |
| `backend/app/settings.py` | Reads Ollama endpoint/model, timeouts, event probabilities, database path, and event-log limit. | A runtime default or environment setting is wrong. |
| `backend/app/domain.py` | Pydantic agent, resource, world, structure, group, belief, event, and action schemas. | State validation or API serialization is wrong. |
| `backend/app/api/routes.py` | Health, model list, world tick/run/pause/reset, model assignment, and spectator event endpoints. | An HTTP request or response is wrong. |
| `backend/app/agent_brain/ollama_client.py` | Builds each agent's observation, checks local models, calls Ollama, and validates structured action output. | A model is unavailable, response parsing fails, or an agent sees incorrect context. |
| `backend/app/simulation/engine.py` | Authoritative world rules: time, needs, disease, actions, reproduction, teaching, groups, beliefs, buildings, disasters, and mortality. | A world outcome, action, or event source is incorrect. |
| `backend/app/storage/sqlite_store.py` | Loads and saves the current complete world snapshot in SQLite. | State does not persist or the snapshot cannot be loaded. |
| `backend/app/static/index.html` | Accessible structure for the spectator dashboard. | A panel or control is missing from the page. |
| `backend/app/static/styles.css` | Responsive visual design and map layout. | The page layout or readability is wrong. |
| `backend/app/static/app.js` | Polls the API, renders the map and timeline, and sends spectator commands. | The page displays stale data or a control does not call the API. |
| `__init__.py` files | Mark Python application modules. | Python import resolution fails. |

## Important behavior boundaries

- **Agent brain:** Returns a proposed action from one person's bounded observation. It does not mutate world state.
- **Simulation engine:** Validates actions and applies biology, resource, relationship, and event consequences.
- **FastAPI routes:** Validate HTTP input and call the engine; simulation and prompt rules stay out of route handlers.
- **SQLite store:** Saves the authoritative Pydantic world snapshot. It does not decide outcomes.
- **Browser UI:** Displays state returned by the backend and sends explicit spectator commands. It does not duplicate simulation rules.

## Main simulation flow

```text
environment and natural events
        ↓
each living agent receives a private observation
        ↓
Ollama proposes a structured action (or fallback policy acts)
        ↓
the engine resolves actions and mutual consent
        ↓
biology, disease, pregnancy, and mortality advance
        ↓
events and the SQLite snapshot are saved
        ↓
the browser refreshes its view
```

One tick represents one simulated day. A running tick does not hold the state lock while a model is generating, so the UI can inspect the world and the spectator can still trigger events. Each event records whether it came from nature, an agent, the spectator, or the system.

## Debugging workflow

1. Find the first incorrect event in the world timeline.
2. Read its `source`, `kind`, `agent_ids`, and `details` before changing code.
3. For a model decision, inspect the agent observation in `agent_brain/ollama_client.py`, the assigned model, and any `fallback_decision` event.
4. For a world consequence, inspect the corresponding resolver in `simulation/engine.py` and compare its inputs with the prior world state.
5. For missing persistence, inspect the serialized `WorldState` in `storage/sqlite_store.py` and confirm the configured database path.
6. For display issues, check the API payload first, then the DOM rendering in `static/app.js`.

Avoid treating free-form model explanations as the source of truth. The state transition and recorded event are authoritative.

## Current limitations

- The world is a lightweight prototype, not a scientific model of millions of years of human evolution.
- The simulation currently stores one world snapshot in a local SQLite file.
- Ollama model calls are sequential within each day; a large population will need scheduling and cost controls.
- Natural event probabilities and biological effects are tunable assumptions, not validated historical or medical data.
- The frontend uses periodic polling rather than a streaming connection.
