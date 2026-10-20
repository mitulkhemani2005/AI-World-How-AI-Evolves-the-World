import { MathUtils, Quaternion, Vector3 } from "three";

const originRotation = new Quaternion();
const rotation = new Quaternion();
const partialRotation = new Quaternion();
const fromDirection = new Vector3();
const toDirection = new Vector3();

// Vector3 has no slerp method. Rotate the start direction with quaternion interpolation instead.
// Interpolating radius separately keeps travel above the globe, including longitude seams and poles.
export function interpolateSurfacePosition(start, destination, progress, arcHeight = 0, target = new Vector3()) {
  const amount = MathUtils.clamp(progress, 0, 1);
  const radius = MathUtils.lerp(start.length(), destination.length(), amount);
  if (radius === 0) return target.set(0, 0, 0);
  fromDirection.copy(start).normalize();
  toDirection.copy(destination).normalize();
  if (fromDirection.lengthSq() === 0) fromDirection.copy(toDirection);
  if (toDirection.lengthSq() === 0) toDirection.copy(fromDirection);
  rotation.setFromUnitVectors(fromDirection, toDirection);
  partialRotation.slerpQuaternions(originRotation, rotation, amount);
  return target.copy(fromDirection).applyQuaternion(partialRotation).normalize()
    .multiplyScalar(radius + Math.sin(amount * Math.PI) * arcHeight);
}
