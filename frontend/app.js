import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

// The browser is a spectator: the FastAPI world remains the single source of truth.
const $ = (selector) => document.querySelector(selector);
const sceneHost = $("#world-scene");
const ui = {
  clock: $("#clock-label"), model: $("#model-select"), run: $("#run-button"), step: $("#step-button"),
  speed: $("#speed-select"), inspector: $("#agent-inspector"), agents: $("#agent-cards"),
  toast: $("#toast"), timeline: $("#event-list"), culture: $("#culture-content"),
};
let world = null;
let selectedAgentId = "agent-1";
let toastTimer = null;
let busy = false;
let dragKind = null;

// Escape model-generated content before inserting it in the inspector or event list.
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
  return payload;
}

function notify(message, error = false) {
  ui.toast.textContent = message;
  ui.toast.classList.toggle("error", error);
  ui.toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => ui.toast.classList.remove("visible"), 2800);
}

// Three.js renders one continuous height-mapped landform, with no visible tile grid.
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.7));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.15;
sceneHost.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0x101918, 0.023);
const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 250);
camera.position.set(19, 19, 22);
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 0, 0);
controls.enableDamping = true;
controls.dampingFactor = 0.075;
controls.minDistance = 12;
controls.maxDistance = 42;
controls.maxPolarAngle = Math.PI * 0.48;

scene.add(new THREE.HemisphereLight(0xcbd8d0, 0x1b231c, 2.1));
const sun = new THREE.DirectionalLight(0xffe2b8, 3.0);
sun.position.set(-12, 22, 10);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
sun.shadow.camera.left = -24; sun.shadow.camera.right = 24;
sun.shadow.camera.top = 24; sun.shadow.camera.bottom = -24;
scene.add(sun);

const terrainGroup = new THREE.Group();
scene.add(terrainGroup);
const peopleGroup = new THREE.Group();
scene.add(peopleGroup);
const resourceGroup = new THREE.Group();
scene.add(resourceGroup);
const structureGroup = new THREE.Group();
scene.add(structureGroup);
const labels = new Map();
const peopleMeshes = new Map();
const sceneObjects = new Map();
const groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
const worldWidth = 12;
const worldHeight = 8;
const spacing = 2;
let landWidth = worldWidth * spacing;
let landDepth = worldHeight * spacing;
let lastClickPoint = null;

function terrainHeight(x, z) {
  // Gentle blended hills provide height variation without hiding the walkable ground.
  return 0.18 * Math.sin(x * 0.27) * Math.cos(z * 0.36) + 0.12 * Math.sin(z * 0.64 + x * 0.18);
}
function worldToScene(x, z) { return new THREE.Vector3((x - (worldWidth - 1) / 2) * spacing, terrainHeight((x - (worldWidth - 1) / 2) * spacing, (z - (worldHeight - 1) / 2) * spacing), (z - (worldHeight - 1) / 2) * spacing); }
function sceneToWorld(point) {
  return { x: THREE.MathUtils.clamp(Math.round(point.x / spacing + (worldWidth - 1) / 2), 0, worldWidth - 1), y: THREE.MathUtils.clamp(Math.round(point.z / spacing + (worldHeight - 1) / 2), 0, worldHeight - 1) };
}

