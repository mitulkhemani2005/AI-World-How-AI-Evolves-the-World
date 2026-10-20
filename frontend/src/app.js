import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import "./styles.css";

// The frontend is a spectator only; FastAPI remains the source of world state and rules.
const $ = (selector) => document.querySelector(selector);
const host = $("#world-scene");
const apiBase = import.meta.env.VITE_API_BASE_URL || "";
const ui = { clock: $("#clock-label"), model: $("#model-select"), run: $("#run-button"), step: $("#step-button"), inspector: $("#agent-inspector"), toast: $("#toast") };
const worldWidth = 36;
const worldHeight = 18;
const globeRadius = 10;
let world = null;
let selectedAgentId = null;
let currentWorldId = null;
let isStepping = false;
let draggedEvent = null;
let toastTimeout = null;

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

// Build an open 3D habitat: the mesh is continuous and has no tile borders.
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.7));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.12;
host.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0xf4f5f1);
scene.fog = new THREE.Fog(0xf4f5f1, 34, 82);
// Leave a margin around the complete sphere so the world is not cropped on first load.
const camera = new THREE.PerspectiveCamera(48, 1, 0.1, 120);
camera.position.set(0, 7, 28);
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 0, 0);
controls.enableDamping = true;
controls.dampingFactor = 0.075;
controls.enablePan = true;
controls.panSpeed = 0.45;
controls.minDistance = 11;
controls.maxDistance = 40;
controls.maxPolarAngle = Math.PI;

const skyLight = new THREE.HemisphereLight(0xf4f7ff, 0x66705e, 1.55);
scene.add(skyLight);
const sunlight = new THREE.DirectionalLight(0xffe3bf, 2.5);
sunlight.position.set(-11, 20, 8);
sunlight.castShadow = true;
sunlight.shadow.mapSize.set(2048, 2048);
sunlight.shadow.camera.left = -22; sunlight.shadow.camera.right = 22;
sunlight.shadow.camera.top = 22; sunlight.shadow.camera.bottom = -22;
scene.add(sunlight);
const coolFill = new THREE.DirectionalLight(0x8296a0, 0.38);
coolFill.position.set(8, 8, -12); scene.add(coolFill);

const terrainGroup = new THREE.Group(); scene.add(terrainGroup);
const peopleGroup = new THREE.Group(); scene.add(peopleGroup);
const resourceGroup = new THREE.Group(); scene.add(resourceGroup);
const structureGroup = new THREE.Group(); scene.add(structureGroup);
const animalGroup = new THREE.Group(); scene.add(animalGroup);
const cropGroup = new THREE.Group(); scene.add(cropGroup);
const labels = new Map();
const peopleMeshes = new Map();
const sceneObjects = new Map();
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
let terrainMesh = null;
let terrainWorldId = null;
let terrainCells = new Map();
let pointerDown = null;

function terrainAt(x, y) {
  return terrainCells.get(((x + worldWidth) % worldWidth) + ":" + THREE.MathUtils.clamp(y, 0, worldHeight - 1));
}

function surfaceRadius(cell) {
  if (!cell || cell.kind === "ocean") return globeRadius - 0.08;
  if (cell.kind === "mountain") return globeRadius + 0.55 + Math.max(0, cell.elevation || 0) * 0.65;
  if (cell.kind === "ice") return globeRadius + 0.09;
  return globeRadius + 0.08 + Math.max(0, cell.elevation || 0) * 0.18;
}

function worldToScene(x, y, extraHeight = 0) {
  const longitude = ((x + 0.5) / worldWidth) * Math.PI * 2 - Math.PI;
  const latitude = Math.PI / 2 - ((y + 0.5) / worldHeight) * Math.PI;
  const cell = terrainAt(x, y);
  const radius = surfaceRadius(cell) + extraHeight;
  return new THREE.Vector3(
    radius * Math.cos(latitude) * Math.sin(longitude),
    radius * Math.sin(latitude),
    radius * Math.cos(latitude) * Math.cos(longitude),
  );
}

function orientOnGlobe(group, x, y, extraHeight = 0) {
  const position = worldToScene(x, y, extraHeight);
  const normal = position.clone().normalize();
  group.position.copy(position);
  group.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), normal);
}

function sceneToWorld(point) {
  const normal = point.clone().normalize();
  const longitude = Math.atan2(normal.x, normal.z);
  const latitude = Math.asin(THREE.MathUtils.clamp(normal.y, -1, 1));
  return {
    x: (Math.floor(((longitude + Math.PI) / (Math.PI * 2)) * worldWidth) + worldWidth) % worldWidth,
    y: THREE.MathUtils.clamp(Math.floor(((Math.PI / 2 - latitude) / Math.PI) * worldHeight), 0, worldHeight - 1),
  };
}

