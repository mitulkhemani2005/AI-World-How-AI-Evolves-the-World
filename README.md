# AI World: How AI Evolves the World

AI World is an experimental generational life simulation. Two independent AI minds begin in an early hominin world and make choices about survival, relationships, learning, conflict, and culture. A FastAPI backend owns biology and world rules; a separate Three.js frontend lets the spectator watch their lives unfold in a continuous, tile-free 3D land habitat.

> **Status:** Local playable prototype. It explores a fictional simulation design; it is not a scientific reconstruction of hominin evolution or a prediction of human history.

## The idea

Two agents start the world: one male and one female. Both use the same spectator-selected local Ollama model, while keeping distinct memories, traits, relationships, and observations. They need to find food and water, rest, respond to illness and danger, communicate, form relationships, and decide whether to have and care for children. As generations grow, they may teach, build homes and property, form groups, fight, create beliefs, or disappear.

The spectator does not direct normal daily choices. The world advances on its own once started. A spectator can still change the shared model, inspect and adjust an individual's biology, or drag an event onto the land. Disasters and diseases can also happen through simulation rules without intervention.

## What the simulation models

1. Every simulated day, the backend advances seasons, weather, resources, biological needs, disease, pregnancy, age, and natural hazards.
2. Decision-capable living agents get separate private observations. The same configured LLM proposes each agent's bounded action, with that person's own history and current circumstances.
3. The simulation resolves choices under shared world rules. Agents can forage, drink, move, rest, gather, talk, help, teach, form groups, build, bond, reproduce, fight, and create cultural beliefs.
4. Need, injury, disease, exposure, conflict, and aging can cause death at any age. Children depend on caregivers and can learn through agent teaching.
5. The backend persists each world in SQLite. The frontend reads snapshots and displays agents and world objects across the land.

If Ollama is unavailable or a response is invalid, a recorded survival fallback keeps the prototype moving. That fallback is a rule-based decision, not an LLM response.

## Spectator experience

- See a dark, orbitable 3D landscape with human figures, resources, trees, and buildings. The land is one continuous terrain surface, with no map tiles or planet-sized globe. Drag to orbit, scroll to zoom, and click a figure to open that person's life record.
- Review age, health, hunger, thirst, energy, disease, family, pregnancy, knowledge, temperament, last action, and recent memories. Adjust a living agent's biological stats from their inspector.
- Select one installed Ollama model for the whole world. Each agent still has an independent identity and private history.
- Drag a wildfire, storm, flood, drought, disease outbreak, or mishap from the event menu onto a location on the land. The simulation applies its geographic consequences; equivalent natural events can occur without the spectator.
- Run, pause, advance one day, or reset the world. The minimalist spectator does not use a name roster or a visible timeline.
- Inspect the world API and its retained event records for debugging and provenance.

## Technology

- **Frontend:** Vite, Three.js, native HTML/CSS/JavaScript. It is a separate application, not rendered by FastAPI.
- **Backend:** Python, FastAPI, Pydantic, HTTPX.
- **Decision model:** Ollama, default model `gemma4:e2b`, shared across agents.
- **Persistence:** SQLite world snapshots.

## Local setup

Requirements: Python 3.11 or newer, Node.js 20 or newer, and Ollama. The backend can also run without Ollama using its visible survival fallback.

### 1. Install the model

```powershell
ollama pull gemma4:e2b
```

### 2. Install dependencies

```powershell
python -m pip install -r backend/requirements.txt
npm ci --prefix frontend
```

### 3. Start the FastAPI backend

From the repository root:

```powershell
python -m uvicorn app.main:app --app-dir backend --reload --port 8000
```

The API and interactive documentation are at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). FastAPI exposes the API only; it does not serve or build the spectator page.

### 4. Start the independent frontend

In a second terminal:

```powershell
npm run dev --prefix frontend
```

Open [http://localhost:5173](http://localhost:5173). Vite serves the UI and proxies `/api` requests to the backend on port 8000.

### Production frontend build

```powershell
npm run build --prefix frontend
npm run preview --prefix frontend
```

Vite writes static production assets to `frontend/dist/`. Host those assets separately from FastAPI and set `VITE_API_BASE_URL` to the FastAPI base URL when building (for example, `https://api.example.com`). Set `FRONTEND_ORIGINS` to the frontend origin or comma-separated list of origins in the backend deployment. The Vite development server and preview server proxy `/api` locally and do not need that change.

## API overview

- `GET /api/health` — API, Ollama, and configured model readiness.
- `GET /api/models` — installed local models.
- `GET /api/world` — authoritative world snapshot, including retained event records.
- `POST /api/world/tick` — advance one simulated day and collect agent decisions.
- `POST /api/world/run?interval_seconds=3` / `POST /api/world/pause` — start or stop autonomous simulation.
- `POST /api/world/reset?seed=7` — start a fresh world.
- `PATCH /api/world/model` — switch all agents to one shared model.
- `PATCH /api/agents/{agent_id}/state` — adjust an individual's health, hunger, thirst, or energy.
- `POST /api/events` — apply a geographically bounded spectator event.

## Repository map

- [idea.md](idea.md) describes the product theme, agents, biology, culture, and spectator experience.
- [codebase.md](codebase.md) maps files to responsibilities and gives a debugging path.
- `frontend/src/app.js` contains the continuous terrain, human figures, direct selection, inspector, controls, and API calls.
- `frontend/src/styles.css` defines the minimalist dark interface and responsive overlays.
- `frontend/index.html` is the independent frontend entry page; `frontend/vite.config.js` configures the dev API proxy.
- `backend/app/simulation/engine.py` is the authoritative world engine.
- `backend/app/agent_brain/ollama_client.py` supplies individual observations and structured choices.

## Boundaries

One tick is one simulated day. The starting period of 6–7 million years ago is thematic; the current small map, life-stage, disease, and hazard rules are simplified assumptions, not calibrated biology or history. LLMs propose choices but cannot directly mutate physics, consent, biology, or persistence.

## License

MIT. See [LICENSE](LICENSE).
