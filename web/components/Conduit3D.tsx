"use client";

import { useEffect, useMemo, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, Bounds, Html, GizmoHelper, GizmoViewport } from "@react-three/drei";
import * as THREE from "three";

export type Path3D = { verts: number[][]; angles: number[]; cuts?: number[] };
type Props = Path3D & { progress?: number };  // progress 0..1 reveals the tube as it forms

const STICK_COLORS = ["#2f9bd6", "#8a6cf0", "#e0a53a", "#37b3ab", "#ee7b3a", "#d24d9a", "#7c8ba0"];
const seglen = (a: number[], b: number[]) => Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);

function tubeGeom(sv: THREE.Vector3[]) {
  const curve = sv.length === 2
    ? new THREE.LineCurve3(sv[0], sv[1])
    : new THREE.CatmullRomCurve3(sv, false, "centripetal", 0.5);
  return new THREE.TubeGeometry(curve, Math.max(24, sv.length * 16), 0.14, 14, false);
}

/* Recentre + scale, split into 10-ft sticks at the cut distances, locate couplers,
   and expose arc-length fractions so the run can be revealed as it forms. */
function build(verts: number[][], cuts: number[]) {
  const V = verts.map((v) => new THREE.Vector3(v[0], v[2], v[1]));
  const box = new THREE.Box3().setFromPoints(V);
  const c = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const s = 10 / (Math.max(size.x, size.y, size.z) || 1);
  const tf = (v: number[]) => new THREE.Vector3(v[0], v[2], v[1]).sub(c).multiplyScalar(s);

  const cum = [0];
  for (let i = 0; i < verts.length - 1; i++) cum.push(cum[i] + seglen(verts[i], verts[i + 1]));
  const total = cum[cum.length - 1] || 1;
  const pointAt = (d: number): number[] => {
    if (d <= 0) return verts[0];
    if (d >= total) return verts[verts.length - 1];
    for (let i = 0; i < verts.length - 1; i++)
      if (cum[i] <= d && d <= cum[i + 1]) {
        const t = (d - cum[i]) / ((cum[i + 1] - cum[i]) || 1);
        const a = verts[i], b = verts[i + 1];
        return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
      }
    return verts[verts.length - 1];
  };
  const dirAt = (d: number): number[] => {
    for (let i = 0; i < verts.length - 1; i++)
      if (cum[i] <= d && d <= cum[i + 1]) return [verts[i + 1][0] - verts[i][0], verts[i + 1][1] - verts[i][1], verts[i + 1][2] - verts[i][2]];
    return [1, 0, 0];
  };

  const bounds = [0, ...cuts, total];
  const sticks: THREE.Vector3[][] = [];
  const stickRanges: { start: number; end: number }[] = [];
  for (let k = 0; k < bounds.length - 1; k++) {
    const lo = bounds[k], hi = bounds[k + 1];
    const raw: number[][] = [pointAt(lo)];
    for (let i = 0; i < verts.length; i++) if (cum[i] > lo + 1e-6 && cum[i] < hi - 1e-6) raw.push(verts[i]);
    raw.push(pointAt(hi));
    sticks.push(raw.map(tf));
    stickRanges.push({ start: lo / total, end: hi / total });
  }

  const couplers = cuts.map((d) => {
    const o = dirAt(d);
    const dir = new THREE.Vector3(o[0], o[2], o[1]).normalize();
    return {
      pos: tf(pointAt(d)),
      quat: new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir),
      frac: d / total,
    };
  });

  const localVerts = verts.map(tf);
  const bendFrac: number[] = [];
  for (let i = 1; i < verts.length - 1; i++) bendFrac.push(cum[i] / total);
  const tipAt = (f: number) => tf(pointAt(Math.max(0, Math.min(1, f)) * total));

  return { sticks, stickRanges, couplers, localVerts, bendFrac, tipAt };
}