function createTerrain(nextWorld = null) {
  // This globe is procedural and fictional; no Earth imagery or geographic map is used.
  if (terrainMesh) {
    terrainMesh.geometry.dispose();
    terrainMesh.material.map?.dispose();
    terrainMesh.material.dispose();
    terrainGroup.remove(terrainMesh);
  }
  for (const child of [...terrainGroup.children]) {
    if (child.userData.isAtmosphere) {
      child.geometry.dispose(); child.material.dispose(); terrainGroup.remove(child);
    }
  }
  const geometry = new THREE.SphereGeometry(globeRadius, 192, 128);
  const positions = geometry.attributes.position;
  if (nextWorld?.terrain?.length) {
    terrainCells = new Map(nextWorld.terrain.map((cell) => [cell.x + ":" + cell.y, cell]));
    const vertex = new THREE.Vector3();
    for (let index = 0; index < positions.count; index += 1) {
      vertex.fromBufferAttribute(positions, index).normalize();
      const longitude = Math.atan2(vertex.x, vertex.z);
      const latitude = Math.asin(THREE.MathUtils.clamp(vertex.y, -1, 1));
      const x = Math.floor(((longitude + Math.PI) / (Math.PI * 2)) * worldWidth) % worldWidth;
      const y = THREE.MathUtils.clamp(Math.floor(((Math.PI / 2 - latitude) / Math.PI) * worldHeight), 0, worldHeight - 1);
      const cell = terrainAt(x, y);
      const radius = surfaceRadius(cell);
      positions.setXYZ(index, vertex.x * radius, vertex.y * radius, vertex.z * radius);
    }
    geometry.computeVertexNormals();
  }

  const canvas = document.createElement("canvas");
  canvas.width = 1024; canvas.height = 512;
  const context = canvas.getContext("2d");
  const colors = {
    // Brighter, higher-contrast biomes remain easy to distinguish against the light UI.
    ocean: "#28658a", plains: "#d0bd82", grassland: "#98ad63", farmland: "#c4ac69",
    forest: "#4d7654", rainforest: "#347954", boreal_forest: "#66866c",
    mountain: "#929790", desert: "#d4ad70", ice: "#d9ecee", river: "#398ca0", lake: "#347d9b",
  };
  context.fillStyle = colors.ocean; context.fillRect(0, 0, canvas.width, canvas.height);
  if (nextWorld?.terrain?.length) {
    const cellWidth = canvas.width / worldWidth; const cellHeight = canvas.height / worldHeight;
    for (const cell of nextWorld.terrain) {
      context.fillStyle = colors[cell.kind] || colors.plains;
      context.fillRect(cell.x * cellWidth, cell.y * cellHeight, Math.ceil(cellWidth + 1), Math.ceil(cellHeight + 1));
    }
    // Gentle texture variation keeps the globe natural while retaining clear biome colors.
    context.fillStyle = "rgba(225,225,210,0.035)";
    for (let x = 0; x < canvas.width; x += 5) {
      const y = (Math.sin(x * 0.045) * 0.5 + 0.5) * canvas.height;
      context.fillRect(x, y, 2, 2);
    }
  }
  const biomeTexture = new THREE.CanvasTexture(canvas);
  biomeTexture.colorSpace = THREE.SRGBColorSpace;
  biomeTexture.anisotropy = renderer.capabilities.getMaxAnisotropy();
  const material = new THREE.MeshStandardMaterial({ map: biomeTexture, color: 0xffffff, roughness: 0.96, metalness: 0.01 });
  terrainMesh = new THREE.Mesh(geometry, material);
  terrainMesh.receiveShadow = true;
  terrainMesh.userData.isLand = true;
  terrainGroup.add(terrainMesh);

  // A subtle atmospheric rim distinguishes the spherical world from its dark backdrop.
  const atmosphere = new THREE.Mesh(
    new THREE.SphereGeometry(globeRadius + 0.16, 96, 64),
    new THREE.MeshBasicMaterial({ color: 0x628c9c, transparent: true, opacity: 0.075, side: THREE.BackSide }),
  );
  atmosphere.userData.isAtmosphere = true;
  terrainGroup.add(atmosphere);
  terrainWorldId = nextWorld?.id || null;
}

function addTree(x, z, scale = 1) {
  const group = new THREE.Group();
  const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.11, 0.16, 0.82, 7), new THREE.MeshStandardMaterial({ color: 0x73543b, roughness: 1 }));
  trunk.position.y = 0.41;
  const foliage = new THREE.Mesh(new THREE.IcosahedronGeometry(0.59, 1), new THREE.MeshStandardMaterial({ color: 0x536d48, roughness: 1, flatShading: true }));
  foliage.position.y = 1.03; foliage.scale.set(0.91, 1.2, 0.88);
  group.add(trunk, foliage);
  group.scale.setScalar(scale);
  orientOnGlobe(group, x, z);
  group.traverse((part) => { if (part.isMesh) { part.castShadow = true; part.receiveShadow = true; } });
  resourceGroup.add(group);
}

function seedScenery() {
  // Seed forest scenery from the saved biome map; this stays consistent across refreshes.
  let seed = 31;
  const random = () => { seed = (seed * 1664525 + 1013904223) % 4294967296; return seed / 4294967296; };
  const woodland = world?.terrain?.filter((cell) => ["forest", "rainforest", "boreal_forest"].includes(cell.kind)) || [];
  for (const cell of woodland) {
    if (random() < 0.5) addTree(cell.x, cell.y, 0.48 + random() * 0.32);
  }
}

