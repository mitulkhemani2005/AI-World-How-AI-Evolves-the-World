# Project Idea: AI World — How AI Evolves the World

## Theme

**A world begins with a few lives. Their choices, relationships, and shared knowledge shape what comes next.**

AI World is a generational simulation about autonomous, human-like agents living in an environment with real constraints. The spectator watches their lives unfold and can optionally alter the conditions. The central question is not “What future must happen?” but “What kinds of worlds can emerge from these agents, these rules, and these events?”

## Premise

Begin with two early hominins, one male and one female, in a natural environment near the beginning of the hominin lineage, approximately 6–7 million years ago. They have no human guide inside the simulation. They must meet their needs, respond to danger, communicate, build relationships, and, if they choose and circumstances allow, reproduce.

Their descendants form a population. Across generations, agents may learn from parents and peers, share ideas, develop customs and beliefs, use tools, build different kinds of property, and organize into groups. Development is not guaranteed to be steady: a population can adapt, divide, lose knowledge, suffer disasters, or disappear.

The starting date is an approximate thematic choice. The simulation is not a scientific reconstruction of every hominin species or a prediction of actual human history.

## The agents

### Shared model, separate minds

All agents use one world-wide LLM model. The current implementation follows the latest project choice: only `qwen2.5:0.5b` is enabled. Each agent still has an independent mind: private observations, memories, experiences, traits, relationships, and life history are sent separately to that shared model for each decision. Sharing an LLM does not mean sharing a conversation or a collective brain. General model switching remains a possible later experiment.

An LLM is one part of an agent's decision process, not the world itself. The agent receives a bounded view of its situation and chooses from available actions. The world simulation decides what those actions cause. After the brain chooses a resource trip or construction task, the body continues walking or gathering until that action completes; urgent biological needs can interrupt it for a new decision. This prevents each walking step from becoming an unrelated new intention.

### Traits and behavior

Agents can differ in temperament, preferences, abilities, health, and learned habits. Helpful, cooperative, aggressive, deceptive, generous, or leadership behavior should emerge through agent traits, experience, circumstances, and choices. Avoid assigning every person a fixed social role at birth.

The social world may include romance and partnerships, affairs, friendship, rivalry, cooperation, disputes, violence, leadership, and criminal or gang-like groups. These behaviors should affect trust, family relations, safety, and group dynamics.

### Communication and ideas

Agents can exchange information and ideas. Communication may begin with simple signals and become richer over time if the simulation rules support that development. Ideas may spread, change as they are retold, or be forgotten. Agents can also learn by observing actions and practicing skills.

## Biology and life history

Agents are embodied living beings, not just text-generating minds. The simulation should represent biological state such as:

- Age and life stage.
- Energy, nutrition, hydration, and rest.
- Health, injury, and recovery.
- Disease exposure, symptoms, immune response, and possible immunity.
- Reproductive health, pregnancy, birth, and childcare where modeled.
- Inherited traits that may affect appearance, abilities, or susceptibility.
- Shelter exposure and the protection provided by maintained shelters.
- Food safety, contamination, spoilage, parasites, and illness from raw or unsafe food and water.
- Animal health, hunger, thirst, disease, domestication, reproduction, and the human-animal relationship.

Birth and death can occur at any age. Death may result from illness, injury, starvation, dehydration, childbirth, violence, environmental exposure, or other modeled causes. A death affects dependents, relationships, group capacity, and the future transmission of knowledge.

Diseases can arise and spread through agents, animals, food, water, or the environment. Raw meat, spoiled foods, polluted water, and animal disease can create distinct risks. Diseases can differ in transmission and severity, and agents may or may not understand what causes them. Care practices and disease knowledge can develop culturally over time. The simulation should record the likely cause and chain of events behind illness and death so the spectator can inspect them.

## Family, inheritance, and teaching

Children inherit biological traits from their parents, with bounded variation if the simulation includes mutation or recombination. Inherited traits are distinct from learned knowledge and from the child's individual memories and personality.

Parents and other community members can teach through demonstration, communication, practice, and care. Children may learn skills, language, customs, survival strategies, beliefs, and social expectations. Teaching is an agent behavior that takes time and can succeed or fail; knowledge should not automatically appear in every child.

## Environment and events

The world provides resources and changing conditions, including food, water, shelter, terrain, weather, seasons, wildlife, and ecological risks. Its fictional globe is generated procedurally rather than copied from Earth: oceans surround several invented landmasses with rivers, lakes, fertile farmland, plains, grassland, mountains, deserts, ice caps, temperate forests, tropical rainforests, and boreal forests.

Agents need to find or make shelter for protection. They can forage fruit and vegetables, hunt wildlife, and learn animal care. Wild animals move, feed, become ill, reproduce, and die. Agents may tame suitable animals into domestic livestock or companions, feed and water them, and collect products such as eggs or milk.

Food sources are biome-dependent. Farm plots require a built farm, suitable soil, water, and time to grow. Crops can fail during drought, fire, flooding, poor soil, or neglect. Raw meat, spoiled food, and contaminated water can cause illness; cooking meat at a campfire reduces some foodborne risk.

Events have two sources:

1. **Natural simulation events:** Weather, disasters, accidents, ecological shifts, disease outbreaks, and other events generated by world rules or randomness.
2. **Spectator interventions:** Events deliberately triggered by a human spectator, such as a flood, wildfire, injury, or outbreak.

The frontend and event log should mark the source of each event. This makes it possible to distinguish agent-driven outcomes, naturally generated conditions, and human interventions.

## Society, beliefs, and culture

Social structures emerge from agents interacting over time. Possible developments include families, friendships, communities, rival groups, leadership, norms, trade, conflict resolution, laws, crime, and collective projects. The simulation should allow different societies to take different paths.

