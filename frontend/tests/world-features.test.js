import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { WorldEffects } from "../src/world-effects.js";
import { describeWorldHit } from "../src/world-inspection.js";

test("every intervention animates at its geographic point, deduplicates and releases resources", () => {
  const scene = new THREE.Scene();
  const effects = new WorldEffects(scene, (x, y, height) => new THREE.Vector3(x, 10 + height, y));
  const world = { id: "world", running: true, events: [] };
  effects.sync(world, 0);
  const kinds = ["wildfire", "storm", "flood", "drought", "injury", "disease_outbreak"];
  world.events = kinds.map((event, index) => ({ id: String(index), kind: "spectator_event", details: { event, x: index, y: 2 } }));
  effects.sync(world, 100);
  effects.sync(world, 200);
  assert.equal(effects.active.size, 6);
  assert.equal(effects.active.get("3").group.position.x, 3);
  effects.update(500);
  const before = effects.active.get("0").particles[0].position.clone();
  effects.update(1000);
  assert.ok(before.distanceTo(effects.active.get("0").particles[0].position) > 0);
  assert.equal(world.running, true);
  effects.update(15000);
  assert.equal(effects.active.size, 0);
  assert.equal(effects.root.children.length, 0);
});

test("hover descriptions cover animals, resources, buildings, crops and terrain", () => {
  const world = { agents: [], animals: [{ id: "goat", species: "goat", animal_type: "wild", health: 90, hunger: 20, thirst: 25 }],
    resources: [{ kind: "wood", x: 1, y: 2, quantity: 8, capacity: 12 }],
    structures: [{ id: "hut", kind: "hut", condition: 85 }], crops: [{ id: "crop", crop_kind: "fruit", growth_days: 7, moisture: 60, condition: 90 }],
    terrain: [{ x: 1, y: 2, kind: "forest", condition: 65, fertility: 50, moisture: 0.7, pollution: 10 }] };
  for (const [data, title] of [[{ animalId: "goat" }, "goat"], [{ resource: { kind: "wood", x: 1, y: 2 } }, "wood"],
    [{ structureId: "hut" }, "hut"], [{ cropId: "crop" }, "fruit crop"], [{ isLand: true }, "forest"]]) {
    const parent = { userData: data };
    const hit = { object: { userData: {}, parent }, point: new THREE.Vector3() };
    const result = describeWorldHit(hit, world, () => ({ x: 1, y: 2 }));
    assert.equal(result.title, title);
    assert.ok(result.lines.length > 0);
  }
});