function makeHumanoid(agent) {
  // A small articulated body reads as a person at landscape zoom and remains directly clickable.
  const root = new THREE.Group();
  root.userData.agentId = agent.id;
  const skin = new THREE.MeshStandardMaterial({ color: agent.sex === "female" ? 0xc99d75 : 0xb88963, roughness: 0.91 });
  const cloth = new THREE.MeshStandardMaterial({ color: agent.sex === "female" ? 0x9d7060 : 0x71805c, roughness: 1, flatShading: true });
  const darkCloth = new THREE.MeshStandardMaterial({ color: 0x383b32, roughness: 1 });
  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.17, 0.32, 4, 7), cloth);
  body.position.y = 0.73;
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.13, 12, 10), skin);
  head.position.y = 1.13;
  const hair = new THREE.Mesh(new THREE.SphereGeometry(0.135, 12, 8, 0, Math.PI * 2, 0, Math.PI * 0.59), darkCloth);
  hair.position.y = 1.16;
  root.add(body, head, hair);
  const limbs = [];
  for (const side of [-1, 1]) {
    const arm = new THREE.Mesh(new THREE.CapsuleGeometry(0.047, 0.25, 3, 6), skin);
    arm.position.set(side * 0.19, 0.73, 0);
    arm.userData.swingPhase = side < 0 ? 0 : Math.PI;
    root.add(arm); limbs.push(arm);
    const leg = new THREE.Mesh(new THREE.CapsuleGeometry(0.058, 0.27, 3, 6), darkCloth);
    leg.position.set(side * 0.073, 0.32, 0);
    leg.userData.swingPhase = side < 0 ? Math.PI : 0;
    root.add(leg); limbs.push(leg);
  }
  const groundMarker = new THREE.Mesh(new THREE.TorusGeometry(0.28, 0.025, 5, 28), new THREE.MeshBasicMaterial({ color: 0x315f43, transparent: true, opacity: 0.9 }));
  groundMarker.rotation.x = Math.PI / 2;
  groundMarker.position.y = 0.045;
  root.add(groundMarker);
  const selectionRing = new THREE.Mesh(new THREE.RingGeometry(0.34, 0.4, 28), new THREE.MeshBasicMaterial({ color: 0x315f43, side: THREE.DoubleSide, transparent: true, opacity: 0.92 }));
  selectionRing.rotation.x = -Math.PI / 2;
  selectionRing.position.y = 0.025;
  selectionRing.visible = agent.id === selectedAgentId;
  root.add(selectionRing);
  root.userData.limbs = limbs; root.userData.selectionRing = selectionRing;
  root.userData.bodyMeshes = [body, head, hair, ...limbs];
  root.scale.setScalar(1.35);
  root.traverse((part) => { if (part.isMesh) { part.castShadow = true; part.receiveShadow = true; part.userData.agentId = agent.id; } });
  const label = document.createElement("div");
  label.className = "scene-label"; label.dataset.agentId = agent.id;
  host.appendChild(label); labels.set(agent.id, label);
  peopleGroup.add(root); peopleMeshes.set(agent.id, root);
  return root;
}

function makeAnimal(animal) {
  // Compact articulated animal models are attached to the globe's local surface normal.
  const root = new THREE.Group();
  root.userData.animalId = animal.id;
  const furColors = { deer: 0x9a754f, antelope: 0xa48254, goat: 0xc1b59b, boar: 0x5f5147, chicken: 0xc58c55, hare: 0x9c9585, dog: 0x95745d, small_game: 0x837557 };
  const fur = new THREE.MeshStandardMaterial({ color: furColors[animal.species] || 0x95816c, roughness: 1 });
  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.11, 0.25, 3, 6), fur);
  body.rotation.z = Math.PI / 2; body.position.y = 0.31;
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.09, 9, 7), fur);
  head.position.set(0, 0.34, 0.22);
  root.add(body, head);
  for (const side of [-1, 1]) for (const forward of [-1, 1]) {
    const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.03, 0.2, 5), fur);
    leg.position.set(side * 0.07, 0.13, forward * 0.11);
    root.add(leg);
  }
  root.scale.setScalar(["small_game", "hare", "chicken"].includes(animal.species) ? 0.72 : 1);
  root.traverse((part) => { if (part.isMesh) { part.castShadow = true; part.userData.animalId = animal.id; } });
  animalGroup.add(root);
  sceneObjects.set("animal-" + animal.id, root);
  return root;
}

