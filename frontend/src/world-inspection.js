// Resolve metadata on a figure's parent so any body part can be hovered, not just its root.
export function describeWorldHit(hit, world, locateCell) {
  if (!hit || !world) return null;
  let object = hit.object;
  while (object) {
    const data = object.userData || {};
    if (data.agentId) {
      const agent = world.agents.find((item) => item.id === data.agentId);
      if (!agent) return null;
      return { title: agent.name, lines: [agent.alive ? `${Math.floor(agent.age_days / 365)} years · ${agent.sex}` : "Deceased",
        `Health ${Math.round(agent.health)} · Hunger ${Math.round(agent.hunger)} · Thirst ${Math.round(agent.thirst)}`,
        `Action: ${(agent.last_action?.action || "observing").replaceAll("_", " ")}`, agent.last_result || "Click to inspect this person."] };
    }
    if (data.animalId) {
      const animal = world.animals?.find((item) => item.id === data.animalId);
      if (!animal) return null;
      return { title: animal.species, lines: [`${animal.animal_type} · NPC`,
        `Health ${Math.round(animal.health)} · Hunger ${Math.round(animal.hunger)} · Thirst ${Math.round(animal.thirst)}`,
        animal.disease || "Healthy", animal.owner_agent_id ? `Cared for by ${world.agents.find((item) => item.id === animal.owner_agent_id)?.name || "an agent"}` : "Lives in the wild"] };
    }
    if (data.resource) {
      const node = world.resources.find((item) => item.kind === data.resource.kind && item.x === data.resource.x && item.y === data.resource.y);
      if (!node) return null;
      return { title: node.kind.replaceAll("_", " "), lines: [`${node.quantity} available · capacity ${node.capacity}`, `Contamination ${Math.round(node.contamination || 0)}%`] };
    }
    if (data.structureId) {
      const building = world.structures.find((item) => item.id === data.structureId);
      if (!building) return null;
      return { title: building.kind.replaceAll("_", " "), lines: [`Condition ${Math.round(building.condition ?? 100)}%`,
        `Owner: ${world.agents.find((item) => item.id === building.owner_agent_id)?.name || "Shared"}`] };
    }
    if (data.cropId) {
      const crop = world.crops?.find((item) => item.id === data.cropId);
      if (!crop) return null;
      return { title: `${crop.crop_kind} crop`, lines: [`${crop.growth_days} growing days`,
        `Moisture ${Math.round(crop.moisture)}% · Condition ${Math.round(crop.condition)}%`] };
    }
    if (data.isLand) {
      const location = locateCell(hit.point);
      const cell = world.terrain.find((item) => item.x === location.x && item.y === location.y);
      if (!cell) return null;
      return { title: cell.kind.replaceAll("_", " "), lines: [
        `Habitat health ${Math.round(cell.condition ?? 100)}% · Fertility ${Math.round(cell.fertility ?? 70)}%`,
        `Moisture ${Math.round(cell.moisture * 100)}% · Pollution ${Math.round(cell.pollution || 0)}%`] };
    }
    object = object.parent;
  }
  return null;
}
