import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
import * as Three from "three";
import { interpolateSurfacePosition } from "../src/surface-motion.js";
import { WorldEffects } from "../src/world-effects.js";
import { describeWorldHit } from "../src/world-inspection.js";

test("spectator controls omit world summary, time scaling, and manual month stepping", async () => {
  const html = await readFile(new URL("../index.html", import.meta.url), "utf8");
  assert.match(html, /<title>Origin: AI World<\/title>/);
  assert.match(html, /<b>Origin: AI World<\/b>/);
  assert.doesNotMatch(html, /id="world-summary"|id="speed-select"|id="step-button"/);
});

test("surface travel stays above the sphere across seams, poles and opposite directions", () => {
  for (const [start, end] of [
    [new Three.Vector3(10, 0, 0), new Three.Vector3(-10, 0, 0)],
    [new Three.Vector3(-0.1, 0, -10).normalize().multiplyScalar(10), new Three.Vector3(0.1, 0, -10).normalize().multiplyScalar(10)],
    [new Three.Vector3(0, 10, 0), new Three.Vector3(0, 0, 12)],
  ]) {
    for (let step = 0; step <= 20; step++) {
      const amount = step / 20;
      const value = interpolateSurfacePosition(start, end, amount, 0.1);
      assert.ok(value.toArray().every(Number.isFinite));
      assert.ok(value.length() >= Three.MathUtils.lerp(start.length(), end.length(), amount) - 1e-8);
    }
    assert.ok(interpolateSurfacePosition(start, end, 0).distanceTo(start) < 1e-8);
    assert.ok(interpolateSurfacePosition(start, end, 1).distanceTo(end) < 1e-8);
  }
});

