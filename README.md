# AI World: How AI Evolves the World

AI World is an experimental, generational life simulation. Two independent minds begin in a rugged early-hominin habitat and make choices about survival, relationships, learning, conflict, and culture. A FastAPI server owns the world rules; Ollama supplies each person's decision using one shared model and that person's private memories, traits, and observations.

The spectator watches through a dark 3D landscape. People walk between resources and structures; selecting a person opens their life and editable biological stats. A world-wide model selector changes the brain used by everyone. Natural events can occur without intervention, and the spectator may drag hazards onto the land and see distance-based consequences.

> **Status:** Local playable prototype. This is an exploration of a simulation design, not a scientific reconstruction of hominin evolution or a prediction of real human history.

## What happens in a world

1. A world starts with two adults, one male and one female, and a shared local Ollama model (`gemma4:e2b` by default).
2. On each simulated day, the backend advances weather, ecology, resources, disease risk, and natural hazards.
3. Each living person from age three receives a private observation. The same configured model proposes a bounded action for each decision-capable person. Their memories, learned knowledge, relationships, age, needs, and traits differ, so their decisions can differ too; infants remain dependent on caregivers.
4. The available action schema is narrowed to choices that fit the person's current needs and surroundings. If they choose a visible resource that is nearby but not underfoot, the engine advances them one step toward it and records both the model's proposal and the resolved movement.
5. The simulation applies world rules. People can forage, drink, move, rest, gather, communicate, help, teach, form groups, bond, reproduce, fight, build, and create cultural beliefs.
6. Biology advances: hunger, thirst, energy, disease, immunity, pregnancy, birth, inherited traits, aging, injury, and death all affect the population.
7. The API saves the world in SQLite. The 3D client visualizes the authoritative state and its timeline.

When Ollama cannot decide or returns an invalid action, a survival fallback is recorded in the timeline. The fallback keeps the world advancing, but it is not a language-model decision.

## Spectator controls

- Orbit and zoom around the continuous, terrain-shaped 3D land. The scene has no visible map tiles.
- Watch individual low-poly human figures animate as they move between world coordinates.
- Select a person to review their health, hunger, thirst, energy, age, disease, family, relationships, knowledge, traits, and recent memories.
- Adjust a living person's health, hunger, thirst, or energy. The server records the intervention and immediately applies death rules when health reaches zero.
- Choose one installed Ollama model for the whole world. Every current person and every newborn then uses that model; their personal memories and traits remain separate.
- Drag wildfire, storm, flood, drought, disease outbreak, or mishap from the event palette onto the land. World effects use a circular footprint with distance falloff. Events may also occur naturally.
- Run, pause, step, speed up, or reset the simulation. Inspect births, deaths, choices, teaching, diseases, conflicts, construction, culture, and spectator interventions in the timeline.

## Local setup

Requirements: Python 3.11 or newer, Node.js 20 or newer, and [Ollama](https://ollama.com/) with `gemma4:e2b` installed. Ollama is optional for the server to run; without it, the simulation uses its visible fallback policy.

```powershell
ollama pull gemma4:e2b
python -m pip install -r backend/requirements.txt
npm ci --prefix frontend
npm run build --prefix frontend
python -m uvicorn app.main:app --app-dir backend --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) for the spectator and [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) for the API documentation. Build the bundled Three.js frontend again after editing `frontend/app.js`:

```powershell
npm run build --prefix frontend
```

The generated bundle is `backend/app/static/app.bundle.js`, so the served scene does not need a browser CDN connection. The default world snapshot is `backend/data/world.sqlite3`; it is local and ignored by Git. A `.env.example` file documents the Ollama URL/model, timeout, natural event probabilities, and database path.

## API overview

- `GET /api/health` — FastAPI and Ollama/model availability.
- `GET /api/models` — installed local Ollama models.
- `GET /api/world` — current authoritative world snapshot.
- `POST /api/world/tick` — advance one simulated day and collect agent decisions.
- `POST /api/world/run?interval_seconds=3` / `POST /api/world/pause` — control the continuous simulation loop.
- `POST /api/world/reset?seed=7` — create and save a fresh world.
- `PATCH /api/world/model` — set one model for all agents.
- `PATCH /api/agents/{agent_id}/state` — apply a spectator adjustment to biological stats.
- `POST /api/events` — place a spectator event at a world coordinate or person.

## Repository map

- [idea.md](idea.md) — product theme, simulation premise, biology, society, and spectator role.
- [codebase.md](codebase.md) — file-level implementation and debugging guide.
- `backend/app/simulation/engine.py` — authoritative biology, hazards, action resolution, and social rules.
- `backend/app/agent_brain/ollama_client.py` — private observations and structured model decisions.
- `backend/app/static/` — FastAPI-served spectator interface and generated bundle.
- `frontend/app.js` — Three.js scene, interactions, and API-backed UI.
- `frontend/build.mjs` — bundles Three.js and the spectator script for local/offline serving.

## Simulation boundaries

One tick is one simulated day. Population growth and technology do not represent six million years of calibrated history; the early-hominin starting point is a thematic premise, and agent rules are simplified assumptions. LLMs suggest actions but do not control physics, biology, consent, or persistence. Natural-event probabilities and disease effects are tunable prototype values, not medical or historical facts.

## License

MIT. See [LICENSE](LICENSE).
