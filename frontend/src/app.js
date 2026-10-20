import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import "./styles.css";

// This client only observes and requests changes; FastAPI owns every world rule.
const $ = (selector) => document.querySelector(selector);
const host = $("#world-scene");
const apiBase = import.meta.env.VITE_API_BASE_URL || "";
const ui = {
  clock: $("#clock-label"), model: $("#model-select"), run: $("#run-button"), step: $("#step-button"),
  inspector: $("#agent-inspector"), toast: $("#toast"),
};
let world = null;
let selectedAgentId = null;
let toastTimeout = null;
let isStepping = false;
let draggedEvent = null;
let currentWorldId = null;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
}

async function api(path, options = {}) {
  const response = await fetch(`${apiBase}${path}`, { headers: { "Content-Type": "application/json" }, ...options });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
  return body;
}

function notify(message, error = false) {
  ui.toast.textContent = message;
  ui.toast.classList.toggle("error", error);
  ui.toast.classList.add("visible");
  clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => ui.toast.classList.remove("visible"), 3000);
}

// Set up a NASA-textured planet, an atmosphere rim, stars, and clickable people.
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.8));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.14;
host.appendChild(renderer.domElement);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 90);
camera.position.set(0, 0.1, 13.2);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.06;
controls.enablePan = false;
controls.minDistance = 6.8;
controls.maxDistance = 18;
controls.rotateSpeed = 0.48;

scene.add(new THREE.HemisphereLight(0xc5d9f3, 0x151a1e, 1.25));
const sunlight = new THREE.DirectionalLight(0xffe6c3, 2.8);
sunlight.position.set(-7, 5, 10);
scene.add(sunlight);
const fill = new THREE.DirectionalLight(0x527eac, 0.65);
fill.position.set(8, -3, -8);
scene.add(fill);

const planet = new THREE.Group();
planet.rotation.y = -0.47;
scene.add(planet);
const radius = 5;
const globeGeometry = new THREE.SphereGeometry(radius, 112, 80);
const globeMaterial = new THREE.MeshStandardMaterial({ color: 0x8f9d9d, roughness: 0.86, metalness: 0.02 });
const globe = new THREE.Mesh(globeGeometry, globeMaterial);
globe.userData.isGlobe = true;
planet.add(globe);

// An offline procedural texture is shown immediately while the bundled NASA map loads.
function fallbackEarthTexture() {
  const canvas = document.createElement("canvas");
  canvas.width = 1024; canvas.height = 512;
  const context = canvas.getContext("2d");
  const ocean = context.createLinearGradient(0, 0, 0, 512);
  ocean.addColorStop(0, "#173c62"); ocean.addColorStop(0.48, "#175978"); ocean.addColorStop(1, "#102849");
  context.fillStyle = ocean; context.fillRect(0, 0, 1024, 512);
  // Approximate continental silhouettes keep the globe useful if the local texture is absent.
  const continents = [
    [[100,80],[170,55],[245,72],[285,110],[258,152],[214,150],[197,194],[163,197],[149,248],[120,220],[115,162],[78,130]],
    [[280,208],[336,195],[366,224],[377,276],[356,322],[342,374],[313,423],[294,370],[280,321],[262,270]],
    [[440,84],[501,62],[557,78],[603,98],[643,91],[686,110],[731,104],[777,138],[824,151],[878,171],[881,211],[849,224],[814,199],[786,228],[741,213],[698,237],[667,215],[632,243],[598,220],[575,176],[540,168],[510,126],[468,138]],
    [[555,239],[596,221],[634,235],[648,275],[632,311],[615,350],[588,392],[563,374],[548,333],[533,290]],
    [[840,325],[880,311],[905,328],[898,353],[869,362],[846,347]],
  ];
  context.fillStyle = "#71815b"; context.strokeStyle = "#9da77a"; context.lineWidth = 3;
  continents.forEach((points) => { context.beginPath(); points.forEach(([x,y], index) => index ? context.lineTo(x,y) : context.moveTo(x,y)); context.closePath(); context.fill(); context.stroke(); });
  const texture = new THREE.CanvasTexture(canvas); texture.colorSpace = THREE.SRGBColorSpace; return texture;
}
globe.material.map = fallbackEarthTexture();
globe.material.needsUpdate = true;
new THREE.TextureLoader().load("/earth/bluemarble-2048.png", (texture) => {
  texture.colorSpace = THREE.SRGBColorSpace;
  globe.material.map = texture;
  globe.material.color.set(0xffffff);
  globe.material.needsUpdate = true;
}, undefined, () => notify("Using the local Earth map fallback; check frontend/public/earth/ for the NASA texture."));