// Run the actual application with real Three.js math/meshes and replace only browser/GPU surfaces.
// This catches runtime API mistakes that a Vite build cannot detect, without requiring a browser.
async function loadWorldApp(forceFallback = false) {
  class Element {
    constructor(tag = "div") {
      this.tagName = tag; this.style = {}; this.dataset = {}; this.children = [];
      this.events = new Map(); this.hidden = false; this.clientWidth = 1200; this.clientHeight = 800;
      this.classList = { add() {}, remove() {}, toggle() {} };
      this.queries = new Map(); this.draws = 0; this.arcs = [];
    }
    appendChild(child) { child.parent = this; this.children.push(child); return child; }
    remove() { if (this.parent) this.parent.children = this.parent.children.filter((item) => item !== this); }
    addEventListener(name, callback) { this.events.set(name, callback); }
    setAttribute() {}
    contains() { return false; }
    after() {}
    insertAdjacentHTML() {}
    querySelector(selector) {
      if (!this.queries.has(selector)) this.queries.set(selector, new Element());
      return this.queries.get(selector);
    }
    getBoundingClientRect() { return { left: 0, top: 0, width: this.clientWidth, height: this.clientHeight }; }
    getContext() {
      return new Proxy({}, { get: (_, name) => name === "createRadialGradient"
        ? () => ({ addColorStop() {} }) : (...args) => { this.draws++; if (name === "arc") this.arcs.push(args); } });
    }
  }
  const elements = new Map();
  const document = {
    activeElement: null,
    createElement: (tag) => new Element(tag),
    querySelector(selector) {
      if (!elements.has(selector)) elements.set(selector, new Element());
      return elements.get(selector);
    },
    querySelectorAll: () => [],
  };
  class Renderer {
    constructor() {
      if (forceFallback) throw new Error("WebGL blocked in compatibility test");
      this.domElement = new Element("canvas"); this.shadowMap = {}; this.capabilities = { getMaxAnisotropy: () => 1 }; this.drawnFrames = 0;
    }
    setPixelRatio() {}
    setSize() {}
    render(scene, camera) { scene.updateMatrixWorld(true); camera.updateMatrixWorld(true); this.drawnFrames++; }
  }
  class Controls {
    constructor(camera) { this.camera = camera; this.target = new Three.Vector3(); }
    update() { this.camera.lookAt(this.target); this.camera.updateMatrixWorld(true); }
  }
  const agent = (id, x, sex) => ({ id, name: id, x, y: 8, sex, age_days: 7300, health: 100,
    hunger: 15, thirst: 15, energy: 85, alive: true, buried: false, traits: {}, memories: [],
    knowledge: [], parent_ids: [], children_ids: [], last_action: { action: "gather", reason: "Collect wood for shelter" } });
  const world = {
    id: "runtime-world", width: 36, height: 18, tick: 0, month_progress_seconds: 0, month_length_seconds: 60,
    global_model: "qwen2.5:0.5b", running: true, weather: "clear", season: "spring", groups: [], beliefs: [],
    agents: [agent("Aru", 17, "male"), agent("Nima", 18, "female")],
    terrain: Array.from({ length: 648 }, (_, index) => ({ x: index % 36, y: Math.floor(index / 36), kind: "forest", elevation: 0.2 })),
    animals: [{ id: "goat", species: "goat", animal_type: "wild", x: 19, y: 8, alive: true, health: 100, hunger: 15, thirst: 15 }],
    resources: [{ kind: "wood", x: 17, y: 8, quantity: 12, capacity: 20 }],
    structures: [{ id: "shelter", kind: "lean_to", x: 16, y: 8 }], crops: [],
  };
  let clock = 100;
  const context = vm.createContext({
    THREE: { ...Three, WebGLRenderer: Renderer }, OrbitControls: Controls, interpolateSurfacePosition, WorldEffects, describeWorldHit,
    document, window: { devicePixelRatio: 1, confirm: () => false }, console: forceFallback ? { ...console, error() {} } : console,
    performance: { now: () => clock }, ResizeObserver: class { observe() {} },
    requestAnimationFrame() {}, setInterval() {}, setTimeout() {}, clearTimeout() {}, AbortSignal,
    fetch: async (url) => ({ ok: true, json: async () => url === "/api/world" ? world :
      url === "/api/models" ? { models: ["qwen2.5:0.5b"] } : { ollama_available: true, default_model: "qwen2.5:0.5b" } }),
  });
  const source = (await readFile(new URL("../src/app.js", import.meta.url), "utf8"))
    .replace(/^import .*;\r?$/gm, "").replaceAll("import.meta.env", "({})");
  vm.runInContext(source + "\nglobalThis.app = { renderWorld, renderFrame, peopleMeshes, labels, sceneObjects, camera, controls, renderer, zoomView, showWholeWorld, worldToScene, groundHit, inspectPointer, constrainCamera, worldEffects, getSelected: () => selectedAgentId, getTerrain: () => terrainMesh };", context);
  await new Promise(setImmediate);
  return { app: context.app, world, elements, setClock(value) { clock = value; } };
}

