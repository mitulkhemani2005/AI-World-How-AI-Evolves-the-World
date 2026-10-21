# Origin: AI World

**Origin: AI World** is an experimental generational life simulation. Two independent AI minds begin in an early hominin world and make choices about survival, relationships, learning, conflict, and culture. A FastAPI backend owns biology and world rules; a separate Three.js frontend lets the spectator watch their lives unfold across a procedural, fictional 3D globe.

> **Status:** Local playable prototype. It explores a fictional simulation design; it is not a scientific reconstruction of hominin evolution or a prediction of human history.

## The idea

Two agents start the world: one male and one female, in a viable natural habitat near food, wood, and water. Both use the pinned local Ollama model `qwen2.5:0.5b`, while keeping distinct memories, traits, relationships, and observations. They remember useful food and water locations and places they build, and can route toward remembered resources or shelters when urgent needs or dangerous weather arise. They need to find food and water, rest, respond to illness and danger, communicate, form relationships, and decide whether to have and care for children. As generations grow, they may teach, build homes and property, form groups, fight, create beliefs, or disappear.

The spectator does not direct normal daily choices. The world advances on its own once started. A spectator can inspect and adjust an individual's biology or drag an event onto the land. Disasters and diseases can also happen through simulation rules without intervention. [Implementation status and further plans](implementation-status.md) distinguishes working mechanisms from future research.

## What the simulation models

1. Every simulated month, the backend advances seasons, weather, resources, biological needs, disease, pregnancy, age, animal lives, crops, and natural hazards. The spherical world has oceans, rivers, lakes, mountains, grasslands, farmland, deserts, ice, and several forest biomes.
2. Decision-capable living agents get separate private observations and a short menu of feasible opportunities. Qwen chooses one intention and explains why. A chosen resource trip continues across physical movement steps; a construction project can gather the required material batch. Source fields distinguish LLM decisions, continued intentions, and inference fallbacks.
3. The simulation resolves choices under shared world rules. Agents can forage, drink, hunt, tame, care for animals, gather, farm, cook, talk, teach, form groups, build, bond, reproduce, fight, and create cultural beliefs.
4. Wild animals move, eat, drink, reproduce, and die within shared population limits. Missing food wildlife replenishes slowly; excess animals migrate away without leaving carcass piles. Agents can tame domestic species or companions, provide care, collect eggs and milk, or hunt wildlife. Edible plants regrow in suitable biomes.
5. Farm plots need a farm, knowledge, suitable soil, water, and time. Harvests can fail through drought, fire, or neglect. Raw meat, spoiled food, and contaminated water can cause foodborne or waterborne disease.
6. Need, injury, disease, exposure, conflict, childbirth complications, and aging can cause death at any age. Children depend on caregivers and can learn through agent teaching.
7. Parents share nearby food and water with dependent children. Shelter reduces weather exposure, while severe hazards can damage buildings, crops, wildlife, food, and water.
8. Population is capped at 128 living agents so local inference and simulation remain tractable. Human extinction is recorded while ecology and the clock continue. Only an explicit spectator pause stops a running world.
9. The backend persists each world and its random stream in SQLite. The frontend reads snapshots and displays agents and world objects on the fictional globe.

If Ollama is unavailable or a response is invalid, a recorded survival fallback keeps the prototype moving. That fallback is a rule-based decision, not an LLM response. Animals use explicit hardcoded NPC behavior in the simulation engine and never call the LLM.

## Spectator experience