function Scene({ verts, angles, cuts, progress = 1 }: Props) {
  const [hovered, setHovered] = useState<number | null>(null);
  const { sticks, stickRanges, couplers, localVerts, bendFrac, tipAt } = useMemo(
    () => build(verts, cuts || []), [verts, cuts]);

  const rolls = useMemo(() => {
    const p = localVerts;
    const dirs: THREE.Vector3[] = [];
    for (let i = 1; i < p.length; i++) dirs.push(p[i].clone().sub(p[i - 1]).normalize());
    const normals: (THREE.Vector3 | null)[] = [];
    for (let i = 1; i < p.length - 1; i++) {
      const n = new THREE.Vector3().crossVectors(dirs[i - 1], dirs[i]);
      normals.push(n.length() > 1e-4 ? n.normalize() : null);
    }
    return normals.map((n, i) => {
      if (i === 0 || !n || !normals[i - 1]) return 0;
      return Math.round(THREE.MathUtils.radToDeg(Math.acos(THREE.MathUtils.clamp(normals[i - 1]!.dot(n), -1, 1))));
    });
  }, [localVerts]);

  const geoms = useMemo(() => sticks.map((sv) => (sv.length >= 2 ? tubeGeom(sv) : null)), [sticks]);

  // reveal each stick tube up to the current progress (drawRange — no rebuild)
  useEffect(() => {
    geoms.forEach((g, i) => {
      if (!g || !g.index) return;
      const total = g.index.count;
      const r = stickRanges[i];
      const f = Math.max(0, Math.min(1, (progress - r.start) / Math.max(1e-6, r.end - r.start)));
      g.setDrawRange(0, f >= 1 ? Infinity : Math.floor((total * f) / 6) * 6);
    });
  }, [progress, geoms, stickRanges]);

  const bends = localVerts.slice(1, -1);
  const forming = progress < 0.999;
  const tip = forming ? tipAt(progress) : null;

  return (
    <Bounds fit clip observe margin={1.25}>
      <group>
        {geoms.map((g, i) => g && (
          <mesh key={i} geometry={g}>
            <meshStandardMaterial color={STICK_COLORS[i % STICK_COLORS.length]} metalness={0.25} roughness={0.45} />
          </mesh>
        ))}
        {couplers.map((cp, i) => cp.frac <= progress && (
          <mesh key={i} position={cp.pos} quaternion={cp.quat}>
            <cylinderGeometry args={[0.21, 0.21, 0.55, 18]} />
            <meshStandardMaterial color="#d3dbd9" metalness={0.75} roughness={0.25} />
          </mesh>
        ))}
        {/* forming tip */}
        {tip && (
          <mesh position={[tip.x, tip.y, tip.z]}>
            <sphereGeometry args={[0.24, 18, 18]} />
            <meshStandardMaterial color="#28e0e8" emissive="#0bd" emissiveIntensity={0.9} />
          </mesh>
        )}
        {/* start / end */}
        {[localVerts[0], localVerts[localVerts.length - 1]].map((p, i) => (i === 1 && forming ? null : (
          <group key={i} position={[p.x, p.y, p.z]}>
            <mesh>
              <sphereGeometry args={[0.26, 18, 18]} />
              <meshStandardMaterial color="#2f9e63" emissive="#154" emissiveIntensity={0.3} />
            </mesh>
            <Html center distanceFactor={11} zIndexRange={[50, 0]} style={{ pointerEvents: "none" }}>
              <span style={{
                display: "inline-block", transform: "translateY(-150%)",
                color: "#7ee6a3", fontSize: 12, fontWeight: 600, letterSpacing: ".03em",
                fontFamily: "var(--font-mono, monospace)", textShadow: "0 1px 4px #000, 0 0 4px #000",
              }}>{i === 0 ? "START" : "END"}</span>
            </Html>
          </group>
        )))}
        {/* bends — only those reached; label the hovered one */}
        {bends.map((p, i) => bendFrac[i] <= progress + 1e-6 && (
          <group key={i} position={[p.x, p.y, p.z]}>
            <mesh
              onPointerOver={(e) => { e.stopPropagation(); setHovered(i); document.body.style.cursor = "pointer"; }}
              onPointerOut={() => { setHovered((h) => (h === i ? null : h)); document.body.style.cursor = "default"; }}
            >
              <sphereGeometry args={[hovered === i ? 0.3 : 0.2, 18, 18]} />
              <meshStandardMaterial color={hovered === i ? "#ffd24d" : "#ff5a4d"} emissive="#611" emissiveIntensity={0.35} />
            </mesh>
            {hovered === i && (
              <Html center distanceFactor={10} zIndexRange={[100, 0]} style={{ pointerEvents: "none" }}>
                <div style={{
                  transform: "translateY(-150%)", background: "rgba(13,20,19,.92)", padding: "3px 9px",
                  borderRadius: 8, fontFamily: "var(--font-mono, monospace)", border: "1px solid #00c2cb88",
                  whiteSpace: "nowrap", textAlign: "center", lineHeight: 1.3, boxShadow: "0 4px 14px rgba(0,0,0,.5)",
                }}>
                  <div style={{ color: "#eafcff", fontSize: 13, fontWeight: 600 }}>bend {i + 1}: {angles[i]}&deg;</div>
                  {rolls[i] ? <div style={{ color: "#5fdbe3", fontSize: 11 }}>roll {rolls[i]}&deg;</div> : null}
                </div>
              </Html>
            )}
          </group>
        ))}
      </group>
    </Bounds>
  );
}

export default function Conduit3D({ verts, angles, cuts, progress = 1 }: Props) {
  if (!verts || verts.length < 2) {
    return <div style={{ padding: 24, color: "var(--muted)", fontSize: 13 }}>No 3-D path for this run.</div>;
  }
  return (
    <div style={{ position: "relative", height: 380, borderRadius: 10, overflow: "hidden", background: "#0e1514", border: "1px solid var(--border)" }}>
      <Canvas camera={{ position: [9, 7, 11], fov: 40 }} dpr={[1, 2]}>
        <hemisphereLight args={["#cfeff2", "#0a1211", 0.7]} />
        <directionalLight position={[10, 16, 8]} intensity={1.15} />
        <directionalLight position={[-8, -3, -6]} intensity={0.35} />
        <gridHelper args={[60, 30, "#1e3a38", "#152825"]} position={[0, -4, 0]} />
        <Scene verts={verts} angles={angles} cuts={cuts} progress={progress} />
        <OrbitControls makeDefault enableDamping dampingFactor={0.1} />
        <GizmoHelper alignment="bottom-right" margin={[64, 64]}>
          <GizmoViewport axisColors={["#e06", "#0c9", "#29f"]} labelColor="#dfe" />
        </GizmoHelper>
      </Canvas>
      <div style={{
        position: "absolute", left: 12, bottom: 10, fontSize: 11.5, color: "#7fa39f",
        fontFamily: "var(--font-mono, monospace)", pointerEvents: "none", lineHeight: 1.5,
      }}>
        drag to orbit &middot; each color = one 10-ft stick &middot; silver collar = coupler<br />hover a bend for angle &amp; roll
      </div>
    </div>
  );
}