function createTerrain() {
  const geometry = new THREE.PlaneGeometry(landWidth, landDepth, 100, 72);
  geometry.rotateX(-Math.PI / 2);
  const positions = geometry.attributes.position;
  const colors = [];
  const low = new THREE.Color("#314435");
  const mid = new THREE.Color("#526047");
  const high = new THREE.Color("#786f58");
  for (let i = 0; i < positions.count; i += 1) {
    const x = positions.getX(i); const z = positions.getZ(i);
    const height = terrainHeight(x, z);
    positions.setY(i, height);
    const color = height > 0.12 ? mid.clone().lerp(high, Math.min((height - 0.12) * 1.6, 0.45)) : low.clone().lerp(mid, Math.max((height + 0.35) * 1.8, 0.12));
    const noise = 0.97 + 0.03 * Math.sin(i * 0.41);
    colors.push(color.r * noise, color.g * noise, color.b * noise);
  }
  geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
  geometry.computeVertexNormals();
  const land = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.94, metalness: 0 }));
  land.receiveShadow = true;
  land.userData.isLand = true;
  terrainGroup.add(land);
  // A quiet dark plinth gives the terrain a clear edge without drawing a map grid.
  const base = new THREE.Mesh(new THREE.BoxGeometry(landWidth + 0.8, 0.65, landDepth + 0.8), new THREE.MeshStandardMaterial({ color: 0x18221f, roughness: 0.9 }));
  base.position.y = -0.46;
  base.receiveShadow = true;
  terrainGroup.add(base);
  const waterMat = new THREE.MeshStandardMaterial({ color: 0x356f7b, roughness: 0.32, metalness: 0.08, transparent: true, opacity: 0.88 });
  // Natural pools and shallow streams visually ground water resource nodes.
  for (const [x, z, sx, sz] of [[-7, -4, 3.2, 1.1], [5, 4, 2.6, 0.85], [-1, 6.5, 1.5, 0.65]]) {
    const pool = new THREE.Mesh(new THREE.CircleGeometry(1, 36), waterMat);
    pool.rotation.x = -Math.PI / 2;
    pool.scale.set(sx, sz, 1);
    pool.position.set(x, terrainHeight(x, z) + 0.035, z);
    pool.receiveShadow = true;
    terrainGroup.add(pool);
  }
}

function addTree(x, z, scale = 1) {
  const group = new THREE.Group();
  const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.11, 0.17, 0.85, 7), new THREE.MeshStandardMaterial({ color: 0x76583c, roughness: 1 }));
  trunk.position.y = 0.45;
  const foliageMat = new THREE.MeshStandardMaterial({ color: 0x566e49, roughness: 1, flatShading: true });
  const crown = new THREE.Mesh(new THREE.IcosahedronGeometry(0.66, 1), foliageMat);
  crown.position.y = 1.16;
  crown.scale.set(0.9, 1.18, 0.88);
  group.add(trunk, crown);
  group.scale.setScalar(scale);
  const position = worldToScene(x, z);
  group.position.set(position.x, position.y, position.z);
  group.traverse((mesh) => { if (mesh.isMesh) { mesh.castShadow = true; mesh.receiveShadow = true; } });
  resourceGroup.add(group);
}

function seedScenery() {
  // Seeded decorative plants keep the same terrain feel between refreshes.
  let seed = 31;
  const random = () => { seed = (seed * 1664525 + 1013904223) % 4294967296; return seed / 4294967296; };
  for (let i = 0; i < 46; i += 1) {
    const x = random() * (worldWidth - 1); const z = random() * (worldHeight - 1);
    const nearWater = Math.abs(x - 1.8) + Math.abs(z - 1.2) < 2 || Math.abs(x - 8) + Math.abs(z - 6) < 2;
    if (!nearWater && random() > 0.28) addTree(x, z, 0.65 + random() * 0.55);
  }
}

function makeHumanoid(person) {
  // A small articulated low-poly body makes locomotion legible at spectator zoom.
  const root = new THREE.Group();
  root.userData.agentId = person.id;
  const skin = new THREE.MeshStandardMaterial({ color: person.sex === "female" ? 0xc99d75 : 0xb88963, roughness: 0.9 });
  const cloth = new THREE.MeshStandardMaterial({ color: person.sex === "female" ? 0x9d7060 : 0x65785b, roughness: 1 });
  const darkCloth = new THREE.MeshStandardMaterial({ color: 0x3c4940, roughness: 1 });
  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.19, 0.34, 4, 7), cloth);
  body.position.y = 0.83;
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.145, 10, 8), skin);
  head.position.y = 1.25;
  const hair = new THREE.Mesh(new THREE.SphereGeometry(0.15, 10, 7, 0, Math.PI * 2, 0, Math.PI * 0.6), darkCloth);
  hair.position.y = 1.3;
  root.add(body, head, hair);
  const limbs = [];
  for (const side of [-1, 1]) {
    const arm = new THREE.Mesh(new THREE.CapsuleGeometry(0.055, 0.29, 3, 6), skin);
    arm.position.set(side * 0.22, 0.83, 0);
    arm.userData.swingPhase = side < 0 ? 0 : Math.PI;
    root.add(arm); limbs.push(arm);
    const leg = new THREE.Mesh(new THREE.CapsuleGeometry(0.07, 0.31, 3, 6), darkCloth);
    leg.position.set(side * 0.085, 0.36, 0);
    leg.userData.swingPhase = side < 0 ? Math.PI : 0;
    root.add(leg); limbs.push(leg);
  }
  const selectionRing = new THREE.Mesh(new THREE.RingGeometry(0.32, 0.38, 24), new THREE.MeshBasicMaterial({ color: 0xb3d789, side: THREE.DoubleSide, transparent: true, opacity: 0.9 }));
  selectionRing.rotation.x = -Math.PI / 2;
  selectionRing.position.y = 0.035;
  selectionRing.visible = person.id === selectedAgentId;
  root.add(selectionRing);
  root.userData.limbs = limbs;
  root.userData.selectionRing = selectionRing;
  root.traverse((mesh) => { if (mesh.isMesh) { mesh.castShadow = true; mesh.receiveShadow = true; mesh.userData.agentId = person.id; } });
  const label = document.createElement("div");
  label.className = "scene-label";
  label.dataset.agentId = person.id;
  sceneHost.appendChild(label);
  labels.set(person.id, label);
  peopleGroup.add(root);
  peopleMeshes.set(person.id, root);
  return root;
}

