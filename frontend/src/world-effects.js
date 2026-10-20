import * as THREE from "three";

const colors = { wildfire: 0xff6a24, storm: 0x77b9e3, flood: 0x399ed1, drought: 0xc69c57,
  disease_outbreak: 0x9b70c7, injury: 0xd45b4b, terrain_care: 0x79a95a };

// Effects consume event records, never control simulation time or change authoritative state.
export class WorldEffects {
  constructor(scene, locate) {
    this.root = new THREE.Group();
    scene.add(this.root);
    this.locate = locate;
    this.active = new Map();
    this.seen = new Set();
    this.worldId = null;
  }

  sync(world, now) {
    if (this.worldId !== world.id) {
      this.clear();
      this.worldId = world.id;
      // Opening a saved world must not replay its entire historical disaster log.
      this.seen = new Set((world.events || []).map((event) => event.id));
      return;
    }
    for (const event of world.events || []) {
      if (this.seen.has(event.id)) continue;
      this.seen.add(event.id);
      const kind = event.details?.event || ({ terrain_care: "terrain_care", disease_started: "disease_outbreak",
        animal_disease: "disease_outbreak", injury: "injury" })[event.kind];
      const subject = (world.agents || []).find((agent) => event.agent_ids?.includes(agent.id))
        || (world.animals || []).find((animal) => animal.id === event.details?.animal_id);
      const x = event.details?.x ?? subject?.x, y = event.details?.y ?? subject?.y;
      if (!colors[kind] || x == null || y == null) continue;
      this.add(event.id, kind, x, y, now);
    }
    if (this.seen.size > 3000) this.seen = new Set((world.events || []).map((event) => event.id));
  }

  add(id, kind, x, y, now) {
    if (!colors[kind] || this.active.has(id)) return;
    if (this.active.size >= 24) this.remove(this.active.keys().next().value);
    const group = new THREE.Group();
    group.position.copy(this.locate(x, y, 0.12));
    group.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), group.position.clone().normalize());
    const duration = kind === "injury" || kind === "terrain_care" ? 3500 : 10000;
    const material = new THREE.MeshBasicMaterial({ color: colors[kind], transparent: true, opacity: 0.8, depthWrite: false });
    const ring = new THREE.Mesh(new THREE.RingGeometry(0.35, 0.44, 36), material);
    ring.rotation.x = -Math.PI / 2;
    ring.material.side = THREE.DoubleSide;
    group.add(ring);
    const particles = [];
    const geometry = kind === "wildfire" ? new THREE.ConeGeometry(0.12, 0.5, 5)
      : kind === "storm" ? new THREE.CylinderGeometry(0.015, 0.015, 0.4, 4)
        : new THREE.SphereGeometry(kind === "injury" ? 0.07 : 0.10, 6, 5);
    for (let index = 0; index < 24; index++) {
      const particle = new THREE.Mesh(geometry, material);
      particle.userData.phase = index / 24;
      particle.userData.angle = index * 2.39996;
      group.add(particle);
      particles.push(particle);
    }
    if (kind === "flood") {
      const water = new THREE.Mesh(new THREE.CircleGeometry(1, 40), material);
      water.rotation.x = -Math.PI / 2;
      water.position.y = 0.04;
      group.add(water);
      group.userData.water = water;
    }
    if (kind === "storm") {
      const cloudMaterial = new THREE.MeshBasicMaterial({ color: 0x87969d, transparent: true, opacity: 0.6 });
      for (let index = 0; index < 4; index++) {
        const cloud = new THREE.Mesh(new THREE.SphereGeometry(0.55, 8, 6), cloudMaterial);
        cloud.position.set((index - 1.5) * 0.5, 2.8, 0);
        cloud.scale.y = 0.5;
        group.add(cloud);
      }
    }
    this.root.add(group);
    this.active.set(id, { group, kind, start: now, duration, material, ring, particles });
  }

  update(now) {
    for (const [id, effect] of this.active) {
      const age = (now - effect.start) / effect.duration;
      if (age >= 1) { this.remove(id); continue; }
      const seconds = (now - effect.start) / 1000;
      effect.material.opacity = Math.min(0.85, (1 - age) * 1.3);
      effect.ring.scale.setScalar(1 + age * 7);
      if (effect.group.userData.water) effect.group.userData.water.scale.setScalar(0.6 + Math.sin(age * Math.PI) * 2);
      for (const particle of effect.particles) {
        const phase = (seconds * 0.7 + particle.userData.phase) % 1;
        const angle = particle.userData.angle + (effect.kind === "drought" ? seconds : 0);
        const radius = effect.kind === "injury" ? age * 1.4 : 0.3 + particle.userData.phase * 1.6;
        const height = effect.kind === "storm" ? (1 - phase) * 2.6
          : effect.kind === "flood" ? 0.08 + Math.sin(seconds * 3 + angle) * 0.05 : phase * 1.4;
        particle.position.set(Math.cos(angle) * radius, height, Math.sin(angle) * radius);
        if (effect.kind === "wildfire") particle.scale.setScalar(0.5 + Math.sin(phase * Math.PI));
      }
    }
  }

  remove(id) {
    const effect = this.active.get(id);
    if (!effect) return;
    const geometries = new Set(), materials = new Set();
    effect.group.traverse((part) => {
      if (part.geometry) geometries.add(part.geometry);
      if (part.material) materials.add(part.material);
    });
    for (const geometry of geometries) geometry.dispose();
    for (const material of materials) material.dispose();
    effect.group.removeFromParent();
    this.active.delete(id);
  }

  clear() { for (const id of [...this.active.keys()]) this.remove(id); }
}
