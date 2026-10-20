/* The browser is a spectator: all authoritative choices and consequences come from FastAPI. */
const $ = (selector) => document.querySelector(selector);
const ui = {
  clock: $("#clock-label"), map: $("#world-map"), agents: $("#agent-cards"), inspector: $("#agent-inspector"),
  timeline: $("#event-list"), culture: $("#culture-content"), run: $("#run-button"), step: $("#step-button"),
  speed: $("#speed-select"), modelAgent: $("#model-agent"), modelInput: $("#model-input"), modelOptions: $("#model-options"),
  modelStatus: $("#model-status"), eventTarget: $("#event-target"), eventStatus: $("#event-status"), toast: $("#toast"),
};
let currentWorld = null;
let selectedAgentId = "agent-1";
let selectedTile = null;
let toastTimer = null;
let modelDraftDirty = false;
let eventTargetDraft = "";

// Escape every value that came from a model or the saved world before putting it in markup.
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
  return payload;
}

function notify(message, isError = false) {
  ui.toast.textContent = message;
  ui.toast.style.background = isError ? "#e2a096" : "#d3e6b3";
  ui.toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => ui.toast.classList.remove("visible"), 2600);
}

function livingAgents() {
  return currentWorld?.agents.filter((agent) => agent.alive) || [];
}

function renderWorld(world) {
  currentWorld = world;
  const day = world.tick % 365 || 365;
  const year = Math.floor(world.tick / 365) + 1;
  ui.clock.textContent = `YEAR ${year} · DAY ${day} · WORLD ${world.id.slice(0, 8).toUpperCase()}${world.processing ? " · BRAINS DECIDING" : ""}`;
  $("#season-label").textContent = world.season || "spring";
  $("#weather-label").textContent = world.weather || "clear";
  $("#tech-label").textContent = `Knowledge age ${world.tech_level}`;
  $("#population-label").textContent = `${livingAgents().length} living · ${world.agents.length} total`;
  $("#event-count").textContent = `${world.events.length} event${world.events.length === 1 ? "" : "s"}`;
  ui.run.textContent = world.running ? "Ⅱ Pause world" : "▶ Run world";
  renderMap(world);
  renderAgents(world);
  renderInspector(world);
  renderTimeline(world);
  renderCulture(world);
  renderSelectors(world);
}

function renderMap(world) {
  const cells = [];
  for (let y = 0; y < world.height; y += 1) {
    for (let x = 0; x < world.width; x += 1) {
      const resources = world.resources.filter((node) => node.x === x && node.y === y && node.quantity > 0);
      const structures = world.structures.filter((structure) => structure.x === x && structure.y === y);
      const agents = world.agents.filter((agent) => agent.x === x && agent.y === y);
      const water = resources.some((node) => node.kind === "water");
      const selected = selectedTile && selectedTile.x === x && selectedTile.y === y;
      const markers = resources.map((node) => {
        const icon = { food: "✿", water: "≈", wood: "♣", stone: "◆" }[node.kind] || "·";
        return `<span class="resource-marker" title="${escapeHtml(node.kind)} · ${node.quantity}">${icon}</span>`;
      }).join("");
      const buildings = structures.map((structure) => `<span class="structure-marker" title="${escapeHtml(structure.kind)} · owner ${escapeHtml(structure.owner_agent_id || "shared")}">⌂</span>`).join("");
      const people = agents.map((agent) => {
        const sexClass = agent.age_days < 16 * 365 ? "child" : agent.sex;
        const deadClass = agent.alive ? "" : "dead";
        return `<span class="agent-marker ${sexClass} ${deadClass}" data-agent="${escapeHtml(agent.id)}" role="button" tabindex="0" title="${escapeHtml(agent.name)} · age ${Math.floor(agent.age_days / 365)}${agent.alive ? "" : " · deceased"}">${agent.sex === "female" ? "♀" : "♂"}</span>`;
      }).join("");
      cells.push(`<div class="map-cell ${water ? "water-cell" : ""} ${selected ? "selected" : ""}" role="button" tabindex="0" data-cell-x="${x}" data-cell-y="${y}" aria-label="Tile ${x}, ${y}">${markers}${buildings}${people}</div>`);
    }
  }
  ui.map.style.setProperty("--cols", world.width);
  ui.map.innerHTML = cells.join("");
  $("#selected-cell").textContent = selectedTile ? `Selected tile ${selectedTile.x}, ${selectedTile.y}` : "No tile selected";
}