test("a populated world renders continuing frames, moves people/animals, and updates death and burial", async () => {
  const { app, world, setClock, elements } = await loadWorldApp();
  assert.equal(app.peopleMeshes.size, 2);
  assert.doesNotThrow(() => { app.renderFrame(100); app.renderFrame(200); });
  assert.equal(app.renderer.drawnFrames, 2);
  assert.ok(app.getTerrain().material.map.image.draws > 648, "actual biomes are painted into the texture");
  const person = app.peopleMeshes.get("Aru");
  const chest = person.position.clone().addScaledVector(person.position.clone().normalize(), 0.98).project(app.camera);
  const click = { clientX: (chest.x + 1) * 600, clientY: (1 - chest.y) * 400 };
  app.renderer.domElement.events.get("pointerdown")(click);
  app.renderer.domElement.events.get("pointerup")(click);
  assert.equal(app.getSelected(), "Aru", "clicking a rendered person opens that person's inspector");
  assert.equal(app.inspectPointer(click).title, "Aru");
  assert.equal(elements.get("#world-tooltip").hidden, false);
  assert.ok(app.groundHit(click), "event placement ray reaches the actual land");
  // Texture UVs and entity coordinates must refer to the same geographic longitude.
  const geometry = app.getTerrain().geometry;
  for (let index = 1000; index < geometry.attributes.position.count; index += 173) {
    const uv = new Three.Vector2().fromBufferAttribute(geometry.attributes.uv, index);
    const point = new Three.Vector3().fromBufferAttribute(geometry.attributes.position, index).normalize();
    const expected = app.worldToScene(uv.x * 36 - 0.5, (1 - uv.y) * 18 - 0.5).normalize();
    assert.ok(point.distanceTo(expected) < 1e-5, "terrain colors align with positions");
  }
  const figure = app.peopleMeshes.get("Aru");
  const original = figure.position.clone();
  setClock(300);
  world.agents[0].x = 18;
  world.agents[0].last_action.action = "move";
  world.animals[0].x = 20;
  app.renderWorld(world);
  app.renderFrame(800);
  assert.ok(figure.position.distanceTo(original) > 0.1);
  app.renderFrame(1700);
  assert.ok(figure.position.distanceTo(app.worldToScene(18, 8, 0.28)) < 1e-6);
  assert.ok(app.labels.get("Aru").textContent.includes("move"));
  const animal = app.sceneObjects.get("animal-goat");
  assert.ok(animal.scale.x <= 0.65, "food NPCs stay much smaller than people");
  assert.ok(animal.position.distanceTo(app.worldToScene(20, 8, 0.02)) < 1e-6);
  const distance = app.camera.position.distanceTo(app.controls.target);
  app.zoomView(0.8);
  assert.ok(app.camera.position.distanceTo(app.controls.target) < distance);
  app.camera.position.set(0, 0, 0);
  app.constrainCamera();
  assert.ok(app.camera.position.length() > 11, "camera cannot enter the ground");
  assert.ok(app.camera.position.clone().sub(app.controls.target).dot(app.controls.target.clone().normalize()) >= 1.99);
  world.events = [{ id: "fire", kind: "spectator_event", details: { event: "wildfire", x: 18, y: 8 } }];
  app.renderWorld(world);
  app.renderFrame(1750);
  assert.equal(app.worldEffects.active.size, 1);
  assert.equal(world.running, true, "display effects must not pause the world");
  app.renderFrame(13000);
  assert.equal(app.worldEffects.active.size, 0, "transient effects release their objects");
  world.agents[0].alive = false;
  app.renderWorld(world); app.renderFrame(1800);
  assert.ok(figure.userData.deathPoseApplied);
  world.agents[0].buried = true;
  app.renderWorld(world); app.renderFrame(1900);
  assert.equal(figure.visible, false);
  assert.ok(figure.userData.graveMarker);
  world.id = "new-world";
  app.renderWorld(world); app.renderFrame(2000);
  assert.equal(app.peopleMeshes.size, 2, "reset must not retain old figures");
});