// Fresnel glow produces a slim blue atmospheric edge around the planet.
const atmosphere = new THREE.Mesh(
  new THREE.SphereGeometry(radius * 1.025, 72, 56),
  new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    vertexShader: "varying vec3 vNormal; varying vec3 vView; void main(){ vec4 mv=modelViewMatrix*vec4(position,1.0); vNormal=normalize(normalMatrix*normal); vView=normalize(-mv.xyz); gl_Position=projectionMatrix*mv; }",
    fragmentShader: "varying vec3 vNormal; varying vec3 vView; void main(){ float rim=pow(1.0-max(dot(normalize(vNormal),normalize(vView)),0.0),3.2); gl_FragColor=vec4(0.22,0.50,0.85,rim*0.52); }",
  }),
);
planet.add(atmosphere);

// Sparse stars make the black void feel deep without competing with the Earth.
const starPositions = [];
let starSeed = 814;
const seededRandom = () => { starSeed = (starSeed * 16807) % 2147483647; return (starSeed - 1) / 2147483646; };
for (let index = 0; index < 750; index += 1) {
  starPositions.push((seededRandom() - 0.5) * 70, (seededRandom() - 0.5) * 42, -7 - seededRandom() * 35);
}
const starsGeometry = new THREE.BufferGeometry();
starsGeometry.setAttribute("position", new THREE.Float32BufferAttribute(starPositions, 3));
const stars = new THREE.Points(starsGeometry, new THREE.PointsMaterial({ color: 0xc5d0dc, size: 0.045, transparent: true, opacity: 0.56 }));
scene.add(stars);

const peopleGroup = new THREE.Group(); planet.add(peopleGroup);
const markerGroup = new THREE.Group(); planet.add(markerGroup);
const people = new Map();
const markers = new Map();
const labelElements = new Map();
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
let pointerDown = null;

// Map the small early-hominin habitat onto a region around East Africa.
function coordinateFor(x, y) {
  const longitude = THREE.MathUtils.degToRad(28 + (x / 12) * 27);
  const latitude = THREE.MathUtils.degToRad(15 - (y / 8) * 27);
  const normal = new THREE.Vector3(Math.cos(latitude) * Math.sin(longitude), Math.sin(latitude), Math.cos(latitude) * Math.cos(longitude));
  return { normal, point: normal.clone().multiplyScalar(radius + 0.022), longitude, latitude };
}