function createResource(node) {
  const group = new THREE.Group();
  const pos = worldToScene(node.x, node.y);
  group.position.set(pos.x, pos.y, pos.z);
  const quantityScale = Math.max(0.45, Math.min(1.25, node.quantity / 18));
  if (node.kind === "food") {
    const bush = new THREE.Mesh(new THREE.IcosahedronGeometry(0.27 * quantityScale, 1), new THREE.MeshStandardMaterial({ color: 0x739b53, roughness: 1, flatShading: true }));
    bush.position.y = 0.25;
    group.add(bush);
    for (let i = 0; i < 3; i += 1) { const berry = new THREE.Mesh(new THREE.SphereGeometry(0.07, 7, 6), new THREE.MeshStandardMaterial({ color: 0xd27d54 })); berry.position.set((i - 1) * 0.13, 0.3 + (i % 2) * 0.1, 0.17); group.add(berry); }
  } else if (node.kind === "wood") {
    const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.10, 0.16, 0.75 * quantityScale, 7), new THREE.MeshStandardMaterial({ color: 0x76583c, roughness: 1 }));
    trunk.position.y = 0.38; group.add(trunk);
    const crown = new THREE.Mesh(new THREE.IcosahedronGeometry(0.46 * quantityScale, 1), new THREE.MeshStandardMaterial({ color: 0x4f6846, roughness: 1, flatShading: true }));
    crown.position.y = 0.89; group.add(crown);
  } else {
    const geo = node.kind === "water" ? new THREE.CylinderGeometry(0.58, 0.67, 0.07, 20) : new THREE.DodecahedronGeometry(0.36 * quantityScale, 0);
    const mat = new THREE.MeshStandardMaterial({ color: node.kind === "water" ? 0x4c8794 : 0x929590, roughness: node.kind === "water" ? 0.35 : 1, metalness: 0.04, transparent: node.kind === "water", opacity: node.kind === "water" ? 0.85 : 1, flatShading: true });
    const object = new THREE.Mesh(geo, mat); object.position.y = node.kind === "water" ? 0.045 : 0.28; group.add(object);
  }
  group.traverse((mesh) => { if (mesh.isMesh) { mesh.castShadow = true; mesh.receiveShadow = true; } });
  resourceGroup.add(group);
  sceneObjects.set(`resource-${node.kind}-${node.x}-${node.y}`, group);
}

