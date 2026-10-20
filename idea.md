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

All agents use one world-wide LLM model selected by the spectator. Each agent still has an independent mind: private observations, memories, experiences, traits, relationships, and life history are sent separately to that shared model for each decision. Sharing an LLM does not mean sharing a conversation or a collective brain. A model change applies to every current agent and every newborn while leaving each individual's identity and history intact.

An LLM is one part of an agent's decision process, not the world itself. The agent receives a bounded view of its situation and chooses from available actions. The world simulation decides what those actions cause.

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

Birth and death can occur at any age. Death may result from illness, injury, starvation, dehydration, childbirth, violence, environmental exposure, or other modeled causes. A death affects dependents, relationships, group capacity, and the future transmission of knowledge.

Diseases can arise and spread through agents or the environment. They can differ in transmission and severity, and agents may or may not understand what causes them. Care practices and disease knowledge can develop culturally over time. The simulation should record the likely cause and chain of events behind illness and death so the spectator can inspect them.

## Family, inheritance, and teaching

Children inherit biological traits from their parents, with bounded variation if the simulation includes mutation or recombination. Inherited traits are distinct from learned knowledge and from the child's individual memories and personality.

Parents and other community members can teach through demonstration, communication, practice, and care. Children may learn skills, language, customs, survival strategies, beliefs, and social expectations. Teaching is an agent behavior that takes time and can succeed or fail; knowledge should not automatically appear in every child.

## Environment and events

The world provides resources and changing conditions, including food, water, shelter, terrain, weather, seasons, and ecological risks. Agents may forage, make shelters, cooperate to obtain resources, or adapt their behavior to the environment.

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

The dark-themed frontend should let the spectator:

- Orbit a continuous 3D landscape, zoom in and out, and follow human figures as they walk.
- Inspect an agent's needs, health, memories, relationships, lineage, and current action.
- Adjust selected biological stats through that person's inspector, with changes applied by simulation rules.
- Observe communication, teaching, family life, and the spread of ideas.
- See buildings, resources, hazards, groups, and property.
- Review a timeline of births, deaths, illness, recovery, conflict, discoveries, beliefs, construction, and disasters.
- Pause and change simulation speed.
- Change the shared LLM model used by every agent and inspect the resulting changes in their behavior.
- Drag events onto a location or person, with range and severity determined by the world simulation.

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