function needBar(label, value) {
  const urgency = value >= 75 ? "danger" : value >= 55 ? "warn" : "";
  return `<div class="health-row"><span>${label}</span><div class="bar ${urgency}"><i style="width:${Math.max(0, Math.min(100, value))}%"></i></div><b>${Math.round(value)}</b></div>`;
}

function renderAgents(world) {
  ui.agents.innerHTML = world.agents.map((agent) => {
    const selected = agent.id === selectedAgentId ? "selected" : "";
    const avatarClass = agent.age_days < 16 * 365 ? "child" : agent.sex;
    const avatar = agent.sex === "female" ? "♀" : "♂";
    const action = agent.last_action ? agent.last_action.action.replaceAll("_", " ") : "new to the world";
    return `<article class="agent-card ${selected}" data-select-agent="${escapeHtml(agent.id)}">
      <div class="agent-card-head"><div class="avatar ${avatarClass}">${avatar}</div><div><h3>${escapeHtml(agent.name)}${agent.alive ? "" : " · deceased"}</h3><small>${Math.floor(agent.age_days / 365)} years · ${escapeHtml(agent.model)}</small></div></div>
      <div class="mini-stats"><div class="mini-stat"><span>Health</span><strong>${Math.round(agent.health)}%</strong></div><div class="mini-stat"><span>Hunger</span><strong>${Math.round(agent.hunger)}%</strong></div><div class="mini-stat"><span>Thirst</span><strong>${Math.round(agent.thirst)}%</strong></div></div>
      <div class="agent-action-line">Last choice: ${escapeHtml(action)}${agent.disease ? ` · Ill with ${escapeHtml(agent.disease)}` : ""}</div>
    </article>`;
  }).join("");
}

function renderInspector(world) {
  const agent = world.agents.find((person) => person.id === selectedAgentId) || world.agents[0];
  if (!agent) {
    ui.inspector.innerHTML = '<div class="empty-state">No people are in this world.</div>';
    return;
  }
  const ageLabel = agent.age_days < 365 ? `${agent.age_days} days` : `${Math.floor(agent.age_days / 365)} years`;
  const partner = world.agents.find((person) => person.id === agent.bonded_partner_id);
  const parents = agent.parent_ids.map((id) => world.agents.find((person) => person.id === id)?.name || "Unknown").join(", ") || "First generation";
  const children = agent.children_ids.map((id) => world.agents.find((person) => person.id === id)?.name || "Unknown").join(", ") || "None";
  const relationships = Object.entries(agent.relationship_scores || {}).map(([id, score]) => {
    const person = world.agents.find((candidate) => candidate.id === id);
    return person ? `${person.name} ${Math.round(score)}` : null;
  }).filter(Boolean).join(" · ") || "None recorded";
  const condition = agent.alive ? (agent.disease ? `Ill · ${agent.disease}` : "Alive") : "Deceased";
  const traits = Object.entries(agent.traits || {}).map(([name, value]) => `${name} ${Math.round(value * 100)}`).join(" · ") || "No inherited traits recorded";
  const memories = [...(agent.memories || [])].slice(-5).reverse();
  ui.inspector.innerHTML = `
    <div class="inspector-person"><div class="avatar ${agent.age_days < 16 * 365 ? "child" : agent.sex}">${agent.sex === "female" ? "♀" : "♂"}</div><div><h3>${escapeHtml(agent.name)}</h3><p>${escapeHtml(condition)} · ${escapeHtml(ageLabel)}</p></div></div>
    ${needBar("Health", agent.health)}${needBar("Hunger", agent.hunger)}${needBar("Thirst", agent.thirst)}${needBar("Fatigue", 100 - agent.energy)}
    <div class="detail-line"><span>Brain model</span><span>${escapeHtml(agent.model)}</span></div>
    <div class="detail-line"><span>Parents</span><span>${escapeHtml(parents)}</span></div>
    <div class="detail-line"><span>Children</span><span>${escapeHtml(children)}</span></div>
    <div class="detail-line"><span>Bond</span><span>${escapeHtml(partner?.name || "None")}</span></div>
    <div class="detail-line"><span>Relationships</span><span>${escapeHtml(relationships)}</span></div>
    <div class="detail-line"><span>Pregnancy</span><span>${agent.pregnancy_days_remaining == null ? "No" : `${agent.pregnancy_days_remaining} days remaining`}</span></div>
    <div class="detail-line"><span>Knowledge</span><span>${(agent.knowledge || []).length} learned</span></div>
    <div class="detail-line"><span>Traits</span><span>${escapeHtml(traits)}</span></div>
    <div class="detail-line"><span>Memories</span><span>Individual life history</span></div>
    <ul class="memory-list">${memories.length ? memories.map((memory) => `<li>${escapeHtml(memory)}</li>`).join("") : "<li>No memories yet.</li>"}</ul>`;
}