function makePerson(agent) {
  // Meshes are attached to a pivot so the body's local up axis follows the curved surface.
  const root = new THREE.Group();
  root.userData.agentId = agent.id;
  const skin = new THREE.MeshStandardMaterial({ color: agent.sex === "female" ? 0xc49673 : 0xb78763, roughness: 0.92 });
  const garment = new THREE.MeshStandardMaterial({ color: agent.sex === "female" ? 0x9d7060 : 0x6e805f, roughness: 1, flatShading: true });
  const hair = new THREE.MeshStandardMaterial({ color: 0x332c27, roughness: 1 });
  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.074, 0.13, 4, 7), garment);
  body.position.y = 0.16; root.add(body);
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.057, 12, 10), skin);
  head.position.y = 0.30; root.add(head);
  const hairCap = new THREE.Mesh(new THREE.SphereGeometry(0.059, 12, 8, 0, Math.PI * 2, 0, Math.PI * 0.58), hair);
  hairCap.position.y = 0.32; root.add(hairCap);
  const limbs = [];
  for (const side of [-1, 1]) {
    const arm = new THREE.Mesh(new THREE.CapsuleGeometry(0.018, 0.105, 3, 6), skin);
    arm.position.set(side * 0.088, 0.175, 0); arm.userData.phase = side < 0 ? 0 : Math.PI;
    root.add(arm); limbs.push(arm);
    const leg = new THREE.Mesh(new THREE.CapsuleGeometry(0.023, 0.11, 3, 6), hair);
    leg.position.set(side * 0.035, 0.065, 0); leg.userData.phase = side < 0 ? Math.PI : 0;
    root.add(leg); limbs.push(leg);
  }
  const halo = new THREE.Mesh(new THREE.TorusGeometry(0.125, 0.006, 6, 36), new THREE.MeshBasicMaterial({ color: 0xc3e796, transparent: true, opacity: 0.9 }));
  halo.rotation.x = Math.PI / 2; halo.position.y = 0.012; halo.visible = agent.id === selectedAgentId; root.add(halo);
  root.userData.limbs = limbs; root.userData.halo = halo;
  root.traverse((child) => { if (child.isMesh) { child.userData.agentId = agent.id; child.castShadow = true; } });
  const label = document.createElement("div"); label.className = "scene-label"; label.dataset.agentId = agent.id;
  host.appendChild(label); labelElements.set(agent.id, label);
  peopleGroup.add(root); people.set(agent.id, root);
  return root;
}

function makeMarker(key, node) {
  const group = new THREE.Group();
  const location = coordinateFor(node.x, node.y);
  group.position.copy(location.point);
  group.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), location.normal);
  const colors = { food: 0x89b96e, water: 0x69b9d1, wood: 0x9a754c, stone: 0xa6a8a3 };
  const color = colors[node.kind] || 0xb3d789;
  const pin = new THREE.Mesh(new THREE.SphereGeometry(0.035 + Math.min(node.quantity, 30) * 0.0008, 10, 8), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.9 }));
  pin.position.y = 0.035; group.add(pin);
  const glow = new THREE.Mesh(new THREE.RingGeometry(0.055, 0.075, 22), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.58, side: THREE.DoubleSide }));
  glow.rotation.x = -Math.PI / 2; glow.position.y = 0.012; group.add(glow);
  group.userData.markerKind = node.kind; group.userData.remaining = node.quantity;
  markerGroup.add(group); markers.set(key, group);
}

function syncMarkers(nextWorld) {
  const wanted = new Set();
  for (const node of nextWorld.resources) {
    if (node.quantity <= 0) continue;
    const key = `resource-${node.kind}-${node.x}-${node.y}`;
    wanted.add(key);
    if (!markers.has(key)) makeMarker(key, node);
    else markers.get(key).userData.remaining = node.quantity;
  }
  for (const building of nextWorld.structures) {
    const key = `building-${building.id}`; wanted.add(key);
    if (markers.has(key)) continue;
    const group = new THREE.Group();
    const location = coordinateFor(building.x, building.y);
    group.position.copy(location.point); group.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), location.normal);
    const color = building.kind === "shrine" ? 0xd7bc82 : building.kind === "farm" ? 0x8eaa62 : 0xc8a77b;
    const house = new THREE.Mesh(new THREE.ConeGeometry(0.075, 0.14, 4), new THREE.MeshBasicMaterial({ color }));
    house.position.y = 0.085; house.rotation.y = Math.PI / 4; group.add(house);
    group.userData.markerKind = "building"; markerGroup.add(group); markers.set(key, group);
  }
  for (const [key, marker] of markers) if (!wanted.has(key)) { marker.removeFromParent(); markers.delete(key); }
}