function createCrop(plot) {
  const group = new THREE.Group();
  group.userData.cropId = plot.id;
  orientOnGlobe(group, plot.x, plot.y, 0.015);
  const soil = new THREE.Mesh(new THREE.CircleGeometry(0.28, 12), new THREE.MeshStandardMaterial({ color: 0x5d5035, roughness: 1 }));
  soil.rotation.x = -Math.PI / 2; soil.position.y = 0.02; group.add(soil);
  const leaves = new THREE.MeshStandardMaterial({ color: plot.condition < 30 ? 0x806c46 : plot.crop_kind === "fruit" ? 0x6c9b52 : 0x9cae52, roughness: 0.9 });
  for (let index = 0; index < 4; index += 1) {
    const stem = new THREE.Mesh(new THREE.ConeGeometry(0.045, 0.24 + Math.min(0.15, plot.growth_days / 100), 5), leaves);
    const angle = index * Math.PI / 2;
    stem.position.set(Math.cos(angle) * 0.12, 0.15, Math.sin(angle) * 0.12);
    group.add(stem);
  }
  group.traverse((part) => { if (part.isMesh) part.castShadow = true; });
  cropGroup.add(group); sceneObjects.set("crop-" + plot.id, group);
}

function createResource(node) {
  const group = new THREE.Group();
  orientOnGlobe(group, node.x, node.y);
  const size = Math.max(0.5, Math.min(1.2, node.quantity / 18));
  if (["food", "fruit", "vegetable"].includes(node.kind)) {
    const bush = new THREE.Mesh(new THREE.IcosahedronGeometry(0.25 * size, 1), new THREE.MeshStandardMaterial({ color: node.kind === "vegetable" ? 0x91a955 : 0x759856, roughness: 1, flatShading: true }));
    bush.position.y = 0.2; group.add(bush);
    for (let berry = 0; berry < 3; berry += 1) {
      const fruit = new THREE.Mesh(new THREE.SphereGeometry(0.055, 7, 6), new THREE.MeshStandardMaterial({ color: node.kind === "vegetable" ? 0xa2ae62 : 0xc97a57 }));
      fruit.position.set((berry - 1) * 0.12, 0.28 + (berry % 2) * 0.07, 0.14); group.add(fruit);
    }
  } else if (node.kind === "wood") {
    const stump = new THREE.Mesh(new THREE.CylinderGeometry(0.11, 0.16, 0.63 * size, 7), new THREE.MeshStandardMaterial({ color: 0x76583c, roughness: 1 }));
    stump.position.y = 0.32; group.add(stump);
    const crown = new THREE.Mesh(new THREE.IcosahedronGeometry(0.38 * size, 1), new THREE.MeshStandardMaterial({ color: 0x4f6846, roughness: 1, flatShading: true }));
    crown.position.y = 0.72; group.add(crown);
  } else {
    const edible = ["meat", "cooked_meat", "eggs", "milk"].includes(node.kind);
    const geometry = node.kind === "water" ? new THREE.CylinderGeometry(0.38, 0.48, 0.055, 20) : new THREE.DodecahedronGeometry(0.25 * size, 0);
    const edibleColors = { meat: 0x9a5148, cooked_meat: 0x9c704b, eggs: 0xe0d4aa, milk: 0xc7d3ca };
    const material = new THREE.MeshStandardMaterial({ color: node.kind === "water" ? (node.contamination > 15 ? 0x795766 : 0x4c8794) : edible ? edibleColors[node.kind] : 0x929590, roughness: 0.8, transparent: node.kind === "water", opacity: 0.84, flatShading: true });
    const marker = new THREE.Mesh(geometry, material); marker.position.y = node.kind === "water" ? 0.04 : 0.2; group.add(marker);
  }
  group.traverse((part) => { if (part.isMesh) { part.castShadow = true; part.receiveShadow = true; } });
  resourceGroup.add(group);
  sceneObjects.set(`resource-${node.kind}-${node.x}-${node.y}`, group);
}

function createStructure(building) {
  const group = new THREE.Group();
  const wood = new THREE.MeshStandardMaterial({ color: 0x947652, roughness: 1 });
  const roof = new THREE.MeshStandardMaterial({ color: 0x534a3d, roughness: 1, flatShading: true });
  orientOnGlobe(group, building.x, building.y);
  const scale = building.kind === "communal_house" ? 1.14 : 0.8;
  if (building.kind === "campfire") {
    const stones = new THREE.Mesh(new THREE.TorusGeometry(0.25, 0.08, 5, 12), new THREE.MeshStandardMaterial({ color: 0x77716a, roughness: 1 }));
    stones.rotation.x = Math.PI / 2; stones.position.y = 0.08;
    const flame = new THREE.Mesh(new THREE.ConeGeometry(0.13, 0.36, 6), new THREE.MeshStandardMaterial({ color: 0xd88943, emissive: 0x9a4014, emissiveIntensity: 0.5 }));
    flame.position.y = 0.26; group.add(stones, flame);
  } else if (building.kind === "farm") {
    const plot = new THREE.Mesh(new THREE.BoxGeometry(1.05, 0.1, 0.86), new THREE.MeshStandardMaterial({ color: 0x564832, roughness: 1 }));
    plot.position.y = 0.06; group.add(plot);
    const crops = new THREE.MeshStandardMaterial({ color: 0x86a55b, roughness: 1 });
    for (let row = 0; row < 3; row += 1) for (let stem = 0; stem < 4; stem += 1) {
      const plant = new THREE.Mesh(new THREE.ConeGeometry(0.07, 0.23, 5), crops);
      plant.position.set(-0.34 + stem * 0.23, 0.18, -0.26 + row * 0.26); group.add(plant);
    }
  } else if (building.kind === "shrine") {
    const altar = new THREE.Mesh(new THREE.CylinderGeometry(0.31, 0.38, 0.27, 8), roof);
    altar.position.y = 0.14; group.add(altar);
    for (let index = 0; index < 4; index += 1) {
      const angle = index * Math.PI / 2;
      const pillar = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.09, 0.7, 6), wood);
      pillar.position.set(Math.cos(angle) * 0.43, 0.36, Math.sin(angle) * 0.43); group.add(pillar);
    }
  } else {
    const hut = new THREE.Mesh(new THREE.BoxGeometry(scale, 0.72 * scale, scale), wood);
    hut.position.y = 0.38 * scale;
    const cap = new THREE.Mesh(new THREE.ConeGeometry(scale * 0.75, scale * 0.66, 4), roof);
    cap.position.y = 0.96 * scale; cap.rotation.y = Math.PI / 4;
    group.add(hut, cap);
  }
  group.traverse((part) => { if (part.isMesh) { part.castShadow = true; part.receiveShadow = true; } });
  structureGroup.add(group); sceneObjects.set(`structure-${building.id}`, group);
}

