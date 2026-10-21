import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { interpolateSurfacePosition } from "./surface-motion.js";
import { WorldEffects } from "./world-effects.js";
import { describeWorldHit } from "./world-inspection.js";
import "./styles.css";

// The frontend is a spectator only; FastAPI remains the source of world state and rules.
const $ = (selector) => document.querySelector(selector);
const host = $("#world-scene");
const apiBase = import.meta.env.VITE_API_BASE_URL || "";
const ui = { clock: $("#clock-label"), model: $("#model-select"), run: $("#run-button"), step: $("#step-button"), inspector: $("#agent-inspector"), toast: $("#toast") };
let worldWidth = 36;
let worldHeight = 18;
const globeRadius = 10;
let world = null;
let selectedAgentId = null;
let currentWorldId = null;
let isStepping = false;
let draggedEvent = null;
let toastTimeout = null;
let followingAgentId = null;
let hoverPointer = null;
let lastHoverAt = 0;
let terrainHealthSignature = "";
let armedEvent = null;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
}

async function api(path, options = {}) {
  const response = await fetch(`${apiBase}${path}`, { cache: "no-store", signal: AbortSignal.timeout(30000), headers: { "Content-Type": "application/json" }, ...options });
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
let fallbackContext = null;
let fallbackPixelRatio = 1;
let renderer;
try {
  // Prefer the full 3D scene, but do not let a blocked WebGL context disable the whole frontend.
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.7));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.12;
  host.appendChild(renderer.domElement);
} catch (error) {
  // A 2D globe fallback keeps terrain, people, and controls visible on systems without WebGL.
  console.error("WebGL initialization failed; using the compatibility globe.", error);
  const canvas = document.createElement("canvas");
  canvas.setAttribute("aria-label", "Compatibility view of the simulated world");
  canvas.style.width = "100%";
  canvas.style.height = "100%";
  host.appendChild(canvas);
  fallbackContext = canvas.getContext("2d");
  if (!fallbackContext) throw error;
  renderer = {
    domElement: canvas,
    shadowMap: { enabled: false, type: null },
    capabilities: { getMaxAnisotropy: () => 1 },
    setPixelRatio(value) { fallbackPixelRatio = value; },
    setSize(width, height) {
      canvas.width = Math.max(1, Math.round(width * fallbackPixelRatio));
      canvas.height = Math.max(1, Math.round(height * fallbackPixelRatio));
      fallbackContext.setTransform(fallbackPixelRatio, 0, 0, fallbackPixelRatio, 0, 0);
    },
    render() { drawCompatibilityGlobe(); },
  };
  notify("Using compatibility globe because WebGL is unavailable.", true);
}

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
controls.enableZoom = true;
controls.zoomSpeed = 0.8;
controls.enablePan = false;
controls.panSpeed = 0.45;
controls.minDistance = 11;
controls.maxDistance = 40;
controls.minPolarAngle = 0.06;
controls.maxPolarAngle = Math.PI - 0.06;

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
const itemGroup = new THREE.Group(); scene.add(itemGroup);
let deathWorldId = null;
const reportedDeaths = new Set();
const worldEffects = new WorldEffects(scene, worldToScene);
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

function compatibilityFrame() {
  const direction = camera.position.clone().normalize();
  const pole = Math.abs(direction.y) > 0.98 ? new THREE.Vector3(0, 0, 1) : new THREE.Vector3(0, 1, 0);
  const right = new THREE.Vector3().crossVectors(pole, direction).normalize();
  return { direction, right, up: new THREE.Vector3().crossVectors(direction, right).normalize(),
    radius: Math.max(40, Math.min(host.clientWidth * 0.45, host.clientHeight * 0.39) * (29 / camera.position.length())) };
}