function updatePerson(agent, now) {
  let figure = people.get(agent.id);
  if (!figure) figure = makePerson(agent);
  const location = coordinateFor(agent.x, agent.y);
  const destination = location.point;
  figure.userData.destination = destination;
  figure.userData.destinationNormal = location.normal;
  const moving = agent.alive && agent.last_action?.action === "move" && figure.position.distanceTo(destination) > 0.035;
  figure.userData.limbs.forEach((limb) => { limb.rotation.x = moving ? Math.sin(now * 0.008 + limb.userData.phase) * 0.52 : THREE.MathUtils.damp(limb.rotation.x, 0, 4, 1 / 60); });
  figure.userData.halo.visible = agent.id === selectedAgentId && agent.alive;
  figure.userData.dead = !agent.alive;
  figure.traverse((part) => { if (part.isMesh) { part.material.transparent = !agent.alive; part.material.opacity = agent.alive ? 1 : 0.32; } });
  const label = labelElements.get(agent.id);
  label.textContent = agent.alive ? `${agent.name} · ${Math.floor(agent.age_days / 365)}` : `${agent.name} · deceased`;
  label.classList.toggle("selected", agent.id === selectedAgentId); label.classList.toggle("dead", !agent.alive);
}

function syncWorldObjects(nextWorld, now = performance.now()) {
  if (currentWorldId !== nextWorld.id) {
    currentWorldId = nextWorld.id; selectedAgentId = null;
    for (const label of labelElements.values()) label.remove();
    labelElements.clear(); people.clear(); markers.clear(); peopleGroup.clear(); markerGroup.clear();
  }
  const livingOrRemembered = new Set(nextWorld.agents.map((agent) => agent.id));
  for (const [id, label] of labelElements) if (!livingOrRemembered.has(id)) { label.remove(); labelElements.delete(id); people.delete(id); }
  nextWorld.agents.forEach((agent) => updatePerson(agent, now));
  syncMarkers(nextWorld);
}

const projected = new THREE.Vector3();
function renderLabels() {
  for (const [id, figure] of people) {
    const label = labelElements.get(id);
    const anchor = figure.localToWorld(new THREE.Vector3(0, 0.39, 0));
    projected.copy(anchor).project(camera);
    const px = (projected.x * 0.5 + 0.5) * host.clientWidth;
    const py = (-projected.y * 0.5 + 0.5) * host.clientHeight;
    label.style.transform = `translate(${px}px,${py}px) translate(-50%,-100%)`;
    const facingCamera = anchor.clone().normalize().dot(camera.position.clone().sub(anchor).normalize()) > 0;
    label.style.display = projected.z < 1 && facingCamera ? "block" : "none";
  }
}

function resize() {
  const width = Math.max(host.clientWidth, 1); const height = Math.max(host.clientHeight, 1);
  renderer.setSize(width, height, false); camera.aspect = width / height; camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(host); resize();

function frame(now) {
  requestAnimationFrame(frame);
  controls.update();
  // Let the agents continue smoothly along their surface paths between API snapshots.
  for (const figure of people.values()) {
    const target = figure.userData.destinationNormal;
    if (target) {
      // Interpolate along the sphere's surface so a walking figure cannot cut through the planet.
      const surfaceNormal = figure.position.clone().normalize().lerp(target, 0.12).normalize();
      figure.position.copy(surfaceNormal.multiplyScalar(radius + 0.022));
      figure.quaternion.slerp(new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), surfaceNormal), 0.2);
    }
    figure.userData.halo.rotation.y = now * 0.0004;
  }
  renderLabels(); renderer.render(scene, camera);
}
requestAnimationFrame(frame);

function statBar(name, value, lowIsBad = false) {
  const level = Number(value || 0);
  const state = lowIsBad ? (level <= 25 ? "danger" : level <= 45 ? "warn" : "") : (level >= 85 ? "danger" : level >= 68 ? "warn" : "");
  return `<div class="stat-row"><div class="stat-top"><span>${name}</span><b>${Math.round(level)}%</b></div><div class="bar ${state}"><i style="width:${THREE.MathUtils.clamp(level, 0, 100)}%"></i></div></div>`;
}