createTerrain();
seedScenery();

function resizeScene() {
  const width = Math.max(host.clientWidth, 1); const height = Math.max(host.clientHeight, 1);
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}
new ResizeObserver(resizeScene).observe(host);
resizeScene();

function syncObjects(nextWorld) {
  if (terrainWorldId !== nextWorld.id) createTerrain(nextWorld);
  if (currentWorldId !== nextWorld.id) {
    currentWorldId = nextWorld.id; selectedAgentId = null;
    for (const label of labels.values()) label.remove();
    labels.clear(); peopleMeshes.clear(); sceneObjects.clear();
    peopleGroup.clear(); resourceGroup.clear(); structureGroup.clear(); animalGroup.clear(); cropGroup.clear();
    seedScenery();
  }
  const liveIds = new Set(nextWorld.agents.map((agent) => agent.id));
  for (const [id, label] of labels) if (!liveIds.has(id)) { label.remove(); labels.delete(id); peopleMeshes.delete(id); }
  for (const agent of nextWorld.agents) {
    let figure = peopleMeshes.get(agent.id);
    if (!figure) {
      figure = makeHumanoid(agent);
      orientOnGlobe(figure, agent.x, agent.y, 0.28);
    }
    const destination = worldToScene(agent.x, agent.y, 0.28);
    if (!figure.userData.destination || figure.userData.destination.distanceTo(destination) > 0.04) {
      figure.userData.travelStart = figure.position.clone();
      figure.userData.travelStartedAt = performance.now();
      figure.userData.destination = destination;
    }
    figure.userData.moving = agent.last_action?.action === "move" && agent.alive;
    figure.userData.working = agent.alive && !["move", "rest", "drink", "bond", "reproduce"].includes(agent.last_action?.action);
    figure.userData.dead = !agent.alive;
    figure.userData.buried = agent.buried;
    figure.visible = !agent.buried;
    if (!agent.alive && !figure.userData.deathPoseApplied) {
      // Dead bodies remain visible on the surface until someone chooses to bury them.
      figure.quaternion.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), Math.PI / 2));
      figure.userData.deathPoseApplied = true;
      figure.userData.bodyMeshes.forEach((part) => part.material.color.set(0x77736d));
    }
    if (agent.buried && !figure.userData.graveMarker) {
      const grave = new THREE.Group();
      const stone = new THREE.Mesh(new THREE.BoxGeometry(0.28, 0.48, 0.14), new THREE.MeshStandardMaterial({ color: 0x777e7a, roughness: 0.95 }));
      stone.position.y = 0.25; grave.add(stone);
      const inscription = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.045, 0.16), new THREE.MeshStandardMaterial({ color: 0xb6b8ac }));
      inscription.position.y = 0.37; grave.add(inscription);
      orientOnGlobe(grave, agent.x, agent.y, 0.05);
      grave.traverse((part) => { if (part.isMesh) part.castShadow = true; });
      peopleGroup.add(grave); figure.userData.graveMarker = grave;
    }
    figure.userData.selectionRing.visible = agent.alive && agent.id === selectedAgentId;
    const label = labels.get(agent.id);
    const action = agent.last_action?.action?.replaceAll("_", " ");
    label.textContent = agent.alive
      ? `${agent.name} · ${action || "observing"}`
      : agent.buried ? `${agent.name} · buried` : `${agent.name} · deceased`;
    label.classList.toggle("selected", agent.id === selectedAgentId);
    label.classList.toggle("dead", !agent.alive);
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
  const desiredAnimals = new Set();
  for (const animal of nextWorld.animals || []) {
    if (!animal.alive) continue;
    const key = "animal-" + animal.id; desiredAnimals.add(key);
    let animalFigure = sceneObjects.get(key);
    if (!animalFigure) animalFigure = makeAnimal(animal);
    const animalDestination = worldToScene(animal.x, animal.y, 0.02);
    if (!animalFigure.userData.destination || animalFigure.userData.destination.distanceTo(animalDestination) > 0.04) {
      animalFigure.userData.travelStart = animalFigure.position.clone();
      animalFigure.userData.travelStartedAt = performance.now();
      animalFigure.userData.destination = animalDestination;
    }
    animalFigure.userData.animalType = animal.animal_type;
    animalFigure.userData.owner = animal.owner_agent_id;
  }
  const desiredCrops = new Set();
  for (const plot of nextWorld.crops || []) {
    const key = "crop-" + plot.id; desiredCrops.add(key);
    if (!sceneObjects.has(key)) createCrop(plot);
  }
  for (const [key, object] of sceneObjects) {
    if ((key.startsWith("resource-") && !desiredResources.has(key))
      || (key.startsWith("structure-") && !desiredStructures.has(key))
      || (key.startsWith("animal-") && !desiredAnimals.has(key))
      || (key.startsWith("crop-") && !desiredCrops.has(key))) {
      object.removeFromParent(); sceneObjects.delete(key);
    }
  }
}