function createStructure(building) {
  const group = new THREE.Group();
  const wood = new THREE.MeshStandardMaterial({ color: 0x947652, roughness: 1 });
  const roof = new THREE.MeshStandardMaterial({ color: 0x534a3d, roughness: 1, flatShading: true });
  const crop = new THREE.MeshStandardMaterial({ color: 0x86a55b, roughness: 1 });
  const pos = worldToScene(building.x, building.y);
  group.position.set(pos.x, pos.y, pos.z);
  const size = building.kind === "communal_house" ? 1.35 : 0.9;
  if (building.kind === "farm") {
    const plot = new THREE.Mesh(new THREE.BoxGeometry(1.3, 0.12, 1.1), new THREE.MeshStandardMaterial({ color: 0x564832, roughness: 1 }));
    plot.position.y = 0.07; group.add(plot);
    for (let row = 0; row < 3; row += 1) for (let stem = 0; stem < 4; stem += 1) {
      const plant = new THREE.Mesh(new THREE.ConeGeometry(0.08, 0.27, 5), crop);
      plant.position.set(-0.43 + stem * 0.28, 0.24, -0.34 + row * 0.31); group.add(plant);
    }
  } else if (building.kind === "shrine") {
    const altar = new THREE.Mesh(new THREE.CylinderGeometry(0.37, 0.44, 0.32, 8), roof);
    altar.position.y = 0.16; group.add(altar);
    for (let pillar = 0; pillar < 4; pillar += 1) {
      const angle = pillar * Math.PI / 2;
      const stone = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.11, 0.85, 6), wood);
      stone.position.set(Math.cos(angle) * 0.52, 0.44, Math.sin(angle) * 0.52); group.add(stone);
    }
  } else if (building.kind === "granary") {
    const store = new THREE.Mesh(new THREE.CylinderGeometry(0.45, 0.5, 1.05, 8), wood);
    store.position.y = 0.53; group.add(store);
    const lid = new THREE.Mesh(new THREE.ConeGeometry(0.61, 0.42, 8), roof);
    lid.position.y = 1.25; group.add(lid);
  } else {
    const leanTo = building.kind === "lean_to";
    const hut = new THREE.Mesh(new THREE.BoxGeometry(size, 0.9 * size, size), wood);
    hut.position.y = 0.47 * size;
    const cap = new THREE.Mesh(leanTo ? new THREE.BoxGeometry(size * 1.25, 0.12, size) : new THREE.ConeGeometry(size * 0.78, size * 0.72, 4), roof);
    cap.position.y = leanTo ? 0.92 * size : 1.22 * size;
    cap.rotation.y = leanTo ? -0.16 : Math.PI / 4;
    group.add(hut, cap);
    if (building.kind === "workshop") {
      const chimney = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.14, 0.7, 6), roof);
      chimney.position.set(size * 0.36, size * 1.05, -size * 0.25); group.add(chimney);
    }
  }
  group.traverse((mesh) => { if (mesh.isMesh) { mesh.castShadow = true; mesh.receiveShadow = true; } });
  structureGroup.add(group);
  sceneObjects.set(`structure-${building.id}`, group);
}

createTerrain();
seedScenery();

function resizeScene() {
  const width = sceneHost.clientWidth; const height = sceneHost.clientHeight;
  renderer.setSize(width, height, false);
  camera.aspect = width / Math.max(height, 1);
  camera.updateProjectionMatrix();
}
new ResizeObserver(resizeScene).observe(sceneHost);
resizeScene();

let currentWorldId = null;
function syncObjects(nextWorld) {
  if (currentWorldId !== nextWorld.id) {
    currentWorldId = nextWorld.id;
    for (const label of labels.values()) label.remove();
    labels.clear(); peopleMeshes.clear(); sceneObjects.clear();
    peopleGroup.clear(); resourceGroup.clear(); structureGroup.clear();
  }
  const liveIds = new Set(nextWorld.agents.map((person) => person.id));
  for (const [id, label] of labels) {
    if (!liveIds.has(id)) { label.remove(); labels.delete(id); peopleMeshes.delete(id); }
  }
  for (const person of nextWorld.agents) {
    let figure = peopleMeshes.get(person.id);
    if (!figure) figure = makeHumanoid(person);
    const destination = worldToScene(person.x, person.y);
    // Smoothly interpolate between daily decisions instead of teleporting the 3D figure.
    figure.userData.destination = destination;
    figure.userData.moving = person.last_action?.action === "move" && person.alive;
    figure.userData.dead = !person.alive;
    figure.userData.selectionRing.visible = person.alive && person.id === selectedAgentId;
    figure.traverse((part) => {
      if (part.isMesh && part.material) {
        // Deceased figures remain in the world history but read visually as inactive.
        part.material.transparent = !person.alive;
        part.material.opacity = person.alive ? 1 : 0.34;
      }
    });
    const label = labels.get(person.id);
    label.textContent = person.alive ? `${person.name} · ${Math.floor(person.age_days / 365)}` : `${person.name} · deceased`;
    label.classList.toggle("selected", person.id === selectedAgentId);
    label.classList.toggle("dead", !person.alive);
  }
  const desiredResources = new Set();
  for (const node of nextWorld.resources) {
    if (node.quantity <= 0) continue;
    const key = `resource-${node.kind}-${node.x}-${node.y}`; desiredResources.add(key);
    if (!sceneObjects.has(key)) createResource(node);
  }
  const desiredStructures = new Set();
  for (const building of nextWorld.structures) {
    const key = `structure-${building.id}`; desiredStructures.add(key);
    if (!sceneObjects.has(key)) createStructure(building);
  }
  // Remove depleted forage nodes and deleted-world remnants from the rendered groups.
  for (const [key, object] of sceneObjects) {
    if ((key.startsWith("resource-") && !desiredResources.has(key)) || (key.startsWith("structure-") && !desiredStructures.has(key))) {
      object.removeFromParent(); sceneObjects.delete(key);
    }
  }
}