function drawCompatibilityGlobe() {
  if (!fallbackContext) return;
  const context = fallbackContext;
  const width = host.clientWidth;
  const height = host.clientHeight;
  const centerX = width / 2;
  const centerY = height / 2;
  const { radius, direction: cameraDirection, right, up } = compatibilityFrame();
  context.clearRect(0, 0, width, height);
  context.fillStyle = "#f4f5f1";
  context.fillRect(0, 0, width, height);

  const sphere = context.createRadialGradient(centerX - radius * 0.35, centerY - radius * 0.4, radius * 0.08, centerX, centerY, radius);
  sphere.addColorStop(0, "#6ea7c1");
  sphere.addColorStop(0.72, "#28658a");
  sphere.addColorStop(1, "#17445f");
  context.beginPath();
  context.arc(centerX, centerY, radius, 0, Math.PI * 2);
  context.fillStyle = sphere;
  context.fill();
  context.save();
  context.beginPath();
  context.arc(centerX, centerY, radius, 0, Math.PI * 2);
  context.clip();

  const colors = {
    plains: "#d0bd82", grassland: "#98ad63", farmland: "#c4ac69", forest: "#4d7654",
    rainforest: "#347954", boreal_forest: "#66866c", mountain: "#929790", desert: "#d4ad70",
    ice: "#d9ecee", river: "#398ca0", lake: "#347d9b",
  };
  if (world?.terrain?.length) {
    for (const cell of world.terrain) {
      const color = colors[cell.kind];
      if (!color) continue;
      const normal = worldToScene(cell.x, cell.y).normalize();
      const facing = normal.dot(cameraDirection);
      if (facing <= 0) continue;
      const x = centerX + normal.dot(right) * radius;
      const y = centerY - normal.dot(up) * radius;
      // Slightly overlap round biome marks to suggest continuous land without tile borders.
      context.beginPath();
      context.arc(x, y, radius * 0.105, 0, Math.PI * 2);
      context.globalAlpha = THREE.MathUtils.clamp(0.72 + facing * 0.28, 0, 1);
      context.fillStyle = color;
      context.fill();
    }
  }
  context.globalAlpha = 1;

  for (const agent of world?.agents || []) {
    const normal = worldToScene(agent.x, agent.y).normalize();
    if (normal.dot(cameraDirection) <= 0) continue;
    const x = centerX + normal.dot(right) * radius;
    const y = centerY - normal.dot(up) * radius;
    context.beginPath();
    context.arc(x, y, agent.alive ? 7 : 5, 0, Math.PI * 2);
    context.fillStyle = agent.alive ? (agent.sex === "female" ? "#a65e47" : "#476d49") : "#77736d";
    context.fill();
    context.strokeStyle = "#ffffff";
    context.lineWidth = 2;
    context.stroke();
    context.font = "12px sans-serif";
    context.fillStyle = "#26352b";
    context.fillText(agent.name, x + 9, y - 8);
  }
  for (const animal of world?.animals || []) {
    if (!animal.alive) continue;
    const normal = worldToScene(animal.x, animal.y).normalize();
    if (normal.dot(cameraDirection) <= 0) continue;
    const x = centerX + normal.dot(right) * radius;
    const y = centerY - normal.dot(up) * radius;
    context.beginPath();
    context.arc(x, y, 2.5, 0, Math.PI * 2);
    context.fillStyle = animal.animal_type === "wild" ? "#815b42" : "#b47b48";
    context.fill();
  }
  // Compatibility mode also visualizes interventions without touching the simulation clock.
  for (const item of world?.items || []) {
    if (item.holder_agent_id && item.kind !== "raft") continue;
    const normal = worldToScene(item.x, item.y).normalize();
    if (normal.dot(cameraDirection) <= 0) continue;
    const x = centerX + normal.dot(right) * radius, y = centerY - normal.dot(up) * radius;
    context.fillStyle = "#92714d";
    context.fillRect(x - 5, y - 3, item.kind === "raft" ? 12 : 3, item.kind === "raft" ? 6 : 10);
  }
  for (const effect of worldEffects.active.values()) {
    const normal = effect.group.position.clone().normalize();
    if (normal.dot(cameraDirection) <= 0) continue;
    const x = centerX + normal.dot(right) * radius, y = centerY - normal.dot(up) * radius;
    context.beginPath();
    context.arc(x, y, Math.max(8, effect.ring.scale.x * radius * 0.025), 0, Math.PI * 2);
    context.strokeStyle = `#${effect.material.color.getHexString()}`;
    context.globalAlpha = effect.material.opacity;
    context.lineWidth = 4;
    context.stroke();
    context.fillStyle = context.strokeStyle;
    context.font = "bold 12px sans-serif";
    context.fillText(effect.kind.replaceAll("_", " "), x + 12, y - 12);
  }
  context.globalAlpha = 1;
  context.restore();
  context.beginPath();
  context.arc(centerX, centerY, radius, 0, Math.PI * 2);
  context.strokeStyle = "rgba(57, 94, 79, .38)";
  context.lineWidth = 1.5;
  context.stroke();
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
  // Align the texture's longitude zero with worldToScene, not Three.js's default sphere seam.
  geometry.rotateY(-Math.PI / 2);
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
  // Use an unlit biome texture so terrain cannot disappear when local night lighting is weak.
  const material = new THREE.MeshBasicMaterial({ map: biomeTexture, color: 0xffffff });
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
  group.userData.isLand = true;
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
    arm.userData.isArm = true;
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
  const legs = [];
  for (const side of [-1, 1]) for (const forward of [-1, 1]) {
    const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.03, 0.2, 5), fur);
    leg.position.set(side * 0.07, 0.13, forward * 0.11);
    root.add(leg);
    leg.userData.phase = side * forward > 0 ? 0 : Math.PI;
    legs.push(leg);
  }
  if (["deer", "antelope", "goat"].includes(animal.species)) {
    for (const side of [-1, 1]) {
      const horn = new THREE.Mesh(new THREE.ConeGeometry(0.035, animal.species === "deer" ? 0.3 : 0.18, 5), fur);
      horn.position.set(side * 0.06, 0.49, 0.22); horn.rotation.z = side * 0.25; root.add(horn);
    }
  }
  if (["hare", "dog"].includes(animal.species)) {
    for (const side of [-1, 1]) {
      const ear = new THREE.Mesh(new THREE.CapsuleGeometry(0.025, animal.species === "hare" ? 0.2 : 0.06, 3, 5), fur);
      ear.position.set(side * 0.055, 0.47, 0.22); root.add(ear);
    }
  }
  if (animal.species === "chicken") {
    const beak = new THREE.Mesh(new THREE.ConeGeometry(0.04, 0.12, 4), new THREE.MeshBasicMaterial({ color: 0xe7a43d }));
    beak.rotation.x = Math.PI / 2; beak.position.set(0, 0.35, 0.33); root.add(beak);
  }
  const marker = new THREE.Mesh(new THREE.RingGeometry(0.20, 0.25, 24), new THREE.MeshBasicMaterial({ color: 0x997034, transparent: true, opacity: 0.7, side: THREE.DoubleSide }));
  marker.rotation.x = -Math.PI / 2; marker.position.y = 0.02; root.add(marker);
  root.userData.legs = legs;
  root.scale.setScalar(["small_game", "hare", "chicken"].includes(animal.species) ? 0.4 : 0.65);
  orientOnGlobe(root, animal.x, animal.y, 0.02);
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