test("blocked WebGL still updates the compatibility globe, picking, events and camera zoom", async () => {
  const { app, world } = await loadWorldApp(true);
  assert.doesNotThrow(() => app.renderFrame(100));
  const canvas = app.renderer.domElement;
  assert.ok(canvas.draws > 600, "fallback paints the received biome data and living entities");
  const direction = app.camera.position.clone().normalize();
  const right = new Three.Vector3().crossVectors(new Three.Vector3(0, 1, 0), direction).normalize();
  const up = new Three.Vector3().crossVectors(direction, right).normalize();
  const normal = app.worldToScene(17, 8).normalize();
  const radius = Math.min(1200 * 0.45, 800 * 0.39) * (29 / app.camera.position.length());
  const pointer = { clientX: 600 + normal.dot(right) * radius, clientY: 400 - normal.dot(up) * radius };
  assert.equal(app.inspectPointer(pointer).title, "Aru", "compatibility hover matches the drawn figure");
  assert.ok(app.groundHit(pointer), "compatibility event drops hit drawn land");
  app.renderer.domElement.events.get("pointerdown")(pointer);
  app.renderer.domElement.events.get("pointerup")(pointer);
  assert.equal(app.getSelected(), "Aru");
  const before = canvas.arcs.at(-1)[2];
  app.zoomView(0.8);
  app.renderFrame(200);
  assert.ok(canvas.arcs.at(-1)[2] > before, "zoom changes the fallback's visible globe size");
  assert.equal(app.labels.get("Aru").style.display, "none", "fallback draws its own correctly projected labels");
  world.events = [{ id: "fallback-storm", details: { event: "storm", x: 17, y: 8 } }];
  app.renderWorld(world);
  app.renderFrame(300);
  assert.equal(app.worldEffects.active.size, 1);
  assert.equal(world.running, true);
});

test("shared tools render and births/deaths stay in the agent life timeline", async () => {
  const { app, world, elements } = await loadWorldApp();
  // The browser applies the HTML hidden attribute; model that initial DOM state here.
  elements.get("#world-timeline").hidden = true;
  world.items = [{ id: "spear", kind: "spear", x: 17, y: 8, creator_agent_id: "Aru", durability: 100 },
    { id: "raft", kind: "raft", x: 18, y: 8, creator_agent_id: "Nima", durability: 100, capacity: 4 }];
  app.renderWorld(world); app.renderFrame(100);
  assert.ok(app.sceneObjects.has("item-spear"));
  assert.ok(app.sceneObjects.has("item-raft"));
  world.agents[0].equipped_item_id = "spear";
  world.items[0].holder_agent_id = "Aru";
  app.renderWorld(world); app.renderFrame(200);
  assert.equal(app.sceneObjects.has("item-spear"), false);
  assert.equal(app.peopleMeshes.get("Aru").userData.equipmentVisual.userData.itemId, "spear");
  world.agents[1].alive = false;
  world.agents[1].death_cause = "a wolf attack";
  world.agents[1].death_tick = 8;
  world.events = [
    { id: "work", kind: "action", tick: 8, message: "Aru gathered wood.", agent_ids: ["Aru"], details: { action: "gather" } },
    { id: "birth", kind: "birth", tick: 7, message: "A child was born.", agent_ids: ["Aru"] },
    { id: "death", kind: "death", tick: 8, message: "Nima died from a wolf attack.", agent_ids: ["Nima"] },
  ];
  app.renderWorld(world); app.renderFrame(300);
  const timeline = elements.get("#world-timeline");
  assert.equal(timeline.hidden, true, "timeline stays closed until opened by the spectator");
  assert.ok(timeline.innerHTML.includes("Aru gathered wood."));
  assert.ok(timeline.innerHTML.includes("Newborns"));
  assert.ok(timeline.innerHTML.includes("Nima died from a wolf attack."));
  assert.ok(timeline.innerHTML.includes('data-timeline-filter="death"'));
  assert.ok(!String(elements.get("#toast").textContent || "").includes("a wolf attack"), "death is not a transient pop-up");
  timeline.events.get("click")({ target: { closest: (selector) => selector === "[data-timeline-filter]"
    ? { dataset: { timelineFilter: "death" } } : null } });
  assert.ok(timeline.innerHTML.includes("Nima died from a wolf attack."), "death tab contains the persistent report");
  elements.get("#timeline-button").events.get("click")();
  assert.equal(timeline.hidden, false, "the life button opens the timeline");
  timeline.events.get("click")({ target: { closest: (selector) => selector === "[data-timeline-agent]"
    ? { dataset: { timelineAgent: "Nima" } } : null } });
  assert.equal(app.getSelected(), "Nima", "choosing an entry opens that agent's globe inspector");
  assert.equal(timeline.hidden, true, "the timeline closes when following an agent");
});