Agents may create explanations for events they do not understand, invent stories, form religions, make gods, establish rituals, and develop ideas of good and evil. Beliefs can influence trust, identity, customs, cooperation, conflict, and how groups explain natural events. They are part of the simulated culture, not claims about real-world religions or morality.

## Tools, buildings, and property

Agents can create and use tools and structures as their skills, resources, and shared knowledge allow. Building may progress from temporary shelters to homes, shared spaces, storage, workshops, farms, or settlements if the simulation supports the necessary discoveries and resources.

Property can be personal, family-held, shared, or group-controlled according to locally developed customs. Agents may build, use, share, trade, claim, defend, abandon, or contest property. Ownership and conflict around property should emerge from social rules and relationships rather than being assumed to work identically in every society.

## Spectator role and interface

The human is primarily an observer. The simulation runs autonomously after its rules and starting conditions are set, while the spectator can optionally intervene.

The separate white-themed frontend should let the spectator:

- Orbit and zoom around a procedural 3D fictional globe with distinct continents and visible oceans, rivers, lakes, farmland, mountains, deserts, ice, and forest biomes. Do not use Earth imagery or tiled map visuals.
- See human figures, animals, crop plots, resources, and buildings attached to the globe surface.
- Advance biology from elapsed real running time, independently of model latency. A biological day takes 60 seconds at 1x; Auto defaults to 2x -> 4x -> 8x, doubling every two running minutes. Fixed speeds up to 16x are available. As requested in the later clock revision, visible sunlight and the local clock follow the spectator's computer time; simulated year/day are displayed separately. Agents can act several times during a biological day.
- Click a human figure directly on the globe to inspect needs, health, memories, relationships, lineage, current biome, and current action. Do not require selecting agents from a name roster.
- Keep dead bodies visible on the ground. Nearby relatives receive the death in their memories and decide whether to mourn, bury, or attend to other needs. Burial leaves a grave marker.
- Give animals hardcoded NPC behavior for movement, feeding, watering, health, illness, reproduction, and death. Animals do not make LLM calls.
- Adjust selected biological stats through that person's inspector, with changes applied by simulation rules.
- Observe communication, teaching, family life, and the spread of ideas.
- See buildings, resources, hazards, groups, and property.
- Review world records from the API for births, deaths, illness, recovery, conflict, discoveries, beliefs, construction, and disasters. Keep the main spectator free of a visible timeline.
- Pause, resume, or advance one day. Only explicit pause stops a running world: interventions, extinction, and recoverable errors must not stop its clock or ecosystem. Persist the run/pause choice through backend restarts.
- Hover world objects for details, animate events at their location, keep animals very small and secondary, without population counters, and protect the camera from entering terrain.
- Let agents choose to restore habitat health, fertility, and resource cleanliness. Food wildlife replenishes according to suitable habitat under a small world-wide budget. Spawning and births use the same limits; excess animals migrate away instead of leaving carcass piles.
- Start founders on adjacent habitable land; proximity enables interaction without forcing reproduction.
- Load only Qwen, prefer full GPU offload, retain RAM/CPU fallback for allocation failures, and display actual residency. Inspect the shared Qwen model readiness. Keep each agent's private history intact; broader model comparisons are a later option.
- Drag events onto a location in the land, with range and severity determined by the world simulation.

## Guiding principles

1. **Agents choose; the world resolves.** The LLM proposes choices, while deterministic simulation systems enforce resource, biology, disease, and environmental rules.
2. **Keep individuals distinct.** Each agent has separate memory and identity, even when agents use the same model.
3. **Make outcomes traceable.** Record observations, decisions, action validation, world consequences, and event sources for debugging and replay.
4. **Let culture be learned.** Children should not automatically know everything their parents know.
5. **Allow varied outcomes.** Do not hard-code inevitable technological progress, religion, morality, or social organization.
6. **Keep the simulation inspectable.** The spectator should be able to understand why an agent acted and why the world changed.
7. **Separate model exploration from fact.** The simulation reveals consequences of its assumptions; it does not prove what real history or future AI will be.

## Suggested development path

### Stage 1: Observable survival loop

Create a small map, two independent agents, basic needs, a constrained action set, simple movement and foraging, health, and a frontend with an event log.

### Stage 2: Biology and family

Add aging, injury, disease, death, relationships, reproduction, children, inheritance, and basic teaching. Make every critical outcome inspectable.

### Stage 3: Communication and groups

Add richer communication, memory retrieval, idea sharing, social bonds, cooperation, disputes, and group formation.

### Stage 4: Culture and material development

Add tools, skills, construction, property customs, beliefs, rituals, moral systems, trade, and institutions. Let these depend on resources and knowledge rather than a fixed unlock timeline.

### Stage 5: Spectator controls and long runs

Add a world-wide model selector, natural event generation, drag-and-drop spectator events, replayable histories, time acceleration, and ways to inspect long-term changes.

The current delivery and the remaining work for these stages are tracked in [implementation-status.md](implementation-status.md). The roadmap is not a claim that all proposed social institutions, tools, or evolutionary mechanisms already exist.

## Family and food ecology revision

Family planning must remain visible among feasible choices after immediate survival needs are met. Agents can approach partners and exchange persistent, expiring proposals instead of requiring identical choices in one decision round. Both adults still independently agree. Physical survival responses can meet urgent needs while the shared model is busy; they never fabricate consent or resources. Pregnancy takes 270 biological days and postpartum recovery takes 120 days. Infants travel with a living caregiver and learn later.

Animals are small NPC food sources, secondary to the people. Healthy habitat determines the wildlife budget, capped at 24 wild animals; kept animals use a separate sustainable settlement allowance capped at 24. Natural spawning, reproduction, and migration enforce these budgets.