function renderLabels() {
  const projected = new THREE.Vector3();
  for (const [id, figure] of peopleMeshes) {
    const label = labels.get(id);
    projected.copy(figure.position).add(new THREE.Vector3(0, 1.63, 0)).project(camera);
    const x = (projected.x * 0.5 + 0.5) * sceneHost.clientWidth;
    const y = (-projected.y * 0.5 + 0.5) * sceneHost.clientHeight;
    label.style.transform = `translate(${x}px,${y}px) translate(-50%,-100%)`;
    label.style.display = projected.z < 1 && !figure.userData.dead ? "block" : "none";
  }
}

function frame(now) {
  requestAnimationFrame(frame);
  const seconds = now * 0.001;
  controls.update();
  for (const [id, figure] of peopleMeshes) {
    const destination = figure.userData.destination;
    if (destination) {
      figure.position.x = THREE.MathUtils.damp(figure.position.x, destination.x, 3.2, 1 / 60);
      figure.position.z = THREE.MathUtils.damp(figure.position.z, destination.z, 3.2, 1 / 60);
      const groundY = terrainHeight(figure.position.x, figure.position.z);
      figure.position.y = THREE.MathUtils.damp(figure.position.y, groundY, 4, 1 / 60);
      const moving = figure.userData.moving && figure.position.distanceTo(destination) > 0.16;
      figure.userData.limbs.forEach((limb) => { limb.rotation.x = moving ? Math.sin(seconds * 7 + limb.userData.swingPhase) * 0.48 : THREE.MathUtils.damp(limb.rotation.x, 0, 5, 1 / 60); });
      figure.rotation.y = Math.atan2(destination.x - figure.position.x, destination.z - figure.position.z);
    }
    figure.userData.selectionRing.rotation.z = seconds * 0.45;
  }
  renderLabels();
  renderer.render(scene, camera);
}
requestAnimationFrame(frame);

function statBar(label, value) {
  const urgency = value >= 75 ? "danger" : value >= 55 ? "warn" : "";
  return `<div class="stat-row"><div class="stat-top"><span>${label}</span><b>${Math.round(value)}%</b></div><div class="bar ${urgency}"><i style="width:${Math.max(0, Math.min(100, value))}%"></i></div></div>`;
}