function renderLabels() {
  const projected = new THREE.Vector3();
  for (const [id, figure] of peopleMeshes) {
    const label = labels.get(id);
    projected.copy(figure.position).add(figure.position.clone().normalize().multiplyScalar(1.85)).project(camera);
    const x = (projected.x * 0.5 + 0.5) * host.clientWidth;
    const y = (-projected.y * 0.5 + 0.5) * host.clientHeight;
    label.style.transform = `translate(${x}px,${y}px) translate(-50%,-100%)`;
    const frontFacing = figure.position.dot(camera.position) > 0;
    label.style.display = !figure.userData.buried && frontFacing && projected.z < 1 && figure.position.clone().sub(camera.position).length() < 55 ? "block" : "none";
  }
}

function frame(now) {
  requestAnimationFrame(frame);
  controls.update();
  for (const figure of peopleMeshes.values()) {
    const destination = figure.userData.destination;
    if (!destination) continue;
    // Smoothstep along the globe surface keeps each person grounded during travel.
    const start = figure.userData.travelStart || destination;
    const rawProgress = THREE.MathUtils.clamp((now - (figure.userData.travelStartedAt || now)) / 1050, 0, 1);
    const progress = rawProgress * rawProgress * (3 - 2 * rawProgress);
    const direction = start.clone().normalize().slerp(destination.clone().normalize(), progress).normalize();
    const radius = THREE.MathUtils.lerp(start.length(), destination.length(), progress) + Math.sin(progress * Math.PI) * 0.08;
    figure.position.copy(direction.multiplyScalar(radius));
    if (!figure.userData.dead) figure.quaternion.slerp(new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), figure.position.clone().normalize()), 0.16);
    const moving = !figure.userData.dead && figure.userData.moving && figure.position.distanceTo(destination) > 0.13;
    const working = !figure.userData.dead && figure.userData.working;
    figure.userData.limbs.forEach((limb, index) => {
      const armAtWork = working && index < 2;
      limb.rotation.x = moving ? Math.sin(now * 0.007 + limb.userData.swingPhase) * 0.48
        : armAtWork ? Math.sin(now * 0.005 + limb.userData.swingPhase) * 0.22
          : THREE.MathUtils.damp(limb.rotation.x, 0, 5, 1 / 60);
    });
    if (moving) figure.rotation.y += Math.sin(now * 0.001) * 0.002;
    figure.userData.selectionRing.rotation.z = now * 0.00045;
  }
  for (const [key, animal] of sceneObjects) {
    if (!key.startsWith("animal-") || !animal.userData.destination) continue;
    const start = animal.userData.travelStart || animal.userData.destination;
    const progress = THREE.MathUtils.clamp((now - (animal.userData.travelStartedAt || now)) / 1300, 0, 1);
    const eased = progress * progress * (3 - 2 * progress);
    const direction = start.clone().normalize().slerp(animal.userData.destination.clone().normalize(), eased).normalize();
    animal.position.copy(direction.multiplyScalar(THREE.MathUtils.lerp(start.length(), animal.userData.destination.length(), eased)));
    animal.quaternion.slerp(new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), animal.position.clone().normalize()), 0.12);
  }
  updateDaylight();
  renderLabels();
  renderer.render(scene, camera);
}
requestAnimationFrame(frame);

function updateDaylight() {
  // Light follows the spectator's actual local clock, not the simulation's accelerated day.
  const current = new Date();
  const hour = current.getHours() + current.getMinutes() / 60 + current.getSeconds() / 3600;
  const daylight = THREE.MathUtils.clamp((Math.sin(((hour - 6) / 12) * Math.PI) + 0.15) / 1.15, 0, 1);
  // Keep the terrain legible at night instead of rendering it nearly black.
  sunlight.intensity = 0.78 + daylight * 1.45;
  skyLight.intensity = 1.0 + daylight * 0.75;
  const angle = ((hour - 6) / 24) * Math.PI * 2;
  sunlight.position.set(Math.cos(angle) * 18, Math.max(1, Math.sin(((hour - 6) / 12) * Math.PI) * 20), Math.sin(angle) * 18);
}