function itemShape(item) {
  const group = new THREE.Group();
  group.userData.itemId = item.id;
  const wood = new THREE.MeshStandardMaterial({ color: 0x92714d, roughness: 1 });
  if (item.kind === "raft") {
    for (let index = 0; index < 5; index++) {
      const log = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.1, 1.6, 7), wood);
      log.rotation.x = Math.PI / 2; log.position.x = (index - 2) * 0.18; group.add(log);
    }
    for (const side of [-1, 1]) {
      const beam = new THREE.Mesh(new THREE.BoxGeometry(1.05, 0.07, 0.09), wood);
      beam.position.set(0, 0.08, side * 0.5); group.add(beam);
    }
  } else {
    const handle = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.03, 0.95, 6), wood);
    handle.position.y = 0.45; group.add(handle);
    const tip = new THREE.Mesh(item.kind === "stone_axe" ? new THREE.BoxGeometry(0.25, 0.18, 0.08)
      : new THREE.ConeGeometry(0.065, 0.22, 5), new THREE.MeshStandardMaterial({ color: 0x727a79, roughness: 1 }));
    tip.position.y = 0.94; group.add(tip);
  }
  return group;
}

function createResource(node) {
  const group = new THREE.Group();
  group.userData.resource = { kind: node.kind, x: node.x, y: node.y };
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
  group.userData.structureId = building.id;
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

function updateTerrainHealth(nextWorld) {
  const signature = nextWorld.id + (nextWorld.terrain || []).map((cell) => `${Math.round(cell.condition ?? 100)}:${Math.round(cell.pollution || 0)}`).join(",");
  if (signature === terrainHealthSignature || !terrainMesh) return;
  terrainHealthSignature = signature;
  const positions = terrainMesh.geometry.attributes.position;
  let colors = terrainMesh.geometry.attributes.color;
  if (!colors) {
    colors = new THREE.BufferAttribute(new Float32Array(positions.count * 3), 3);
    terrainMesh.geometry.setAttribute("color", colors);
    terrainMesh.material.vertexColors = true;
    terrainMesh.material.needsUpdate = true;
  }
  const point = new THREE.Vector3();
  for (let index = 0; index < positions.count; index++) {
    point.fromBufferAttribute(positions, index);
    const location = sceneToWorld(point);
    const cell = terrainAt(location.x, location.y);
    const damage = THREE.MathUtils.clamp((100 - (cell?.condition ?? 100)) / 100 + (cell?.pollution || 0) / 200, 0, 1);
    colors.setXYZ(index, 1 - damage * 0.25, 1 - damage * 0.48, 1 - damage * 0.50);
  }
  colors.needsUpdate = true;
}

function resizeScene() {
  const width = Math.max(host.clientWidth, 1); const height = Math.max(host.clientHeight, 1);
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  camera.updateMatrixWorld(true);
  camera.matrixWorldInverse.copy(camera.matrixWorld).invert();
}
new ResizeObserver(resizeScene).observe(host);
resizeScene();

function showWholeWorld() {
  followingAgentId = null;
  controls.target.set(0, 0, 0);
  controls.minDistance = 12;
  controls.maxDistance = 55;
  camera.position.set(0, 7, 28);
  controls.update();
}

function focusPopulation(nextWorld = world) {
  const person = nextWorld?.agents.find((agent) => agent.id === selectedAgentId)
    || nextWorld?.agents.find((agent) => agent.alive);
  if (!person || fallbackContext) return showWholeWorld();
  followingAgentId = person.id;
  const position = worldToScene(person.x, person.y, 0.5);
  const normal = position.clone().normalize();
  // Start near the living settlement so people and their work are large enough to inspect.
  controls.target.copy(position);
  controls.minDistance = 3;
  controls.maxDistance = 40;
  const tangentUp = new THREE.Vector3(0, 1, 0).addScaledVector(normal, -normal.y);
  if (tangentUp.lengthSq() < 0.001) tangentUp.set(1, 0, 0);
  camera.position.copy(position).addScaledVector(normal, 10).addScaledVector(tangentUp.normalize(), 4);
  controls.update();
}

function zoomView(factor) {
  const offset = camera.position.clone().sub(controls.target);
  const distance = THREE.MathUtils.clamp(offset.length() * factor, controls.minDistance, controls.maxDistance);
  camera.position.copy(controls.target).add(offset.normalize().multiplyScalar(distance));
  controls.update();
  constrainCamera();
}

function constrainCamera() {
  if (followingAgentId && controls.target.length() > globeRadius * 0.8) {
    const normal = controls.target.clone().normalize();
    const offset = camera.position.clone().sub(controls.target);
    const outward = offset.dot(normal);
    if (outward < 2) camera.position.addScaledVector(normal, 2 - outward);
  }
  const direction = camera.position.clone().normalize();
  if (direction.lengthSq() === 0) direction.set(0, 0, 1);
  const location = sceneToWorld(direction);
  const clearance = surfaceRadius(terrainAt(location.x, location.y)) + 1.3;
  if (camera.position.length() < clearance) camera.position.copy(direction.multiplyScalar(clearance));
  camera.lookAt(controls.target);
}
$("#view-world").addEventListener("click", showWholeWorld);
$("#view-people").addEventListener("click", () => focusPopulation());
$("#zoom-in").addEventListener("click", () => zoomView(0.8));
$("#zoom-out").addEventListener("click", () => zoomView(1.25));

function syncObjects(nextWorld) {
  worldWidth = nextWorld.width;
  worldHeight = nextWorld.height;
  terrainCells = new Map((nextWorld.terrain || []).map((cell) => [cell.x + ":" + cell.y, cell]));
  if (terrainWorldId !== nextWorld.id) createTerrain(nextWorld);
  updateTerrainHealth(nextWorld);
  worldEffects.sync(nextWorld, performance.now());
  if (currentWorldId !== nextWorld.id) {
    currentWorldId = nextWorld.id; selectedAgentId = null;
    for (const label of labels.values()) label.remove();
    for (const group of [peopleGroup, resourceGroup, structureGroup, animalGroup, cropGroup, itemGroup]) {
      for (const child of [...group.children]) disposeSceneObject(child);
    }
    labels.clear(); peopleMeshes.clear(); sceneObjects.clear();
    peopleGroup.clear(); resourceGroup.clear(); structureGroup.clear(); animalGroup.clear(); cropGroup.clear(); itemGroup.clear();
    seedScenery();
    focusPopulation(nextWorld);
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
    const lifeScale = agent.age_days < 3 * 365 ? 0.35 : agent.age_days < 12 * 365 ? 0.65 : 1;
    figure.scale.setScalar(1.35 * lifeScale);
    const held = (nextWorld.items || []).find((item) => item.id === agent.equipped_item_id && item.durability > 0);
    if (figure.userData.equipmentId !== held?.id) {
      if (figure.userData.equipmentVisual) disposeSceneObject(figure.userData.equipmentVisual);
      figure.userData.equipmentVisual = null;
      figure.userData.equipmentId = held?.id;
      if (held) {
        const visual = itemShape(held);
        visual.position.set(0.25, 0.3, 0.12); visual.rotation.z = -0.18;
        figure.add(visual); figure.userData.equipmentVisual = visual;
      }
    }
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
      grave.userData.agentId = agent.id;
      peopleGroup.add(grave); figure.userData.graveMarker = grave;
    }
    figure.userData.selectionRing.visible = agent.alive && agent.id === selectedAgentId;
    const label = labels.get(agent.id);
    const action = agent.last_action?.action?.replaceAll("_", " ");
    const intention = agent.pending_action?.action?.replaceAll("_", " ");
    label.textContent = agent.alive
      ? `${agent.name} · ${action || "observing"}${intention && intention !== action ? ` → ${intention}` : ""}${agent.pregnancy_days_remaining != null ? ` · expecting (${agent.pregnancy_days_remaining}d)` : ""}`
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
  const desiredItems = new Set();
  for (const item of nextWorld.items || []) {
    if (item.kind !== "raft" && item.holder_agent_id) continue;
    const key = `item-${item.id}`; desiredItems.add(key);
    let visual = sceneObjects.get(key);
    if (!visual) { visual = itemShape(item); orientOnGlobe(visual, item.x, item.y, 0.12); itemGroup.add(visual); sceneObjects.set(key, visual); }
    const destination = worldToScene(item.x, item.y, 0.12);
    if (!visual.userData.destination || visual.userData.destination.distanceTo(destination) > 0.01) {
      visual.userData.travelStart = visual.position.clone(); visual.userData.travelStartedAt = performance.now(); visual.userData.destination = destination;
    }
  }
  for (const plot of nextWorld.crops || []) {
    const key = "crop-" + plot.id; desiredCrops.add(key);
    if (!sceneObjects.has(key)) createCrop(plot);
  }
  for (const [key, object] of sceneObjects) {
    if ((key.startsWith("resource-") && !desiredResources.has(key))
      || (key.startsWith("structure-") && !desiredStructures.has(key))
      || (key.startsWith("animal-") && !desiredAnimals.has(key))
      || (key.startsWith("crop-") && !desiredCrops.has(key))
      || (key.startsWith("item-") && !desiredItems.has(key))) {
      disposeSceneObject(object); sceneObjects.delete(key);
    }
  }
}

// Wildlife continuously spawns and dies; release GPU resources when its visual leaves the scene.
function disposeSceneObject(object) {
  const geometries = new Set(), materials = new Set();
  object.traverse((part) => {
    if (part.geometry) geometries.add(part.geometry);
    if (part.material) materials.add(part.material);
  });
  for (const geometry of geometries) geometry.dispose();
  for (const material of materials) material.dispose();
  object.removeFromParent();
}

function renderLabels() {
  const projected = new THREE.Vector3();
  for (const [id, figure] of peopleMeshes) {
    const label = labels.get(id);
    if (fallbackContext) { label.style.display = "none"; continue; }
    projected.copy(figure.position).add(figure.position.clone().normalize().multiplyScalar(1.85)).project(camera);
    const x = (projected.x * 0.5 + 0.5) * host.clientWidth;
    const y = (-projected.y * 0.5 + 0.5) * host.clientHeight;
    label.style.transform = `translate(${x}px,${y}px) translate(-50%,-100%)`;
    const frontFacing = figure.position.clone().normalize().dot(camera.position.clone().sub(figure.position)) > 0;
    label.style.display = !figure.userData.buried && frontFacing && projected.z > -1 && projected.z < 1 && figure.position.clone().sub(camera.position).length() < 55 ? "block" : "none";
  }
}

let lastFrameAt = 0;
function renderFrame(now) {
  const delta = Math.min(0.05, Math.max(0.001, (now - lastFrameAt) / 1000 || 1 / 60));
  lastFrameAt = now;
  const followed = peopleMeshes.get(followingAgentId);
  if (followed) {
    const shift = followed.position.clone().sub(controls.target).multiplyScalar(1 - Math.exp(-5 * delta));
    controls.target.add(shift);
    camera.position.add(shift);
  }
  controls.update();
  constrainCamera();
  // Labels and picking use the same current camera transform as the rendered frame.
  camera.updateMatrixWorld(true);
  camera.matrixWorldInverse.copy(camera.matrixWorld).invert();
  for (const figure of peopleMeshes.values()) {
    const destination = figure.userData.destination;
    if (!destination) continue;
    // Smoothstep along the globe surface keeps each person grounded during travel.
    const start = figure.userData.travelStart || destination;
    const duration = Math.max(280, 1050 / Math.sqrt(world?.time_scale || 1));
    const rawProgress = THREE.MathUtils.clamp((now - (figure.userData.travelStartedAt ?? now)) / duration, 0, 1);
    const progress = rawProgress * rawProgress * (3 - 2 * rawProgress);
    interpolateSurfacePosition(start, destination, progress, 0.08, figure.position);
    if (!figure.userData.dead) figure.quaternion.slerp(new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), figure.position.clone().normalize()), 1 - Math.exp(-10 * delta));
    const moving = !figure.userData.dead && figure.userData.moving && figure.position.distanceTo(destination) > 0.13;
    const working = !figure.userData.dead && figure.userData.working;
    figure.userData.limbs.forEach((limb) => {
      const armAtWork = working && limb.userData.isArm;
      limb.rotation.x = moving ? Math.sin(now * 0.007 + limb.userData.swingPhase) * 0.48
        : armAtWork ? Math.sin(now * 0.005 + limb.userData.swingPhase) * 0.22
          : THREE.MathUtils.damp(limb.rotation.x, 0, 5, delta);
    });
    figure.userData.selectionRing.rotation.z = now * 0.00045;
  }
  for (const [key, animal] of sceneObjects) {
    if ((!key.startsWith("animal-") && !key.startsWith("item-")) || !animal.userData.destination) continue;
    const start = animal.userData.travelStart || animal.userData.destination;
    const progress = THREE.MathUtils.clamp((now - (animal.userData.travelStartedAt ?? now)) / 1300, 0, 1);
    const eased = progress * progress * (3 - 2 * progress);
    interpolateSurfacePosition(start, animal.userData.destination, eased, 0, animal.position);
    animal.quaternion.slerp(new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), animal.position.clone().normalize()), 1 - Math.exp(-8 * delta));
    const walking = animal.position.distanceTo(animal.userData.destination) > 0.02;
    for (const leg of animal.userData.legs || []) leg.rotation.x = walking ? Math.sin(now * 0.012 + leg.userData.phase) * 0.45 : 0;
  }
  worldEffects.update(now);
  updateDaylight();
  renderLabels();
  renderer.render(scene, camera);
  if (hoverPointer && now - lastHoverAt > 80 && !pointerDown) {
    inspectPointer(hoverPointer);
    lastHoverAt = now;
  }
}
let frameError = null;
function frame(now) {
  try {
    renderFrame(now);
    frameError = null;
    if (world) $("#scene-status").hidden = true;
  } catch (error) {
    // A visible failure is actionable; a frozen ocean with no error message is not.
    if (frameError !== error.message) console.error("World frame failed", error);
    frameError = error.message;
    $("#scene-status").hidden = false;
    $("#scene-status").textContent = `World display error: ${error.message}`;
  }
  requestAnimationFrame(frame);
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
  // Keep the unlit terrain readable while still giving it a subtle local-clock night tint.
  if (terrainMesh?.material?.color) {
    terrainMesh.material.color.setRGB(0.78 + daylight * 0.22, 0.83 + daylight * 0.17, 0.9 + daylight * 0.1);
  }
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
    ${statBar("health", agent.health, true)}${statBar("hunger", agent.hunger)}${statBar("thirst", agent.thirst)}${statBar("energy", agent.energy, true)}${statBar("fear", agent.fear || 0)}${statBar("stress", agent.stress || 0)}${statBar("loneliness", agent.loneliness || 0)}
    <form class="edit-form" id="edit-agent"><div class="edit-title">SPECTATOR ADJUSTMENT</div><div class="edit-grid">${["health", "hunger", "thirst", "energy"].map((key) => `<div class="edit-field"><label for="edit-${key}">${key}</label><input id="edit-${key}" name="${key}" type="number" min="0" max="100" value="${Math.round(agent[key])}" ${agent.alive ? "" : "disabled"}/></div>`).join("")}</div><button class="small-action" type="submit" ${agent.alive ? "" : "disabled"}>Apply changes</button></form>
    <div class="detail-list"><div class="detail-line"><span>Parents</span><span>${escapeHtml(namesFor(agent.parent_ids || []))}</span></div><div class="detail-line"><span>Children</span><span>${escapeHtml(namesFor(agent.children_ids || []))}</span></div><div class="detail-line"><span>Bond</span><span>${escapeHtml(partner?.name || "None")}</span></div><div class="detail-line"><span>Pregnancy</span><span>${agent.pregnancy_days_remaining == null ? "No" : `${agent.pregnancy_days_remaining} days`}</span></div>${agent.name_status === "provisional" ? '<div class="detail-line"><span>Name</span><span>Awaiting parent choice</span></div>' : ""}<div class="detail-line"><span>Expected child's names</span><span>${escapeHtml(Object.values(agent.unborn_name_suggestions || {}).join(", ") || "Not chosen")}</span></div><div class="detail-line"><span>Knowledge</span><span>${(agent.knowledge || []).length} learned</span></div><div class="detail-line"><span>Temperament</span><span>${escapeHtml(traits)}</span></div><div class="detail-line"><span>Last action</span><span>${escapeHtml(agent.last_action?.action?.replaceAll("_", " ") || "Observing")}</span></div></div>
    <ul class="memories">${memories.length ? memories.map((memory) => `<li>${escapeHtml(memory)}</li>`).join("") : "<li>No memories yet.</li>"}</ul></div>`;
  const biome = terrainAt(agent.x, agent.y);
  const habitat = document.createElement("div");
  habitat.className = "habitat-line";
  habitat.textContent = "Habitat · " + (biome?.kind?.replaceAll("_", " ") || "unknown");
  ui.inspector.querySelector(".condition")?.after(habitat);
  const explanation = document.createElement("div");
  explanation.className = "action-explanation";
  explanation.textContent = [agent.last_action?.reason, agent.last_result,
    !agent.alive && agent.death_details ? `Death report: ${agent.death_cause || "unrecorded cause"}. Hunger ${Math.round(agent.death_details.hunger ?? agent.hunger)}, thirst ${Math.round(agent.death_details.thirst ?? agent.thirst)}, energy ${Math.round(agent.death_details.energy ?? agent.energy)}. ${agent.death_details.disease || ""} ${agent.death_details.attribution || ""}` : "",
    agent.family_offer && agent.family_offer_until_tick >= world.tick ? `Family proposal: ${agent.family_offer.action} · waiting for an answer` : "",
    agent.pregnancy_days_remaining != null ? `Birth in about ${Math.ceil((agent.pregnancy_days_remaining * (world.day_length_seconds || 720 / 365) - (world.day_progress_seconds || 0)) / (world.time_scale || 1))} real seconds at current speed` : "",
    agent.construction_project ? `Project: ${agent.construction_project.replaceAll("_", " ")}` : "",
    agent.decision_source ? `Decision: ${agent.decision_source}${agent.intention_source ? ` (${agent.intention_source} intention)` : ""}` : ""].filter(Boolean).join(" · ");
  ui.inspector.querySelector(".detail-list")?.after(explanation);
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
  $("#culture-count").textContent = String(groups.length + beliefs.length + structures.length);
  const block = (title, values, count = true) => `<div class="culture-block"><h4>${title}${count ? ` · ${values.length}` : ""}</h4><div class="chip-list">${values.length ? values.map((value) => `<span class="chip">${escapeHtml(value)}</span>`).join("") : '<span class="chip">None yet</span>'}</div></div>`;
  $("#culture-popover").innerHTML = `<h3>World culture</h3>${block("Structures", structures.map((item) => item.kind.replaceAll("_", " ")))}${block("Groups", groups.map((item) => `${item.name} · ${item.kind} · ${item.member_ids.length}`))}${block("Beliefs", beliefs.map((item) => `${item.name} · ${item.kind}`))}`;
  $("#culture-popover").insertAdjacentHTML("beforeend", block("Wildlife · NPC", [...new Set(animals.filter((item) => item.alive).map((item) => `${item.species} · ${item.animal_type}`))], false) + block("Growing crops", crops.map((item) => `${item.crop_kind} · ${item.growth_days} days · ${Math.round(item.moisture)}% moisture`)));
}

function renderWorld(next) {
  world = next;
  const year = Math.floor(world.tick / 365) + 1; const day = (world.tick % 365) + 1;
  const living = world.agents.filter((agent) => agent.alive).length;
  const localTime = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  ui.clock.textContent = `LOCAL ${localTime} · YEAR ${year} · DAY ${day} · ${world.time_scale || 1}×${world.processing ? " · THINKING" : ""}`;
  $("#population-label").textContent = String(living);
  $("#age-label").textContent = String(year);
  $("#weather-label").textContent = world.weather || "clear";
  $("#world-summary").textContent = [living + " people", "living wildlife", (world.crops?.length || 0) + " growing crops", world.season || "spring"].join(" · ");
  if (document.activeElement !== $("#speed-select")) $("#speed-select").value = world.auto_accelerate ? "auto" : String(world.time_scale || 2);
  ui.run.textContent = world.running ? "Ⅱ" : "▶";
  ui.run.title = world.running ? "Pause the simulation" : "Run the simulation";
  syncObjects(world); renderInspector(); renderCulture(); renderDeathReports();
}

function renderDeathReports() {
  const changed = deathWorldId !== world.id;
  if (changed) { deathWorldId = world.id; reportedDeaths.clear(); }
  const deceased = world.agents.filter((person) => !person.alive);
  for (const person of deceased) {
    if (!changed && !reportedDeaths.has(person.id)) notify(`${person.name} died from ${person.death_cause || "an unrecorded cause"}.`, true);
    reportedDeaths.add(person.id);
  }
  const panel = $("#death-notices");
  panel.hidden = deceased.length === 0;
  panel.innerHTML = deceased.slice(-3).reverse().map((person) => `<button class="death-report" data-person="${escapeHtml(person.id)}"><b>${escapeHtml(person.name)} died</b><span>${escapeHtml(person.death_cause || "Cause was not recorded")}</span><small>${person.death_tick == null ? "Historical record" : `Day ${person.death_tick + 1}`} · click for their life record</small></button>`).join("");
  for (const button of document.querySelectorAll(".death-report")) button.addEventListener("click", () => {
    selectedAgentId = button.dataset.person; renderInspector(); focusPopulation(world);
  });
}

async function refreshWorld() {
  try { renderWorld(await api("/api/world")); }
  catch (error) {
    ui.clock.textContent = "WORLD CONNECTION ERROR";
    $("#scene-status").hidden = false;
    $("#scene-status").textContent = `World connection failed: ${error.message}`;
  }
}

async function refreshModels() {
  try {
    const [health, response] = await Promise.all([api("/api/health"), api("/api/models")]);
  const selected = world?.global_model || health.default_model || "qwen2.5:0.5b";
    const options = (response.models || []).map((model) => `<option value="${escapeHtml(model)}">${escapeHtml(model)}</option>`);
    if (!response.models?.includes(selected)) options.unshift(`<option value="${escapeHtml(selected)}">${escapeHtml(selected)} · unavailable</option>`);
    ui.model.innerHTML = options.join("") || `<option value="${escapeHtml(selected)}">${escapeHtml(selected)}</option>`;
    ui.model.value = selected;
    ui.model.disabled = true;
    $("#compute-status").textContent = `QWEN · ${(health.compute?.device || "checking").toUpperCase()}`;
    ui.model.title = health.model_ready ? "Qwen guides each separate private mind." : "Qwen is unavailable. The world uses a recorded survival fallback.";
  } catch (error) { ui.model.innerHTML = "<option>Ollama unavailable</option>"; ui.model.title = error.message; }
}

ui.run.addEventListener("click", async () => {
  try {
    if (world?.running) await api("/api/world/pause", { method: "POST" });
    else await api("/api/world/run", { method: "POST" });
    await refreshWorld();
  } catch (error) { notify(error.message, true); }
});
$("#speed-select").addEventListener("change", async (event) => {
  const automatic = event.target.value === "auto";
  try { renderWorld(await api("/api/world/speed", { method: "PATCH", body: JSON.stringify({ time_scale: automatic ? 2 : Number(event.target.value), auto_accelerate: automatic }) })); }
  catch (error) { notify(error.message, true); }
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
  scene.updateMatrixWorld(true);
  camera.updateMatrixWorld(true);
  const bounds = renderer.domElement.getBoundingClientRect();
  pointer.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1;
  pointer.y = -((event.clientY - bounds.top) / bounds.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
}

function groundHit(event) {
  if (fallbackContext) {
    const hit = compatibilityHit(event, true);
    if (!hit) return null;
    const location = sceneToWorld(hit.point);
    return terrainAt(location.x, location.y)?.kind !== "ocean" ? hit.point : null;
  }
  castPointer(event);
  const hit = raycaster.intersectObject(terrainMesh, false)[0];
  if (!hit) return null;
  const location = sceneToWorld(hit.point);
  if (terrainAt(location.x, location.y)?.kind === "ocean") return null;
  return hit.point;
}

function inspectPointer(event) {
  const tooltip = $("#world-tooltip");
  if (!world) { tooltip.hidden = true; return null; }
  castPointer(event);
  const hit = fallbackContext ? compatibilityHit(event)
    : raycaster.intersectObjects([peopleGroup, animalGroup, resourceGroup, structureGroup, cropGroup, itemGroup, terrainMesh], true)[0];
  const description = describeWorldHit(hit, world, sceneToWorld);
  if (!description) { tooltip.hidden = true; return null; }
  tooltip.innerHTML = `<strong>${escapeHtml(description.title)}</strong>${description.lines.filter(Boolean).map((line) => `<span>${escapeHtml(line)}</span>`).join("")}`;
  const bounds = host.getBoundingClientRect();
  tooltip.style.left = `${Math.max(8, Math.min(host.clientWidth - 264, event.clientX - bounds.left + 16))}px`;
  tooltip.style.top = `${Math.max(8, Math.min(host.clientHeight - 150, event.clientY - bounds.top + 18))}px`;
  tooltip.hidden = false;
  return description;
}

renderer.domElement.addEventListener("pointermove", (event) => { hoverPointer = { clientX: event.clientX, clientY: event.clientY }; });
renderer.domElement.addEventListener("pointerleave", () => { hoverPointer = null; $("#world-tooltip").hidden = true; });

function compatibilityHit(event, landOnly = false) {
  const bounds = host.getBoundingClientRect();
  const px = event.clientX - bounds.left, py = event.clientY - bounds.top;
  const { direction, right, up, radius } = compatibilityFrame();
  if (!landOnly) {
    // Match the orthographic drawing, rather than using the perspective WebGL picking ray.
    const entries = [...(world?.agents || []).filter((agent) => !agent.buried).map((agent) => ({
      x: agent.x, y: agent.y, object: peopleMeshes.get(agent.id) })),
    ...(world?.animals || []).filter((animal) => animal.alive).map((animal) => ({
      x: animal.x, y: animal.y, object: sceneObjects.get(`animal-${animal.id}`) })),
    ...(world?.items || []).filter((item) => item.kind === "raft" || !item.holder_agent_id).map((item) => ({
      x: item.x, y: item.y, object: sceneObjects.get(`item-${item.id}`) }))];
    for (const item of entries.reverse()) {
      const point = worldToScene(item.x, item.y), normal = point.clone().normalize();
      if (normal.dot(direction) <= 0 || !item.object) continue;
      const distance = Math.hypot(px - host.clientWidth / 2 - normal.dot(right) * radius,
        py - host.clientHeight / 2 + normal.dot(up) * radius);
      if (distance <= 12) return { object: item.object, point };
    }
  }
  const x = (px - host.clientWidth / 2) / radius, y = (host.clientHeight / 2 - py) / radius;
  if (x * x + y * y > 1) return null;
  const normal = direction.multiplyScalar(Math.sqrt(Math.max(0, 1 - x * x - y * y)))
    .addScaledVector(right, x).addScaledVector(up, y);
  return { object: terrainMesh, point: normal.multiplyScalar(globeRadius) };
}

renderer.domElement.addEventListener("pointerdown", (event) => { pointerDown = { x: event.clientX, y: event.clientY }; });
renderer.domElement.addEventListener("pointerup", (event) => {
  if (!pointerDown || Math.hypot(event.clientX - pointerDown.x, event.clientY - pointerDown.y) > 5) { pointerDown = null; return; }
  castPointer(event);
  if (armedEvent) {
    const point = groundHit(event);
    if (point) { triggerEvent(armedEvent, point); armedEvent = null; host.classList.remove("event-armed"); }
    pointerDown = null;
    return;
  }
  const hits = fallbackContext ? [compatibilityHit(event)].filter(Boolean) : raycaster.intersectObjects(peopleGroup.children, true);
  const globeHit = raycaster.intersectObject(terrainMesh, false)[0];
  const visibleHits = hits.filter((hit) => fallbackContext || !globeHit || hit.distance < globeHit.distance);
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
  tool.addEventListener("click", () => { armedEvent = tool.dataset.event; host.classList.add("event-armed"); notify("Click a place on the land, or drag the event there."); });
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
setInterval(refreshWorld, 750);
setInterval(refreshModels, 20000);