function renderTimeline(world) {
  const events = [...world.events].slice(-35).reverse();
  ui.timeline.innerHTML = events.length ? events.map((event) => {
    const tag = event.source;
    const year = Math.floor(event.tick / 365) + 1;
    return `<div class="event-item"><div class="event-tick">Y${year} · ${event.tick}</div><div><div class="event-message">${escapeHtml(event.message)}</div><div class="event-meta"><span class="event-tag ${escapeHtml(tag)}">${escapeHtml(tag.replaceAll("_", " "))}</span><span class="event-tag">${escapeHtml(event.kind.replaceAll("_", " "))}</span></div></div></div>`;
  }).join("") : '<div class="empty-state">The story begins when the world advances.</div>';
}

function renderCulture(world) {
  const structures = world.structures || [];
  const groups = world.groups || [];
  const beliefs = world.beliefs || [];
  const structureCounts = Object.entries(structures.reduce((counts, item) => ({ ...counts, [item.kind]: (counts[item.kind] || 0) + 1 }), {}));
  const chips = (items, className = "") => items.length ? items.map((item) => `<span class="chip ${className}">${escapeHtml(item)}</span>`).join("") : '<span class="empty-state">Nothing yet</span>';
  ui.culture.innerHTML = `<div class="culture-block"><h3>Property · ${structures.length} built</h3><div class="chip-list">${chips(structureCounts.map(([kind, count]) => `${kind.replaceAll("_", " ")} ×${count}`))}</div></div>
    <div class="culture-block"><h3>Groups · ${groups.length}</h3><div class="chip-list">${chips(groups.map((group) => `${group.name} · ${group.kind} · ${group.member_ids.length}`))}</div></div>
    <div class="culture-block"><h3>Beliefs · ${beliefs.length}</h3><div class="chip-list">${beliefs.length ? beliefs.map((belief) => `<span class="chip belief" title="${escapeHtml(belief.description)}">${escapeHtml(belief.name)} · ${escapeHtml(belief.kind)}</span>`).join("") : '<span class="empty-state">No beliefs have emerged.</span>'}</div></div>`;
}

function renderSelectors(world) {
  const selected = world.agents.some((agent) => agent.id === selectedAgentId) ? selectedAgentId : world.agents[0]?.id;
  selectedAgentId = selected || "";
  const agentOptions = world.agents.map((agent) => `<option value="${escapeHtml(agent.id)}">${escapeHtml(agent.name)}${agent.alive ? "" : " · deceased"}</option>`).join("");
  ui.modelAgent.innerHTML = agentOptions;
  ui.eventTarget.innerHTML = '<option value="">Near selected tile / world center</option>' + world.agents.filter((agent) => agent.alive).map((agent) => `<option value="${escapeHtml(agent.id)}">${escapeHtml(agent.name)}</option>`).join("");
  ui.modelAgent.value = selectedAgentId;
  ui.eventTarget.value = eventTargetDraft;
  // Do not overwrite a model name while the spectator is typing it.
  if (selectedAgentId && !modelDraftDirty && document.activeElement !== ui.modelInput) {
    ui.modelInput.value = world.agents.find((agent) => agent.id === selectedAgentId)?.model || "gemma4:e2b";
  }
}

async function refreshHealth() {
  try {
    const health = await api("/api/health");
    const models = await api("/api/models");
    ui.modelOptions.innerHTML = '<option value="">Installed models…</option>' + models.models.map((model) => `<option value="${escapeHtml(model)}">${escapeHtml(model)}</option>`).join("");
    ui.modelStatus.textContent = !health.ollama_available ? "Ollama is not reachable. Survival fallback is active." : health.model_ready ? `${health.default_model} is ready on this machine.` : `${health.default_model} is not installed yet. The fallback remains active.`;
    ui.modelStatus.classList.toggle("error", !health.model_ready);
  } catch (error) {
    ui.modelStatus.textContent = error.message;
    ui.modelStatus.classList.add("error");
  }
}