function renderInspector() {
  const person = world?.agents.find((item) => item.id === selectedAgentId);
  if (!person) { ui.inspector.innerHTML = '<div class="empty-state">Select a person in the world to inspect their life.</div>'; return; }
  // Avoid replacing an edit form while a spectator is entering values.
  if (ui.inspector.contains(document.activeElement)) return;
  const partner = world.agents.find((item) => item.id === person.bonded_partner_id);
  const namesFor = (ids) => ids.map((id) => world.agents.find((item) => item.id === id)?.name || "Unknown").join(", ") || "None";
  const relationships = Object.entries(person.relationship_scores || {}).map(([id, score]) => {
    const related = world.agents.find((item) => item.id === id);
    return related ? `${related.name} ${Math.round(score)}` : null;
  }).filter(Boolean).join(" · ") || "None recorded";
  const memories = [...(person.memories || [])].slice(-4).reverse();
  const traits = Object.entries(person.traits || {}).map(([name, value]) => `${name} ${Math.round(value * 100)}`).join(" · ") || "None";
  const age = person.age_days < 365 ? `${person.age_days} days` : `${Math.floor(person.age_days / 365)} years`;
  const condition = person.alive ? (person.disease ? `Ill · ${person.disease}` : "Alive") : "Deceased";
  $("#selected-person-tag").textContent = person.alive ? "LIVING" : "DECEASED";
  ui.inspector.innerHTML = `<div class="inspector-person"><div class="person-avatar ${person.sex}">${person.sex === "female" ? "♀" : "♂"}</div><div><h3>${escapeHtml(person.name)}</h3><p>${escapeHtml(condition)} · ${escapeHtml(age)} · ${escapeHtml(person.sex)}</p></div></div>
    ${statBar("Health", person.health)}${statBar("Hunger", person.hunger)}${statBar("Thirst", person.thirst)}${statBar("Energy", person.energy)}
    <form id="stat-edit-form"><div class="eyebrow" style="margin-top:13px">SPECTATOR ADJUSTMENT</div><div class="stat-edit-grid">${["health", "hunger", "thirst", "energy"].map((key) => `<div class="edit-field"><label for="edit-${key}">${key}</label><input id="edit-${key}" name="${key}" type="number" min="0" max="100" step="1" value="${Math.round(person[key])}" ${person.alive ? "" : "disabled"}/></div>`).join("")}</div><button class="small-action" type="submit" ${person.alive ? "" : "disabled"}>Apply condition changes</button></form>
    <div class="detail-lines"><div class="detail-line"><span>Parents</span><span>${escapeHtml(namesFor(person.parent_ids || []))}</span></div><div class="detail-line"><span>Children</span><span>${escapeHtml(namesFor(person.children_ids || []))}</span></div><div class="detail-line"><span>Bond</span><span>${escapeHtml(partner?.name || "None")}</span></div><div class="detail-line"><span>Relationships</span><span>${escapeHtml(relationships)}</span></div><div class="detail-line"><span>Pregnancy</span><span>${person.pregnancy_days_remaining == null ? "No" : `${person.pregnancy_days_remaining} days`}</span></div><div class="detail-line"><span>Knowledge</span><span>${(person.knowledge || []).length} learned · ${escapeHtml(traits)}</span></div><div class="detail-line"><span>Memories</span><span>Individual history</span></div><ul class="memory-list">${memories.length ? memories.map((memory) => `<li>${escapeHtml(memory)}</li>`).join("") : "<li>No memories yet.</li>"}</ul></div>`;
  $("#stat-edit-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const changes = Object.fromEntries(new FormData(event.currentTarget).entries());
    for (const key of Object.keys(changes)) changes[key] = Number(changes[key]);
    try { await api(`/api/agents/${encodeURIComponent(person.id)}/state`, { method: "PATCH", body: JSON.stringify(changes) }); notify(`${person.name}'s condition was updated.`); await refreshWorld(); }
    catch (error) { notify(error.message, true); }
  });
}

function renderAgents() {
  const people = world?.agents || [];
  $("#people-total").textContent = String(people.length);
  ui.agents.innerHTML = people.map((person) => {
    const choice = person.last_action?.action?.replaceAll("_", " ") || "observing the world";
    return `<article class="agent-card ${person.id === selectedAgentId ? "selected" : ""}" data-select-agent="${escapeHtml(person.id)}"><div class="agent-card-head"><div class="mini-avatar ${person.sex}">${person.sex === "female" ? "♀" : "♂"}</div><div><h3>${escapeHtml(person.name)}${person.alive ? "" : " · deceased"}</h3><small>${Math.floor(person.age_days / 365)} years · ${escapeHtml(person.disease || (person.alive ? "healthy" : "died"))}</small></div></div><div class="agent-action-line">Last choice: ${escapeHtml(choice)}</div></article>`;
  }).join("") || '<div class="empty-state">No one remains alive in this world.</div>';
}

function renderTimeline() {
  const events = [...(world?.events || [])].slice(-30).reverse();
  $("#event-count").textContent = `${world?.events?.length || 0} events`;
  ui.timeline.innerHTML = events.length ? events.map((event) => {
    const year = Math.floor(event.tick / 365) + 1;
    return `<div class="event-item"><div class="event-tick">Y${year} · ${event.tick}</div><div><div class="event-message">${escapeHtml(event.message)}</div><div class="event-meta"><span class="event-tag ${escapeHtml(event.source)}">${escapeHtml(event.source.replaceAll("_", " "))}</span><span class="event-tag">${escapeHtml(event.kind.replaceAll("_", " "))}</span></div></div></div>`;
  }).join("") : '<div class="empty-state">The story starts with the first choice.</div>';
}

