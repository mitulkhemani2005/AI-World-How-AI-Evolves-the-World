# Working simulation and next stages

## Current behavior

The canonical design is [idea.md](idea.md). Later requirements pin Qwen, use a white interface, and display local computer time while biology advances every real minute. Existing SQLite worlds migrate without being reset. New worlds place the founders in a viable natural habitat; different seeds produce different terrain.

| System | Current implementation |
| --- | --- |
| World display | Procedural globe, aligned biome texture and entity coordinates, human figures, animals, resources, buildings, crops, orbit/zoom, a people view that follows movement, direct selection, and visible rendering errors. A 2D compatibility view is available if WebGL initialization fails. |
| Private minds | Separate observations, memories, relationships, traits and skills. One shared Qwen model selects a concrete opportunity; the engine executes and validates it. Meaningful task continuations avoid random movement between every LLM turn. |
| Survival | Daily nutrition, hydration, fatigue, illness and exposure. Food and water used in care consume real resources. Rest and care cannot heal unlimited health in one day. |
| Shelter and material work | Local resource navigation, gathering batches for a chosen project, building costs, shelter protection and property owner records. |
| Animals and farming | NPC animal rules, taming, care, food collection limited by day, crops that require planting and growth before harvest, contamination and raw-food disease risk. Building a farm does not create an instant food stock. |
| Family | Independent mutual choices for bonding/reproduction, pregnancy, birth, inherited traits, dependent children and teaching of actually learned knowledge. Children do not inherit parents' skill lists. |
| Social outcomes | Communication memories, relationship changes, conflict, community/family/gang groups and deity/myth/virtue/evil/taboo records. These are basic mechanisms, not complete sociological systems. |
| Death and hazards | Disease, injuries, starvation/dehydration consequences, age risks, bodies, mourning, burial, grave markers, natural hazards and bounded spectator events with separate sources. |
| Time and persistence | A separate elapsed-time loop advances biology during slow model calls. Action rounds run on their own cadence. Pause invalidates late proposals. SQLite stores the world, pending work and random state. |
| Inspection | Action reason/result, current project, source (`llm`, `continuation`, `fallback`), original intention source, event provenance, biological stats, family and knowledge. |

The engine makes feasible opportunities available and resolves consequences. It does not guarantee births, technological progress, cooperation, survival, religion or any particular historical path. A small model can still make poor choices. Failed inference is explicitly recorded as fallback behavior.

## Verification

`frontend/tests/world-runtime.test.js` executes the application with real Three.js math/geometry and a stub GPU/DOM. This is a runtime regression check, not a screenshot or physical-GPU test. It reproduces the populated scene transition that previously called an unsupported vector method and froze the initial ocean sphere.

`backend/tests/test_world.py` checks temporary worlds for physical accounting, bounded actions, shared-model requests, model autonomy, task execution, slow inference timing, pause semantics, farm growth, animal products, learned skills, mutual consent, birth, disease and saved-state recovery. Tests do not touch the spectator's saved world.

An isolated live Ollama run also exercised Qwen choices through shelter/campfire construction, teaching, chicken domestication, egg collection and animal care without JSON-validation fallbacks. This demonstrates an observable working loop; it is not evidence of guaranteed long-term civilization growth.

## Further development

1. **Long-run reliability:** seeded multi-generation scenario runs, starvation/extinction diagnostics, queue budgets for larger populations, measured response latency, save slots and event replay. Keep 60-second days as the default.
2. **Ecology and biology depth:** explicit nutrition stores, inherited disease susceptibility, pregnancy/nursing costs, contact-based disease transmission, seed stocks, soil fertility, food chains and seasonal migration. Current biology is illustrative.
3. **Knowledge and technology:** replace the current simplified building-count knowledge levels with individual discoveries, tool recipes, practice, experimentation, prerequisites, forgotten knowledge and communal construction projects.
4. **Property and institutions:** extend ownership records into inventories, transfer, trade, disputes, norms, leadership succession, crime, law and collective decisions. Current group and belief records do not implement economies or governments.
5. **Culture and communication:** persistent narratives, rituals, teaching success/failure, language development, beliefs that affect future decisions and conflicts, and inspectable chains of idea transmission.
6. **Rendering and scale:** higher-detail rigged people/animals, terrain detail around settlements, streamed snapshots, replay and larger habitats after simulation reliability is measured.

These are explicit next stages. Millions of years of biological evolution and a complete modern civilization are not implemented or scientifically validated by the present prototype.
