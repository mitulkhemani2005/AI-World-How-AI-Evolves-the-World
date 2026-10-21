# Working simulation and next stages

## Current behavior

The canonical design is [idea.md](idea.md). Later requirements pin Qwen, use a white interface, and display local computer time while biology uses elapsed real time (365 simulated days in 12 real minutes at default 1×). Existing SQLite worlds migrate without being reset. New worlds place the founders on adjacent land in a viable natural habitat; different seeds produce different terrain.

| System | Current implementation |
| --- | --- |
| World display | Procedural globe, aligned biome texture and entity coordinates, human figures, animals, resources, buildings, crops, orbit/zoom, a people view that follows movement, direct selection, hover inspection, camera collision protection, and visible rendering errors. A 2D compatibility view is available if WebGL initialization fails. |
| Private minds | Separate observations, memories, relationships, traits and skills. One shared Qwen model selects a concrete opportunity; the engine executes and validates it. Meaningful task continuations avoid random movement between every LLM turn. |
| Survival | Daily nutrition, hydration, fatigue, illness and exposure. Explicit physical survival reflexes work during inference; spring water replenishes daily and new stock dilutes spoilage. Food and water used in care consume real resources. Rest and care cannot heal unlimited health in one day. |
| Shelter and material work | Local navigation to suitable dry building sites, capacity/demand checks, family/group material pools, real building costs, repairs, shared shelter and property creator records. |
| Animals and farming | Small NPC food animals, movement independent of inference, shared habitat/settlement budgets for migration, weekly spawning and births, taming, care, food collection limited by day, crops that require planting and growth before harvest, contamination and raw-food disease risk. Building a farm does not create an instant food stock. |
| Terrain care | Habitat health, fertility and pollution; gathering/hazard damage; daily agent restoration, resource cleaning and watering; soil quality affects crops and wildlife habitat. |
| Family | Independent model choices for bonding/reproduction, seven-day proposals answerable across turns, partner navigation, 9-day pregnancy, parents' naming choices, random baby sex, birth, postpartum recovery, inherited traits, carried infants and teaching of actually learned knowledge. Children do not inherit parents' skill lists. |
| Shared tools and exploration | Real material experiments, learned weapon/raft techniques, spears, stone axes, shared handover, repairs, durability, four-person rafts, boarding/sailing/disembarking and island landings. |
| Social outcomes | Fear, stress and loneliness respond to threat, loss, care and separation. Families can reunite physically. Communication memories, relationship changes, conflict, community/family/gang groups and deity/myth/virtue/evil/taboo records remain basic mechanisms, not complete sociological systems. |
| Death and hazards | Disease, injuries, starvation/dehydration consequences, age risks, bodies, mourning, burial, grave markers, natural hazards and bounded spectator events with separate sources and geographic animations. Exact fatal damage is recorded immediately and reported in the UI. Predator attacks, armed/caregiver defence, and shelter/fire protection are implemented; at most two predators remain within the animal budget. Events never pause the world. |
| Time and persistence | A separate elapsed-time loop advances biology during slow model calls. Action rounds run on their own cadence. Pause invalidates late proposals. SQLite stores pending work, speed, run/pause choice and random state. Default speed is fixed 1× (12 minutes per year); spectator speeds reach 16×. Running worlds resume on restart and continue through extinction and recoverable errors. |
| Compute | Only Qwen; full GPU requests, resident warmup, RAM/CPU retry on GPU allocation failure, and actual device/VRAM status. Local Ollama confirms 100% GPU on the RTX 4060. |
| Inspection | Action reason/result, current project, source (`llm`, `continuation`, `fallback`), original intention source, event provenance, biological stats, family and knowledge. |

The engine makes feasible opportunities available and resolves consequences. It does not guarantee births, technological progress, cooperation, survival, religion or any particular historical path. A small model can still make poor choices. Failed inference is explicitly recorded as fallback behavior.

## Verification

`frontend/tests/world-runtime.test.js` executes the application with real Three.js math/geometry and a stub GPU/DOM. This is a runtime regression check, not a screenshot or physical-GPU test. It reproduces the populated scene transition that previously called an unsupported vector method and froze the initial ocean sphere.

`backend/tests/test_world.py` and `backend/tests/test_continuous_world.py` check temporary worlds for physical accounting, bounded actions, shared-model requests, model autonomy, task execution, slow inference timing, pause semantics, farm growth, animal products, learned skills, mutual consent, birth, disease and saved-state recovery, GPU fallback, speed, terrain care, wildlife spawning, close founders, and continued ecology after extinction/errors. Tests do not touch the spectator's saved world.

An isolated live Ollama run also exercised Qwen choices through shelter/campfire construction, teaching, chicken domestication, egg collection and animal care without JSON-validation fallbacks. This demonstrates an observable working loop; it is not evidence of guaranteed long-term civilization growth.

## Further development

1. **Long-run reliability:** seeded multi-generation scenario runs, starvation/extinction diagnostics, queue budgets for larger populations, measured response latency, save slots and event replay. Retain the 12-minute year at default 1× and explicit speed controls.
2. **Ecology and biology depth:** explicit nutrition stores, inherited disease susceptibility, pregnancy/nursing costs, contact-based disease transmission, seed stocks, deeper soil nutrient cycles, food chains and seasonal migration. Current biology is illustrative.
3. **Knowledge and technology:** replace the current simplified building-count knowledge levels with individual discoveries, richer tool recipes, practice, experimentation, prerequisites, forgotten knowledge and communal construction projects.
4. **Property and institutions:** extend ownership records into inventories, transfer, trade, disputes, norms, leadership succession, crime, law and collective decisions. Current group and belief records do not implement economies or governments.
5. **Culture and communication:** persistent narratives, rituals, teaching success/failure, language development, beliefs that affect future decisions and conflicts, and inspectable chains of idea transmission.
6. **Rendering and scale:** higher-detail rigged people/animals, terrain detail around settlements, streamed snapshots, replay and larger habitats after simulation reliability is measured.

These are explicit next stages. Millions of years of biological evolution and a complete modern civilization are not implemented or scientifically validated by the present prototype.

The family revision was also exercised with the real local Qwen model in an isolated procedural world: the pair independently agreed to pregnancy after four decision rounds. In that earlier check, fast-forwarding the then-current 270-day biological gestation and two more weeks produced three living people: both parents and their child, with lineage recorded. This was a birth-path check, not a guarantee of family survival or multi-generation growth; the saved spectator world was kept unchanged apart from the requested animal migration and normal running ecology.

The earlier shared-survival revision changed pregnancies to 90 days. The current revision uses the user's chosen 9-day gestation and migrates existing pregnancies proportionally. It adds a 12-minute year, parental naming choices with a recorded fallback, random baby sex, fear/stress/loneliness and family reunion travel. Existing deterministic checks still exercise the complete experiment -> craft -> board -> sail -> land path on two islands, specific death causes, internal family fights and weapon handovers. These are bounded prototype mechanics, not a complete economic, naval or social model.

A separate live Qwen scenario also completed the full sea-exploration loop in ten physical decision rounds: build shelter, discover rafting, gather materials, craft a shared raft, choose an exploration destination, board, sail three steps and land on a second island. The journey continued the model's chosen intention, and did not use fresh random directional choices at every movement step.