function renderCulture() {
  const structures = world?.structures || []; const groups = world?.groups || []; const beliefs = world?.beliefs || [];
  const counts = Object.entries(structures.reduce((result, item) => ({ ...result, [item.kind]: (result[item.kind] || 0) + 1 }), {}));
  const chips = (items) => items.length ? items.map((item) => `<span class="chip">${escapeHtml(item)}</span>`).join("") : '<span class="empty-state">Nothing yet</span>';
  ui.culture.innerHTML = `<div class="culture-block"><h3>Property · ${structures.length} built</h3><div class="chip-list">${chips(counts.map(([kind, number]) => `${kind.replaceAll("_", " ")} ×${number}`))}</div></div><div class="culture-block"><h3>Groups · ${groups.length}</h3><div class="chip-list">${chips(groups.map((group) => `${group.name} · ${group.kind} · ${group.member_ids.length}`))}</div></div><div class="culture-block"><h3>Beliefs · ${beliefs.length}</h3><div class="chip-list">${beliefs.length ? beliefs.map((belief) => `<span class="chip belief" title="${escapeHtml(belief.description)}">${escapeHtml(belief.name)} · ${escapeHtml(belief.kind)}</span>`).join("") : '<span class="empty-state">No beliefs have emerged.</span>'}</div></div>`;
}

function renderWorld(next) {
  world = next;
  const day = world.tick % 365 || 365;
  const year = Math.floor(world.tick / 365) + 1;
  const alive = world.agents.filter((person) => person.alive).length;
  ui.clock.textContent = `YEAR ${year} · DAY ${day} · WORLD ${world.id.slice(0, 8).toUpperCase()}${world.processing ? " · AGENTS DECIDING" : ""}`;
  $("#population-label").textContent = `${alive} living / ${world.agents.length} total`;
  $("#season-label").textContent = world.season || "spring";
  $("#weather-label").textContent = world.weather || "clear";
  $("#tech-label").textContent = `Level ${world.tech_level}`;
  ui.run.textContent = world.running ? "Ⅱ  Pause world" : "▶  Run world";
  syncObjects(world);
  renderAgents(); renderInspector(); renderTimeline(); renderCulture();
}

async function refreshWorld() {
  try { renderWorld(await api("/api/world")); }
  catch (error) { ui.clock.textContent = "Backend unavailable"; notify(error.message, true); }
}

