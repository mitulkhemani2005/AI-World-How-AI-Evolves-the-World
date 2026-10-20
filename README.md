# AI World: How AI Evolves the World

An experimental life simulation in which autonomous AI-driven people begin in a small early-hominin world and shape its future through survival, relationships, learning, conflict, and culture.

The project is intended to let a spectator watch a society emerge over generations. Agents make their own choices; the world model determines what happens as a result. The spectator can observe hands-off, change an agent's language model, or introduce an event. The world can also produce events naturally.

> **Project status:** A playable local prototype is implemented. It includes a FastAPI backend, a live spectator page, Ollama-driven agent decisions, SQLite world snapshots, basic biology, reproduction, social interactions, property, beliefs, and event controls. It is an early simulation model, not a scientific reconstruction.

## Vision

The simulation starts with two early hominins, one male and one female, approximately at the beginning of the hominin lineage (around 6–7 million years ago). They and their descendants live in an environment with resources, biological needs, disease, and danger. Over time, agents may develop communication, teaching, customs, beliefs, tools, buildings, and social institutions.

The simulation explores possible outcomes under its rules. It is not intended to predict exactly what real human history or the future of AI will be.

Read [idea.md](idea.md) for the full theme and design principles.

## Core concepts

- **Independent minds:** Every agent has its own brain instance, memories, relationships, and life history. The spectator can choose or change the LLM model assigned to an agent.
- **Biological lives:** Agents have bodies, needs, age, health, injuries, reproductive health, and inherited traits. Birth and death can happen at any age.
- **Learning across generations:** Children inherit biological traits and learn from parents and community through observation, practice, communication, and teaching.
- **A changing environment:** Food, water, shelter, weather, hazards, and diseases affect agent decisions and survival. Events can arise naturally; the spectator can also trigger selected events.
- **Emergent society:** Relationships, cooperation, conflict, family structures, leadership, group behavior, beliefs, religion, morality, property, and crime can develop through agent interactions and world conditions.
- **Visible simulation:** The spectator page exposes the map, agent state, events, relationships, family tree, buildings, and the effects of spectator interventions.

## How it is intended to work

1. The **FastAPI backend** owns the simulation state and exposes APIs to the frontend.
2. Each **agent brain** observes its available information and proposes an action based on its own state, memory, and assigned LLM model.
3. The backend validates the action and applies it through the simulation's biology, environment, and social rules.
4. Agents communicate, form relationships, have children, and pass knowledge through social learning.
5. The **frontend** renders the current world and its history. Spectator actions are sent to the backend and recorded as interventions in the event timeline.

Agent models should choose among bounded actions provided by the simulation. They do not directly edit the world state. This separation makes behavior inspectable and helps debug whether an outcome came from an agent decision, a world rule, or a spectator intervention.

The backend uses FastAPI for API routes, simulation orchestration, and the Ollama adapter. The frontend communicates with it through the API and never calls the model directly.

## Spectator controls

- Inspect a live map with agents, resources, hazards, and structures.
- Select an agent to view needs, health, memories, relationships, lineage, and current model.
- Follow conversations, shared ideas, teaching, births, deaths, disease, conflict, and discoveries.
- Pause or speed up the simulation.
- Change an agent's LLM model while preserving that agent's world identity and stored history where possible.
- Trigger supported events such as a flood, wildfire, injury, or disease outbreak.
- Review a timeline that distinguishes naturally generated events from spectator-triggered ones.

## Implemented simulation systems

- A shared 2D habitat with seasonal weather and renewable food, water, wood, and stone.
- Separate agents with individual memories, learned knowledge, inherited traits, health, needs, model assignments, and family links.
- Ollama model selection per agent, structured action proposals, and an explainable fallback when a model is unavailable.
- Aging, disease, transmission, recovery, injury, pregnancy, birth, inheritance, childcare, and death at any age.
- Communication, trust, mutual bonding and reproductive choice, affairs, helping, teaching, conflict, groups, and gang-like group types.
- Resource gathering and buildings that unlock as shared construction knowledge grows; ownership is recorded.
- Agent-created beliefs, including deities, myths, virtues, evil, and taboos.
- Natural mishaps, disease emergence, and disasters, plus spectator-triggered injury, outbreak, wildfire, storm, flood, or drought.
- A browser frontend with live map, agent inspector, model controls, event timeline, culture view, and run/pause/speed/reset controls.
- SQLite snapshot persistence so the world continues after an API restart.

The prototype does not simulate six million years of detailed history. Each tick is one simulated day; world progression depends on agent decisions, resource constraints, and the rules currently implemented.

## Repository guide

- [idea.md](idea.md) — product theme, world premise, agent behavior, biology, society, and spectator role.
- [codebase.md](codebase.md) — current repository inventory and proposed file-by-file implementation/debugging map.
- [LICENSE](LICENSE) — MIT license.

## Development status and setup

The app uses FastAPI, Python, SQLite, a dependency-free browser UI, and Ollama. From the repository root, install the backend dependencies and start the API:

```powershell
cd backend
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

The spectator page is served at `http://127.0.0.1:8000/`; interactive API documentation is at `http://127.0.0.1:8000/docs`. The default LLM is `gemma4:e2b`. Ollama must be running locally and the model must be installed. If Ollama is unavailable or returns an invalid action, the simulation uses a basic survival fallback and records that decision in the event history. `.env.example` lists supported settings; set them in the shell or copy it to `.env` and pass `--env-file ..\.env` to Uvicorn. Do not put provider secrets in browser code.

API routes:

- `GET /api/health` — backend and Ollama availability.
- `GET /api/models` — installed Ollama models.
- `GET /api/world` — current world state.
- `POST /api/world/tick` — advance one simulated day.
- `POST /api/world/run?interval_seconds=3` — run repeated ticks.
- `POST /api/world/pause` — pause repeated ticks.
- `POST /api/world/reset?seed=7` — create a fresh starting world.
- `PATCH /api/agents/{agent_id}/model` — change an agent's LLM model.
- `POST /api/events` — trigger a spectator event.

World snapshots are stored in `backend/data/world.sqlite3` by default. This file is ignored by Git.

## Design boundaries

- Clearly label simulated outcomes as outcomes of this model and its assumptions.
- Keep world rules, agent choices, and spectator interventions separately observable.
- Make births, deaths, disease spread, relationship changes, and model changes inspectable in the event history.
- Avoid presenting generated religious or moral beliefs as factual claims about real people or history.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