function renderInspector() {
  const agent = world?.agents.find((person) => person.id === selectedAgentId);
  if (!agent) { ui.inspector.classList.remove("visible"); ui.inspector.innerHTML = '<div class="inspector-empty"><span class="eyebrow">LIFE RECORD</span><p>Select a person on Earth to see their story.</p></div>'; return; }
  ui.inspector.classList.add("visible");
  if (ui.inspector.contains(document.activeElement)) return;
  const age = agent.age_days < 365 ? `${agent.age_days} days` : `${Math.floor(agent.age_days / 365)} years`;
  const relatedNames = (ids) => ids.map((id) => world.agents.find((item) => item.id === id)?.name || "Unknown").join(", ") || "None";
  const partner = world.agents.find((person) => person.id === agent.bonded_partner_id);
  const traits = Object.entries(agent.traits || {}).map(([name, score]) => `${name} ${Math.round(score * 100)}`).join(" · ") || "Not developed";
  const memories = [...(agent.memories || [])].slice(-4).reverse();
  const condition = agent.alive ? (agent.disease ? `Ill · ${agent.disease}` : "Living") : "Deceased";
  const sexIcon = agent.sex === "female" ? "♀" : "♂";
  ui.inspector.innerHTML = `<div class="inspector-content"><div class="inspector-head"><div class="agent-avatar">${sexIcon}</div><div><h2>${escapeHtml(agent.name)}</h2><p>${escapeHtml(age)} · ${escapeHtml(agent.sex)}</p></div><button class="close-inspector" aria-label="Close inspector">×</button></div>
    <div class="condition ${agent.alive ? "" : "dead"}">${escapeHtml(condition.toUpperCase())} ${agent.disease ? `· ${agent.disease.toUpperCase()}` : ""}</div>
    ${statBar("health", agent.health, true)}${statBar("hunger", agent.hunger)}${statBar("thirst", agent.thirst)}${statBar("energy", agent.energy, true)}
    <form class="edit-form" id="edit-agent"><div class="edit-title">SPECTATOR ADJUSTMENT</div><div class="edit-grid">${["health", "hunger", "thirst", "energy"].map((key) => `<div class="edit-field"><label for="edit-${key}">${key}</label><input id="edit-${key}" name="${key}" type="number" min="0" max="100" value="${Math.round(agent[key])}" ${agent.alive ? "" : "disabled"}/></div>`).join("")}</div><button class="small-action" type="submit" ${agent.alive ? "" : "disabled"}>Apply changes</button></form>
    <div class="detail-list"><div class="detail-line"><span>Parents</span><span>${escapeHtml(relatedNames(agent.parent_ids || []))}</span></div><div class="detail-line"><span>Children</span><span>${escapeHtml(relatedNames(agent.children_ids || []))}</span></div><div class="detail-line"><span>Bond</span><span>${escapeHtml(partner?.name || "None")}</span></div><div class="detail-line"><span>Pregnancy</span><span>${agent.pregnancy_days_remaining == null ? "No" : `${agent.pregnancy_days_remaining} days`}</span></div><div class="detail-line"><span>Knowledge</span><span>${(agent.knowledge || []).length} learned</span></div><div class="detail-line"><span>Temperament</span><span>${escapeHtml(traits)}</span></div><div class="detail-line"><span>Last action</span><span>${escapeHtml(agent.last_action?.action?.replaceAll("_", " ") || "Observing")}</span></div></div>
    <ul class="memories">${memories.length ? memories.map((memory) => `<li>${escapeHtml(memory)}</li>`).join("") : "<li>No memories yet.</li>"}</ul></div>`;
  ui.inspector.querySelector(".close-inspector").addEventListener("click", () => { selectedAgentId = null; syncWorldObjects(world); renderInspector(); });
  ui.inspector.querySelector("#edit-agent").addEventListener("submit", async (event) => {
    event.preventDefault();
    const changes = Object.fromEntries(new FormData(event.currentTarget).entries());
    for (const key of Object.keys(changes)) changes[key] = Number(changes[key]);
    try { await api(`/api/agents/${encodeURIComponent(agent.id)}/state`, { method: "PATCH", body: JSON.stringify(changes) }); notify(`${agent.name}'s condition was updated.`); await refreshWorld(); }
    catch (error) { notify(error.message, true); }
  });
}