async function refreshModels() {
  try {
    const [health, models] = await Promise.all([api("/api/health"), api("/api/models")]);
    const installed = models.models || [];
    const current = world?.global_model || health.default_model || "gemma4:e2b";
    const options = installed.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`);
    if (!installed.includes(current)) options.unshift(`<option value="${escapeHtml(current)}">${escapeHtml(current)} · unavailable</option>`);
    ui.model.innerHTML = options.join("");
    ui.model.value = current;
    ui.model.title = !health.ollama_available ? "Ollama is not reachable; survival fallback decisions will be used." : installed.includes(current) ? `${current} is installed and ready.` : "The world's configured model is not installed.";
  } catch (error) { ui.model.innerHTML = '<option>Ollama unavailable</option>'; ui.model.title = error.message; }
}

function setBusy(value) { busy = value; ui.step.disabled = value; }
ui.run.addEventListener("click", async () => {
  try {
    if (world?.running) await api("/api/world/pause", { method: "POST" });
    else await api(`/api/world/run?interval_seconds=${encodeURIComponent(ui.speed.value)}`, { method: "POST" });
    await refreshWorld();
  } catch (error) { notify(error.message, true); }
});
ui.step.addEventListener("click", async () => {
  if (busy) return;
  setBusy(true);
  try { renderWorld(await api("/api/world/tick", { method: "POST" })); }
  catch (error) { notify(error.message, true); }
  finally { setBusy(false); }
});
ui.model.addEventListener("change", async () => {
  try { renderWorld(await api("/api/world/model", { method: "PATCH", body: JSON.stringify({ model: ui.model.value }) })); notify(`Every agent now uses ${ui.model.value}.`); }
  catch (error) { notify(error.message, true); await refreshModels(); }
});
$("#reset-world").addEventListener("click", async () => {
  if (!window.confirm("Start a new world? This replaces the currently saved world.")) return;
  try { selectedAgentId = "agent-1"; renderWorld(await api(`/api/world/reset?seed=${Math.floor(Math.random() * 1000000)}`, { method: "POST" })); notify("A new world has begun."); await refreshModels(); }
  catch (error) { notify(error.message, true); }
});
ui.agents.addEventListener("click", (event) => {
  const card = event.target.closest("[data-select-agent]");
  if (card) { selectedAgentId = card.dataset.selectAgent; renderWorld(world); }
});

function positionFromPointer(event) {
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
}
function groundHit(event) {
  positionFromPointer(event);
  const hit = raycaster.ray.intersectPlane(groundPlane, new THREE.Vector3());
  if (!hit || Math.abs(hit.x) > landWidth / 2 || Math.abs(hit.z) > landDepth / 2) return null;
  return hit;
}
let pointerDown = null;
renderer.domElement.addEventListener("pointerdown", (event) => { pointerDown = { x: event.clientX, y: event.clientY }; });
renderer.domElement.addEventListener("pointerup", (event) => {
  if (!pointerDown || Math.hypot(event.clientX - pointerDown.x, event.clientY - pointerDown.y) > 5) return;
  positionFromPointer(event);
  const hits = raycaster.intersectObjects(peopleGroup.children, true);
  const personId = hits.map((hit) => hit.object.userData.agentId || hit.object.parent?.userData.agentId).find(Boolean);
  if (personId) { selectedAgentId = personId; renderWorld(world); }
  pointerDown = null;
});

function eventPayload(kind, point, agentId = null) {
  const location = point ? sceneToWorld(point) : { x: Math.floor(worldWidth / 2), y: Math.floor(worldHeight / 2) };
  return { kind, ...location, ...(agentId ? { target_agent_id: agentId } : {}) };
}
async function triggerEvent(kind, point, agentId) {
  if (!world) return;
  try {
    const body = eventPayload(kind, point, agentId);
    renderWorld(await api("/api/events", { method: "POST", body: JSON.stringify(body) }));
    notify(`${kind.replaceAll("_", " ")} applied near (${body.x}, ${body.y}).`);
  } catch (error) { notify(error.message, true); }
}
for (const tool of document.querySelectorAll(".event-tool")) {
  tool.addEventListener("dragstart", (event) => { dragKind = tool.dataset.event; event.dataTransfer.setData("text/plain", dragKind); sceneHost.classList.add("drag-active"); });
  tool.addEventListener("dragend", () => { dragKind = null; sceneHost.classList.remove("drag-active", "drop-hover"); });
}
sceneHost.addEventListener("dragover", (event) => { event.preventDefault(); sceneHost.classList.add("drop-hover"); });
sceneHost.addEventListener("dragleave", (event) => { if (!sceneHost.contains(event.relatedTarget)) sceneHost.classList.remove("drop-hover"); });
sceneHost.addEventListener("drop", async (event) => {
  event.preventDefault(); sceneHost.classList.remove("drag-active", "drop-hover");
  const kind = event.dataTransfer.getData("text/plain") || dragKind;
  const hit = groundHit(event);
  if (!kind || !hit) return notify("Drop the event over the visible land.", true);
  const agentHit = raycaster.intersectObjects(peopleGroup.children, true).map((item) => item.object.userData.agentId).find(Boolean);
  await triggerEvent(kind, hit, agentHit || null);
});
const dropZone = document.querySelector(".drop-instructions");
dropZone.addEventListener("dragover", (event) => { event.preventDefault(); dropZone.classList.add("drop-hover"); });
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drop-hover"));
dropZone.addEventListener("drop", async (event) => {
  event.preventDefault(); dropZone.classList.remove("drop-hover");
  const kind = event.dataTransfer.getData("text/plain") || dragKind;
  if (kind) await triggerEvent(kind, null);
});

refreshWorld(); refreshModels();
// A short poll keeps the 3D spectators in sync while model calls run in the backend.
setInterval(refreshWorld, 1500);
setInterval(refreshModels, 20000);
