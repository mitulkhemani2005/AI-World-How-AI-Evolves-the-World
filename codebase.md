# Codebase Map and Debugging Guide

## Current status

The first backend slice is implemented. It runs an in-memory world for two agents, calls Ollama for agent actions, and exposes world controls through FastAPI. There is no frontend, durable persistence, reproduction, or test suite yet. The map below marks implemented and planned paths separately.

## Repository layout

```text
.
├── README.md
├── idea.md
├── codebase.md
├── LICENSE
├── backend/
│   ├── requirements.txt
│   └── app/
│       ├── __init__.py
│       ├── main.py
│       ├── settings.py
│       ├── domain.py
│       ├── api/
│       │   ├── __init__.py
│       │   └── routes.py
│       ├── agent_brain/
│       │   ├── __init__.py
│       │   └── ollama_client.py
│       └── simulation/
│           ├── __init__.py
│           └── engine.py
├── apps/web/                     # Planned spectator frontend
└── data/                         # Planned scenario definitions
```

## Implemented file responsibilities

| File | Responsibility | Inspect when… |
| --- | --- | --- |
| `backend/requirements.txt` | FastAPI, Uvicorn, and HTTPX dependencies. | Dependency installation fails. |
| `backend/app/main.py` | Creates the FastAPI application, enables local frontend CORS, and registers routes. | The server fails to start or routes are not registered. |
| `backend/app/settings.py` | Reads Ollama URL/model, timeouts, event probabilities, and event-log limit from environment variables. | A default or runtime setting is wrong. |
| `backend/app/domain.py` | Defines Pydantic agents, resources, world state, events, actions, and request schemas. | API validation or serialized state is wrong. |
| `backend/app/api/routes.py` | Implements health, world read/tick/run/pause/reset, model change, and spectator-event endpoints. | An API response or request behavior is wrong. |
| `backend/app/agent_brain/ollama_client.py` | Checks Ollama/model availability, constructs agent observations, calls `/api/chat`, and validates action JSON. | An agent gets fallback decisions or proposes malformed actions. |
| `backend/app/simulation/engine.py` | Owns the in-memory world, tick loop, resource regeneration, action resolution, biology, disease, events, and mortality. | The world changes incorrectly or an event has the wrong cause/source. |
| `backend/app/__init__.py`, `api/__init__.py`, `agent_brain/__init__.py`, `simulation/__init__.py` | Mark Python packages. | Python cannot resolve an application package. |

## Important behavior boundaries

- **FastAPI routes** validate HTTP input and call the engine. They should not contain simulation rules or LLM prompts.
- **Agent brain adapter** returns a proposed, schema-validated action. It cannot mutate world state.
- **Simulation engine** owns authoritative consequences: movement bounds, resource use, needs, disease, injury, death, and event provenance.
- **Frontend (planned)** will display backend state and submit commands. It must not duplicate authoritative biology or simulation rules.
- **Persistence (planned)** will replace the current in-memory-only state. Until then, restarting the backend resets the world.

## Planned modules as the simulation grows

- `backend/app/biology/needs.py`, `disease.py`, `aging.py`, `reproduction.py` — move biological rules out of the engine as they become richer; handle inheritance and births here.
- `backend/app/society/relationships.py`, `communication.py`, `learning.py`, `culture.py` — relationships, idea sharing, parent-to-child teaching, groups, beliefs, and social norms.
- `backend/app/storage/` — save and load world state, agent memories, model assignments, and event history behind repository interfaces.
- `apps/web/` — interactive map, agent inspector, event timeline, model selection, and spectator controls.
- `data/` — versioned starting scenarios, terrain/resource definitions, and tunable event parameters.
- `backend/tests/` — focused API and simulation behavior tests once test coverage is requested and added.

## Core data concepts

- **Agent:** Stable ID, age, biological state, position, individual memory, selected model, and alive/deceased status.
- **World:** Seed, simulated day, map bounds, agents, resource nodes, running state, and recent events.
- **Observation:** Bounded information visible to one agent for one decision.
- **Action:** Structured proposal such as forage, drink, rest, move, communicate, or help; validated and resolved by the engine.
- **Event:** Timestamp/tick, source (`natural`, `agent_action`, `spectator`, or `system`), affected agents, cause, and details.
- **Lineage (planned):** Parent/child links and inherited biological traits, kept distinct from learned culture.

## Debugging workflow

1. Reproduce the issue using the same starting seed and model configuration.
2. Find the first incorrect event or state transition in the world event list.
3. Identify its source: model proposal, action resolution, biological rule, natural event, or spectator command.
4. If model-related, inspect the agent observation, assigned model, Ollama response, and fallback event.
5. If world-rule-related, inspect the pre-state, rule inputs, and post-state in `simulation/engine.py`.

The decision path should remain inspectable as:

```text
observation built → action proposed → action validated → world rules applied → event recorded → frontend updated
```

The structured world transition and its cause are the source of truth. Free-form LLM explanations should not be treated as proof of why an event happened.

## Keeping this map useful

When adding a file, document its responsibility, inputs/outputs, dependencies, and the first place to inspect when it fails. Update the layout whenever files move. Add setup and run commands only after they have been checked against the actual implementation.