function renderCulture() {
  const structures = world?.structures || []; const groups = world?.groups || []; const beliefs = world?.beliefs || [];
  $("#culture-count").textContent = String(groups.length + beliefs.length + structures.length);
  const block = (title, items) => `<div class="culture-block"><h4>${title} · ${items.length}</h4><div class="chip-list">${items.length ? items.map((item) => `<span class="chip">${escapeHtml(item)}</span>`).join("") : '<span class="chip">None yet</span>'}</div></div>`;
  $("#culture-popover").innerHTML = `<h3>World culture</h3>${block("Structures", structures.map((item) => item.kind.replaceAll("_", " ")))}${block("Groups", groups.map((item) => `${item.name} · ${item.kind} · ${item.member_ids.length}`))}${block("Beliefs", beliefs.map((item) => `${item.name} · ${item.kind}`))}`;
}

function renderWorld(next) {
  world = next;
  const year = Math.floor(world.tick / 365) + 1; const day = world.tick % 365 || 365;
  const living = world.agents.filter((person) => person.alive).length;
  ui.clock.textContent = `YEAR ${year} · DAY ${day}${world.processing ? " · THINKING" : ""}`;
  $("#population-label").textContent = String(living);
  $("#age-label").textContent = String(year);
  $("#weather-label").textContent = world.weather || "clear";
  $("#world-summary").textContent = `${living} alive · ${world.agents.length} lives in the world · ${world.season || "spring"}`;
  ui.run.textContent = world.running ? "Ⅱ" : "▶";
  ui.run.title = world.running ? "Pause the simulation" : "Run the simulation";
  syncWorldObjects(world); renderInspector(); renderCulture();
}

async function refreshWorld() {
  try { renderWorld(await api("/api/world")); }
  catch (error) { ui.clock.textContent = "BACKEND UNAVAILABLE"; notify(error.message, true); }
}

async function refreshModels() {
  try {
    const [health, response] = await Promise.all([api("/api/health"), api("/api/models")]);
    const selected = world?.global_model || health.default_model || "gemma4:e2b";
    const options = (response.models || []).map((model) => `<option value="${escapeHtml(model)}">${escapeHtml(model)}</option>`);
    if (!response.models?.includes(selected)) options.unshift(`<option value="${escapeHtml(selected)}">${escapeHtml(selected)} · unavailable</option>`);
    ui.model.innerHTML = options.join("") || `<option value="${escapeHtml(selected)}">${escapeHtml(selected)}</option>`;
    ui.model.value = selected;
    ui.model.title = health.ollama_available ? "This one model guides every agent; their memories remain individual." : "Ollama is unavailable. The world can continue with its survival fallback.";
  } catch (error) { ui.model.innerHTML = "<option>Ollama unavailable</option>"; ui.model.title = error.message; }
}