function statBar(name, value, lowIsBad = false) {
  const level = Number(value || 0);
  const state = lowIsBad ? (level <= 25 ? "danger" : level <= 45 ? "warn" : "") : (level >= 85 ? "danger" : level >= 68 ? "warn" : "");
  return `<div class="stat-row"><div class="stat-top"><span>${name}</span><b>${Math.round(level)}%</b></div><div class="bar ${state}"><i style="width:${THREE.MathUtils.clamp(level, 0, 100)}%"></i></div></div>`;
}

function renderInspector() {
  const agent = world?.agents.find((person) => person.id === selectedAgentId);
  if (!agent) { ui.inspector.classList.remove("visible"); ui.inspector.innerHTML = '<div class="inspector-empty"><span class="eyebrow">LIFE RECORD</span><p>Select a person in the land to see their story.</p></div>'; return; }
  ui.inspector.classList.add("visible");
  if (ui.inspector.contains(document.activeElement)) return;
  const age = agent.age_days < 365 ? `${agent.age_days} days` : `${Math.floor(agent.age_days / 365)} years`;
  const namesFor = (ids) => ids.map((id) => world.agents.find((person) => person.id === id)?.name || "Unknown").join(", ") || "None";
  const partner = world.agents.find((person) => person.id === agent.bonded_partner_id);
  const traits = Object.entries(agent.traits || {}).map(([name, score]) => `${name} ${Math.round(score * 100)}`).join(" · ") || "Not developed";
  const memories = [...(agent.memories || [])].slice(-4).reverse();
  const condition = agent.alive ? (agent.disease ? `Ill · ${agent.disease}` : "Living") : agent.buried ? "Buried" : `Deceased · ${agent.death_cause || "unknown cause"}`;
  const symbol = agent.sex === "female" ? "♀" : "♂";
  ui.inspector.innerHTML = `<div class="inspector-content"><div class="inspector-head"><div class="agent-avatar">${symbol}</div><div><h2>${escapeHtml(agent.name)}</h2><p>${escapeHtml(age)} · ${escapeHtml(agent.sex)}</p></div><button class="close-inspector" aria-label="Close inspector">×</button></div>
    <div class="condition ${agent.alive ? "" : "dead"}">${escapeHtml(condition.toUpperCase())}</div>
    ${statBar("health", agent.health, true)}${statBar("hunger", agent.hunger)}${statBar("thirst", agent.thirst)}${statBar("energy", agent.energy, true)}
    <form class="edit-form" id="edit-agent"><div class="edit-title">SPECTATOR ADJUSTMENT</div><div class="edit-grid">${["health", "hunger", "thirst", "energy"].map((key) => `<div class="edit-field"><label for="edit-${key}">${key}</label><input id="edit-${key}" name="${key}" type="number" min="0" max="100" value="${Math.round(agent[key])}" ${agent.alive ? "" : "disabled"}/></div>`).join("")}</div><button class="small-action" type="submit" ${agent.alive ? "" : "disabled"}>Apply changes</button></form>
    <div class="detail-list"><div class="detail-line"><span>Parents</span><span>${escapeHtml(namesFor(agent.parent_ids || []))}</span></div><div class="detail-line"><span>Children</span><span>${escapeHtml(namesFor(agent.children_ids || []))}</span></div><div class="detail-line"><span>Bond</span><span>${escapeHtml(partner?.name || "None")}</span></div><div class="detail-line"><span>Pregnancy</span><span>${agent.pregnancy_days_remaining == null ? "No" : `${agent.pregnancy_days_remaining} days`}</span></div><div class="detail-line"><span>Knowledge</span><span>${(agent.knowledge || []).length} learned</span></div><div class="detail-line"><span>Temperament</span><span>${escapeHtml(traits)}</span></div><div class="detail-line"><span>Last action</span><span>${escapeHtml(agent.last_action?.action?.replaceAll("_", " ") || "Observing")}</span></div></div>
    <ul class="memories">${memories.length ? memories.map((memory) => `<li>${escapeHtml(memory)}</li>`).join("") : "<li>No memories yet.</li>"}</ul></div>`;
  const biome = terrainAt(agent.x, agent.y);
  const habitat = document.createElement("div");
  habitat.className = "habitat-line";
  habitat.textContent = "Habitat · " + (biome?.kind?.replaceAll("_", " ") || "unknown");
  ui.inspector.querySelector(".condition")?.after(habitat);
  ui.inspector.querySelector(".close-inspector").addEventListener("click", () => { selectedAgentId = null; renderInspector(); syncObjects(world); });
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
  const animals = world?.animals || []; const crops = world?.crops || [];
  $("#culture-count").textContent = String(groups.length + beliefs.length + structures.length + animals.filter((animal) => animal.animal_type !== "wild").length);
  const block = (title, values) => `<div class="culture-block"><h4>${title} · ${values.length}</h4><div class="chip-list">${values.length ? values.map((value) => `<span class="chip">${escapeHtml(value)}</span>`).join("") : '<span class="chip">None yet</span>'}</div></div>`;
  $("#culture-popover").innerHTML = `<h3>World culture</h3>${block("Structures", structures.map((item) => item.kind.replaceAll("_", " ")))}${block("Groups", groups.map((item) => `${item.name} · ${item.kind} · ${item.member_ids.length}`))}${block("Beliefs", beliefs.map((item) => `${item.name} · ${item.kind}`))}`;
  $("#culture-popover").insertAdjacentHTML("beforeend", block("Animals · NPC", animals.filter((item) => item.alive).map((item) => `${item.species} · ${item.animal_type}${item.owner_agent_id ? " · cared for" : ""}`)) + block("Growing crops", crops.map((item) => `${item.crop_kind} · ${item.growth_days} days · ${Math.round(item.moisture)}% moisture`)));
}

