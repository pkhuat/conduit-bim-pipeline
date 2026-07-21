"use client";

import { useMemo } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, Bounds, Html, GizmoHelper, GizmoViewport } from "@react-three/drei";
import * as THREE from "three";

export type Path3D = { verts: number[][]; angles: number[]; cuts?: number[] };

/* Model space is Z-up (Revit); Three.js is Y-up → map (x,y,z) → (x, z, y). */
function toLocal(verts: number[][]) {
  const pts = verts.map((v) => new THREE.Vector3(v[0], v[2], v[1]));
  const box = new THREE.Box3().setFromPoints(pts);
  const c = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const s = 10 / (Math.max(size.x, size.y, size.z) || 1);
  return pts.map((p) => p.clone().sub(c).multiplyScalar(s));
}

function Scene({ verts, angles }: Path3D) {
  // centre/scale the path, and derive the roll (bend-plane change) at each bend
  const { points, rolls } = useMemo(() => {
    const pts = toLocal(verts);
    const dirs: THREE.Vector3[] = [];
    for (let i = 1; i < pts.length; i++) dirs.push(pts[i].clone().sub(pts[i - 1]).normalize());
    const normals: (THREE.Vector3 | null)[] = [];
    for (let i = 1; i < pts.length - 1; i++) {
      const n = new THREE.Vector3().crossVectors(dirs[i - 1], dirs[i]);
      normals.push(n.length() > 1e-4 ? n.normalize() : null);
    }
    const rolls = normals.map((n, i) => {
      if (i === 0 || !n || !normals[i - 1]) return 0;          // first bend = reference plane
      const d = THREE.MathUtils.clamp(normals[i - 1]!.dot(n), -1, 1);
      return Math.round(THREE.MathUtils.radToDeg(Math.acos(d)));
    });
    return { points: pts, rolls };
  }, [verts]);

  const tube = useMemo(() => {
    if (points.length < 2) return null;
    const curve = new THREE.CatmullRomCurve3(points, false, "centripetal", 0.5);
    return new THREE.TubeGeometry(curve, Math.max(80, points.length * 20), 0.14, 14, false);
  }, [points]);
  if (!tube) return null;
  const bends = points.slice(1, -1);

  return (
    <Bounds fit clip observe margin={1.25}>
      <group>
        <mesh geometry={tube}>
          <meshStandardMaterial color="#00c2cb" metalness={0.35} roughness={0.35} />
        </mesh>
        {/* start / end */}
        {[points[0], points[points.length - 1]].map((p, i) => (
          <mesh key={i} position={[p.x, p.y, p.z]}>
            <sphereGeometry args={[0.26, 18, 18]} />
            <meshStandardMaterial color="#2f9e63" emissive="#154" emissiveIntensity={0.3} />
          </mesh>
        ))}
        {/* bends + angle labels */}
        {bends.map((p, i) => (
          <group key={i} position={[p.x, p.y, p.z]}>
            <mesh>
              <sphereGeometry args={[0.2, 18, 18]} />
              <meshStandardMaterial color="#ff5a4d" emissive="#611" emissiveIntensity={0.3} />
            </mesh>
            <Html center distanceFactor={11} zIndexRange={[10, 0]}>
              <div style={{
                background: "rgba(13,20,19,.86)", padding: "2px 7px", borderRadius: 7,
                fontFamily: "var(--font-mono, monospace)", border: "1px solid #00c2cb55",
                whiteSpace: "nowrap", textAlign: "center", lineHeight: 1.25,
              }}>
                <div style={{ color: "#eafcff", fontSize: 12.5, fontWeight: 600 }}>{angles[i]}&deg;</div>
                {rolls[i] ? <div style={{ color: "#5fdbe3", fontSize: 10.5 }}>roll {rolls[i]}&deg;</div> : null}
              </div>
            </Html>
          </group>
        ))}
      </group>
    </Bounds>
  );
}

export default function Conduit3D({ verts, angles }: Path3D) {
  if (!verts || verts.length < 2) {
    return <div style={{ padding: 24, color: "var(--muted)", fontSize: 13 }}>No 3-D path for this run.</div>;
  }
  return (
    <div style={{ height: 380, borderRadius: 10, overflow: "hidden", background: "#0e1514", border: "1px solid var(--border)" }}>
      <Canvas camera={{ position: [9, 7, 11], fov: 40 }} dpr={[1, 2]}>
        <hemisphereLight args={["#cfeff2", "#0a1211", 0.7]} />
        <directionalLight position={[10, 16, 8]} intensity={1.15} />
        <directionalLight position={[-8, -3, -6]} intensity={0.35} />
        <gridHelper args={[60, 30, "#1e3a38", "#152825"]} position={[0, -4, 0]} />
        <Scene verts={verts} angles={angles} />
        <OrbitControls makeDefault enableDamping dampingFactor={0.1} />
        <GizmoHelper alignment="bottom-right" margin={[64, 64]}>
          <GizmoViewport axisColors={["#e06", "#0c9", "#29f"]} labelColor="#dfe" />
        </GizmoHelper>
      </Canvas>
    </div>
  );
}