ui.run.addEventListener("click", async () => {
  try {
    if (world?.running) await api("/api/world/pause", { method: "POST" });
    else await api("/api/world/run?interval_seconds=3", { method: "POST" });
    await refreshWorld();
  } catch (error) { notify(error.message, true); }
});
ui.step.addEventListener("click", async () => {
  if (isStepping) return;
  isStepping = true; ui.step.disabled = true;
  try { renderWorld(await api("/api/world/tick", { method: "POST" })); }
  catch (error) { notify(error.message, true); }
  finally { isStepping = false; ui.step.disabled = false; }
});
ui.model.addEventListener("change", async () => {
  try { renderWorld(await api("/api/world/model", { method: "PATCH", body: JSON.stringify({ model: ui.model.value }) })); notify(`Shared model changed to ${ui.model.value}.`); }
  catch (error) { notify(error.message, true); await refreshModels(); }
});
$("#reset-world").addEventListener("click", async () => {
  if (!window.confirm("Start a new world? This replaces the currently saved world.")) return;
  try { renderWorld(await api(`/api/world/reset?seed=${Math.floor(Math.random() * 1_000_000)}`, { method: "POST" })); notify("A new world has begun."); await refreshModels(); }
  catch (error) { notify(error.message, true); }
});
$("#culture-button").addEventListener("click", () => { const panel = $("#culture-popover"); panel.hidden = !panel.hidden; });

function castPointer(event) {
  const bounds = renderer.domElement.getBoundingClientRect();
  pointer.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1;
  pointer.y = -((event.clientY - bounds.top) / bounds.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
}
function hitPlanet(event) {
  castPointer(event);
  const hit = raycaster.intersectObject(globe, false)[0];
  if (!hit) return null;
  const local = planet.worldToLocal(hit.point.clone()).normalize();
  let longitude = THREE.MathUtils.radToDeg(Math.atan2(local.x, local.z));
  const latitude = THREE.MathUtils.radToDeg(Math.asin(THREE.MathUtils.clamp(local.y, -1, 1)));
  if (longitude < 0) longitude += 360;
  const x = Math.round(THREE.MathUtils.clamp((longitude - 28) / 27 * 12, 0, 11));
  const y = Math.round(THREE.MathUtils.clamp((15 - latitude) / 27 * 8, 0, 7));
  return { x, y, point: hit.point };
}
renderer.domElement.addEventListener("pointerdown", (event) => { pointerDown = { x: event.clientX, y: event.clientY }; });
renderer.domElement.addEventListener("pointerup", (event) => {
  if (!pointerDown || Math.hypot(event.clientX - pointerDown.x, event.clientY - pointerDown.y) > 5) { pointerDown = null; return; }
  castPointer(event);
  const clicked = raycaster.intersectObjects(peopleGroup.children, true).map((hit) => hit.object.userData.agentId).find(Boolean);
  if (clicked) { selectedAgentId = clicked; renderInspector(); syncWorldObjects(world); }
  pointerDown = null;
});

async function triggerEvent(kind, location) {
  if (!world) return;
  try {
    const request = { kind, x: location?.x ?? Math.floor(world.width / 2), y: location?.y ?? Math.floor(world.height / 2) };
    renderWorld(await api("/api/events", { method: "POST", body: JSON.stringify(request) }));
    notify(`${kind.replaceAll("_", " ")} introduced to the world.`);
  } catch (error) { notify(error.message, true); }
}
for (const tool of document.querySelectorAll(".event-tool")) {
  tool.addEventListener("dragstart", (event) => { draggedEvent = tool.dataset.event; event.dataTransfer.setData("text/plain", draggedEvent); tool.classList.add("dragging"); host.classList.add("drop-hover"); });
  tool.addEventListener("dragend", () => { draggedEvent = null; tool.classList.remove("dragging"); host.classList.remove("drop-hover"); });
}
host.addEventListener("dragover", (event) => { event.preventDefault(); host.classList.add("drop-hover"); });
host.addEventListener("dragleave", (event) => { if (!host.contains(event.relatedTarget)) host.classList.remove("drop-hover"); });
host.addEventListener("drop", async (event) => {
  event.preventDefault(); host.classList.remove("drop-hover");
  const kind = event.dataTransfer.getData("text/plain") || draggedEvent;
  const location = hitPlanet(event);
  if (!kind) return;
  if (!location) return notify("Place the event on the visible side of Earth.", true);
  await triggerEvent(kind, location);
});

refreshWorld(); refreshModels();
// Polling keeps the spectator current without letting the UI advance biology itself.
setInterval(refreshWorld, 1500);
setInterval(refreshModels, 20000);