function renderWorld(next) {
  world = next;
  const year = Math.floor(world.tick / 365) + 1; const day = (world.tick % 365) + 1;
  const living = world.agents.filter((agent) => agent.alive).length;
  const animalCount = (world.animals || []).filter((animal) => animal.alive).length;
  const localTime = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  ui.clock.textContent = `LOCAL ${localTime} · YEAR ${year} · DAY ${day}${world.processing ? " · THINKING" : ""}`;
  $("#population-label").textContent = String(living);
  $("#age-label").textContent = String(year);
  $("#weather-label").textContent = world.weather || "clear";
  $("#world-summary").textContent = `${living} alive · ${world.agents.length} lives in the world · ${world.season || "spring"}`;
  $("#world-summary").textContent = [living + " people", animalCount + " animals", (world.crops?.length || 0) + " growing crops", world.season || "spring"].join(" · ");
  ui.run.textContent = world.running ? "Ⅱ" : "▶";
  ui.run.title = world.running ? "Pause the simulation" : "Run the simulation";
  syncObjects(world); renderInspector(); renderCulture();
}

async function refreshWorld() {
  try { renderWorld(await api("/api/world")); }
  catch (error) { ui.clock.textContent = "BACKEND UNAVAILABLE"; notify(error.message, true); }
}

async function refreshModels() {
  try {
    const [health, response] = await Promise.all([api("/api/health"), api("/api/models")]);
  const selected = world?.global_model || health.default_model || "qwen2.5:0.5b";
    const options = (response.models || []).map((model) => `<option value="${escapeHtml(model)}">${escapeHtml(model)}</option>`);
    if (!response.models?.includes(selected)) options.unshift(`<option value="${escapeHtml(selected)}">${escapeHtml(selected)} · unavailable</option>`);
    ui.model.innerHTML = options.join("") || `<option value="${escapeHtml(selected)}">${escapeHtml(selected)}</option>`;
    ui.model.value = selected;
    ui.model.title = health.ollama_available ? "One model guides every agent; their memories remain individual." : "Ollama is unavailable. The world can continue with its survival fallback.";
  } catch (error) { ui.model.innerHTML = "<option>Ollama unavailable</option>"; ui.model.title = error.message; }
}

ui.run.addEventListener("click", async () => {
  try {
    if (world?.running) await api("/api/world/pause", { method: "POST" });
    else await api("/api/world/run?interval_seconds=2.5", { method: "POST" });
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

function groundHit(event) {
  castPointer(event);
  const hit = raycaster.intersectObject(terrainMesh, false)[0];
  if (!hit) return null;
  return hit.point;
}

renderer.domElement.addEventListener("pointerdown", (event) => { pointerDown = { x: event.clientX, y: event.clientY }; });
renderer.domElement.addEventListener("pointerup", (event) => {
  if (!pointerDown || Math.hypot(event.clientX - pointerDown.x, event.clientY - pointerDown.y) > 5) { pointerDown = null; return; }
  castPointer(event);
  const hits = raycaster.intersectObjects(peopleGroup.children, true);
  const globeHit = raycaster.intersectObject(terrainMesh, false)[0];
  const visibleHits = hits.filter((hit) => !globeHit || hit.distance < globeHit.distance);
  const agentId = visibleHits.map((hit) => hit.object.userData.agentId || hit.object.parent?.userData.agentId).find(Boolean);
  if (agentId) { selectedAgentId = agentId; renderInspector(); syncObjects(world); }
  pointerDown = null;
});

async function triggerEvent(kind, point) {
  if (!world) return;
  const location = point ? sceneToWorld(point) : { x: Math.floor(world.width / 2), y: Math.floor(world.height / 2) };
  try {
    renderWorld(await api("/api/events", { method: "POST", body: JSON.stringify({ kind, ...location }) }));
    notify(`${kind.replaceAll("_", " ")} introduced near (${location.x}, ${location.y}).`);
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
  const point = groundHit(event);
  if (!kind) return;
  if (!point) return notify("Drop the event on the walkable land.", true);
  await triggerEvent(kind, point);
});

refreshWorld(); refreshModels();
// Polling updates the view without allowing display animation to change simulation state.
setInterval(refreshWorld, 1500);
setInterval(refreshModels, 20000);