async function refreshWorld() {
  try {
    renderWorld(await api("/api/world"));
  } catch (error) {
    ui.clock.textContent = "Backend unavailable";
    notify(error.message, true);
  }
}

ui.map.addEventListener("click", (event) => {
  const agentButton = event.target.closest("[data-agent]");
  if (agentButton) {
    selectedAgentId = agentButton.dataset.agent;
    if (currentWorld) renderWorld(currentWorld);
    return;
  }
  const cell = event.target.closest("[data-cell-x]");
  if (cell) {
    selectedTile = { x: Number(cell.dataset.cellX), y: Number(cell.dataset.cellY) };
    if (currentWorld) renderWorld(currentWorld);
  }
});

ui.map.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    const interactive = event.target.closest("[data-agent], [data-cell-x]");
    if (interactive) {
      event.preventDefault();
      interactive.click();
    }
  }
});

ui.agents.addEventListener("click", (event) => {
  const card = event.target.closest("[data-select-agent]");
  if (card) {
    selectedAgentId = card.dataset.selectAgent;
    renderWorld(currentWorld);
  }
});

ui.modelAgent.addEventListener("change", () => {
  selectedAgentId = ui.modelAgent.value;
  modelDraftDirty = false;
  const agent = currentWorld?.agents.find((person) => person.id === selectedAgentId);
  if (agent) ui.modelInput.value = agent.model;
  if (currentWorld) {
    renderAgents(currentWorld);
    renderInspector(currentWorld);
  }
});

ui.modelOptions.addEventListener("change", () => {
  if (ui.modelOptions.value) {
    ui.modelInput.value = ui.modelOptions.value;
    modelDraftDirty = true;
  }
});

ui.modelInput.addEventListener("input", () => { modelDraftDirty = true; });
ui.eventTarget.addEventListener("change", () => { eventTargetDraft = ui.eventTarget.value; });

ui.run.addEventListener("click", async () => {
  try {
    if (currentWorld?.running) await api("/api/world/pause", { method: "POST" });
    else await api(`/api/world/run?interval_seconds=${encodeURIComponent(ui.speed.value)}`, { method: "POST" });
    await refreshWorld();
  } catch (error) { notify(error.message, true); }
});

ui.step.addEventListener("click", async () => {
  ui.step.disabled = true;
  try { renderWorld(await api("/api/world/tick", { method: "POST" })); }
  catch (error) { notify(error.message, true); }
  finally { ui.step.disabled = false; }
});

$("#change-model").addEventListener("click", async () => {
  const agentId = ui.modelAgent.value;
  const model = ui.modelInput.value.trim();
  if (!agentId || !model) return notify("Choose a person and enter a model name.", true);
  try {
    await api(`/api/agents/${encodeURIComponent(agentId)}/model`, { method: "PATCH", body: JSON.stringify({ model }) });
    modelDraftDirty = false;
    notify(`Model changed to ${model}.`);
    await refreshWorld();
  } catch (error) { notify(error.message, true); }
});

$("#refresh-models").addEventListener("click", refreshHealth);

$("#trigger-event").addEventListener("click", async () => {
  const payload = { kind: $("#event-kind").value };
  if (ui.eventTarget.value) payload.target_agent_id = ui.eventTarget.value;
  else if (selectedTile) Object.assign(payload, selectedTile);
  ui.eventStatus.textContent = "Applying event…";
  ui.eventStatus.classList.remove("error");
  try {
    renderWorld(await api("/api/events", { method: "POST", body: JSON.stringify(payload) }));
    eventTargetDraft = "";
    ui.eventTarget.value = "";
    ui.eventStatus.textContent = "Recorded in the timeline as a spectator intervention.";
  } catch (error) {
    ui.eventStatus.textContent = error.message;
    ui.eventStatus.classList.add("error");
  }
});

$("#reset-world").addEventListener("click", async () => {
  if (!window.confirm("Start a new world? This replaces the currently saved world.")) return;
  try {
    selectedTile = null;
    eventTargetDraft = "";
    selectedAgentId = "agent-1";
    renderWorld(await api("/api/world/reset?seed=" + Math.floor(Math.random() * 1_000_000), { method: "POST" }));
    notify("A new world has begun.");
  } catch (error) { notify(error.message, true); }
});

refreshWorld();
refreshHealth();
// Polling keeps this dependency-free frontend live; the backend remains authoritative.
setInterval(refreshWorld, 1500);
setInterval(refreshHealth, 15000);