- See a dark, minimalist interface around an orbitable procedural globe with human figures, wild and domesticated animals, growing crops, resources, forests, and buildings. Its fictional continents are generated from simulation rules and do not copy real Earth geography or satellite imagery. Drag to orbit, scroll to zoom, and click a figure to open that person's life record. If the device blocks WebGL, a 2D compatibility globe still shows terrain and agents.
- Review age, health, hunger, thirst, energy, fear, stress, loneliness, disease, family, pregnancy, knowledge, temperament, last action, and recent memories. Adjust a living agent's biological stats from their inspector.
- Every person uses `qwen2.5:0.5b` with independent identity and private history. Ollama requests all model layers on GPU, keeps Qwen resident, and retries allocation failures using RAM/CPU. The header reports actual GPU/CPU residency.
- Drag a wildfire, storm, flood, drought, disease outbreak, or mishap from the event menu onto a location on the globe. Or click an event and then its location. Fire, rain clouds, flood waves, drought dust, outbreak particles, and mishaps animate there without pausing the world; equivalent natural events can occur without the spectator.
- Run, pause, or reset the world. The world runs only at 1×: **one simulated month takes one real minute**, and 12 months make a year. The clock advances during inference; agents can make decisions throughout the month, limited by model latency. Urgent food, water, exhaustion, illness rest, and infant care can invoke a recorded physical survival reflex while inference waits. These reflexes consume real resources and never supply social consent. Pause discards late model results.
- Open the life timeline to review agent work, births, deaths, and world events. Select All, Work, Newborns, or Deaths, then click an agent's entry to inspect them on the globe. Birth and death updates stay in the timeline instead of appearing as life-event pop-ups.
- Start near the people and follow their movement. Use **People**, **Globe**, **+**, and **−** for camera control, or orbit and scroll directly. Action labels show physical work and pending intentions; the inspector explains results and decision sources.
- The globe uses stable lighting and displays only the simulation year and month; it does not read the spectator's computer clock. Every action appears above its agent. Dead people remain visible on the ground until a nearby agent chooses to mourn or bury them.
- Hover people, animals, resources, crops, buildings, trees, and terrain to inspect them. Animals are small background food NPCs. Wildlife is limited by healthy habitat to at most 24 living wild animals, and kept animals have a separate settlement budget (4 + 2 per living person, capped at 24); no animal totals appear in the interface.
- Agents can choose terrain care: restore habitat health and soil fertility, clean contaminated resources, and use available water. Hazards and wood gathering damage land; degraded soil affects crops.
- Running worlds resume across backend restarts and retry recoverable errors. Reset preserves the current run/pause choice. New founders start on adjacent land, with reproduction still requiring independent mutual consent.
- Family planning gets attention once immediate survival needs are met. A model-selected bond or child proposal remains answerable for seven simulated months; the other person must independently accept. Agents can approach a nearby partner. The current deliberately compressed gestation is **9 simulated months**. Each parent can choose a name through their Qwen decision menu. If birth happens first, the baby receives a provisional name derived from the parents' names; a parent can choose a lasting name during the newborn period. The baby's sex is sampled independently. Infants are smaller figures carried by their primary living caregiver.
- Fear rises during predator attacks, fights and deaths; stress and loneliness respond to danger, separation and social care. Bonded partners and parents may travel to one another, provide care, share ideas and teach. Repeated social actions are limited by the simulation clock. Pregnancy changes food, water and energy needs. Everyone can learn work and caregiving skills; occupations are shaped by individual traits and circumstances rather than fixed sex roles.
- Death reports show the recorded fatal cause, with hunger, thirst, energy, disease and damage context in the life record. Historical snapshots keep their original attribution instead of inventing an exact cause.
- Buildings and crafted objects are shared. Nearby families and groups pool actual materials. Public farms, campfires, granaries and shelters can be used by anyone; equipped tools can be handed over. Family, internal-group and external fights remain possible and are recorded distinctly.
- Construction needs stable dry land; farms need open, moist, fertile soil. Agents walk to suitable sites, consider existing shelter capacity and practical local needs, and repair damaged objects. Duplicate buildings or unneeded items are rejected before materials are spent.
- Agents can experiment to discover weapon making and raft building, craft spears, stone axes and four-person rafts, equip protection, board, sail across the globe and disembark on other land. Items use materials, wear out, and can be repaired. New techniques can be taught.
- Wolves and big cats are predator species. Their NPC encounters can injure or kill people; weapons, nearby caregivers, shelters and campfires can repel attacks. Predators remain inside the small animal budget, with at most two predators.
- Inspect the world API and its retained event records for debugging and provenance.

## Technology

- **Frontend:** Vite, Three.js, native HTML/CSS/JavaScript. It is a separate application, not rendered by FastAPI.
- **Backend:** Python, FastAPI, Pydantic, HTTPX.
- **Decision model:** Ollama `qwen2.5:0.5b`, shared across all agents. The model is pinned so all people use the same small Qwen model.
- **Persistence:** SQLite world snapshots.

## Local setup

Requirements: Python 3.11 or newer, Node.js 20 or newer, and Ollama. The backend can also run without Ollama using its visible survival fallback.

### 1. Install the model

```powershell
ollama pull qwen2.5:0.5b
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

The backend starts the local `ollama serve` process when Ollama is installed but not already running, then warms Qwen on the GPU. The API and interactive documentation are at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). FastAPI exposes the API only; it does not serve or build the spectator page.

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

- `GET /api/health` — API, Ollama, configured model readiness, and actual compute residency.
- `GET /api/models` — the supported shared Qwen model and local availability.
- `GET /api/world` — authoritative world snapshot, including retained event records.
- `POST /api/world/tick` — legacy manual step endpoint; the spectator interface does not expose it.
- `POST /api/world/run?interval_seconds=3` / `POST /api/world/pause` — start or stop autonomous simulation.
- `PATCH /api/world/speed` — legacy compatibility endpoint; the simulation stays at 1×.
- `POST /api/world/reset?seed=7` — start a fresh world.
- `PATCH /api/world/model` — validate/apply the pinned shared Qwen model; other models are rejected.
- `PATCH /api/agents/{agent_id}/state` — adjust an individual's health, hunger, thirst, or energy.
- `POST /api/events` — apply a geographically bounded spectator event.

## Repository map

- [idea.md](idea.md) describes the product theme, agents, biology, culture, and spectator experience.
- [codebase.md](codebase.md) maps files to responsibilities and gives a debugging path.
- `frontend/src/app.js` contains the continuous terrain, human figures, direct selection, inspector, controls, and API calls.
- `frontend/src/styles.css` defines the minimalist dark interface and responsive overlays.
- `frontend/src/surface-motion.js` handles surface travel without unsupported vector APIs.
- `frontend/index.html` is the independent frontend entry page; `frontend/vite.config.js` configures the dev API proxy.
- `backend/app/simulation/engine.py` is the authoritative world engine.
- `backend/app/simulation/planning.py` shares demand, construction-site and family material rules between the model menu and resolver.
- `backend/app/simulation/activities.py` resolves shared crafting, repairs, boating and predator encounters.
- `backend/app/agent_brain/ollama_client.py` supplies individual observations and structured choices.

## Boundaries

The clock advances from elapsed real time at a fixed 1× rate; model decisions never directly advance the calendar. One month takes 60 real seconds and a 12-month year takes 12 minutes. Agent actions can occur several times within a month. The legacy `tick` endpoint can manually advance a month, but the spectator interface has no manual step or speed control. Saved worlds migrate their clock while preserving world identity, people, and run/pause state. The starting period of 6–7 million years ago is thematic; the 9-month pregnancy, small map, life-stage, disease, and social rules are simplified assumptions, not calibrated biology or history. LLMs propose choices but cannot directly mutate physics, consent, biology, or persistence.

## Verification

```powershell
npm test --prefix frontend
npm run build --prefix frontend
$env:PYTHONPATH = "backend"
python -m unittest discover -s backend/tests -v
```

Frontend checks execute the actual application update and frame functions with real Three.js geometry and math, replacing browser/GPU surfaces. They cover populated frames, movement, UV alignment, figure selection, camera collision limits, hover inspection, event animation/disposal, compatibility picking, death, burial, and reset; they do not claim to test a physical GPU. Backend checks use temporary databases and cover the shared-model contract, fallback construction, timing during slow inference, pause, resource conservation, food production, teaching, consent, birth, disease, persistence, wildlife spawning, terrain care, GPU-first fallback, fixed-clock behavior, and continued running after extinction or recoverable errors.

## License

MIT. See [LICENSE](LICENSE).
