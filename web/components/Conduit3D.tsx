"use client";

import { useEffect, useMemo, useState } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { OrbitControls, Bounds, useBounds, Html, GizmoHelper, GizmoViewport } from "@react-three/drei";
import * as THREE from "three";

export type Path3D = { verts: number[][]; angles: number[]; cuts?: number[]; od_mm?: number | null; bend_radius_mm?: number | null };
type Props = Path3D & { progress?: number };

// Galvanized-conduit shades, alternated per 10-ft stick so it reads as real
// pipe while you can still tell one stick from the next.
const STICK_METAL = ["#c2cacc", "#a9b2b4"];
const seglen = (a: number[], b: number[]) => Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
const clamp = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x));

function ftIn(mm: number) {
  const totIn = mm / 25.4;
  let ft = Math.floor(totIn / 12);
  let inch = Math.round(totIn - ft * 12);
  if (inch === 12) { ft += 1; inch = 0; }
  return ft > 0 ? `${ft}' ${inch}"` : `${inch}"`;
}

/* Replace each sharp interior corner of a polyline with a true circular arc of
   radius R (local units) — the real bend-shoe fillet. */
function fillet(pts: THREE.Vector3[], R: number): THREE.Vector3[] {
  if (pts.length < 3 || R <= 0) return pts.map((p) => p.clone());
  const out = [pts[0].clone()];
  for (let k = 1; k < pts.length - 1; k++) {
    const A = pts[k - 1], B = pts[k], C = pts[k + 1];
    const d1 = A.clone().sub(B).normalize();
    const d2 = C.clone().sub(B).normalize();
    const phi = Math.acos(clamp(d1.dot(d2), -1, 1));   // included angle
    const theta = Math.PI - phi;                       // bend deflection
    if (theta < 0.035 || phi < 0.05) { out.push(B.clone()); continue; }
    const tMax = 0.45 * Math.min(A.distanceTo(B), B.distanceTo(C));
    const t = Math.min(R * Math.tan(theta / 2), tMax);
    const Reff = t / Math.tan(theta / 2);
    const T1 = B.clone().add(d1.clone().multiplyScalar(t));
    const T2 = B.clone().add(d2.clone().multiplyScalar(t));
    const bis = d1.clone().add(d2).normalize();
    const O = B.clone().add(bis.multiplyScalar(Reff / Math.sin(phi / 2)));
    const a = T1.clone().sub(O), b = T2.clone().sub(O);
    const Om = Math.acos(clamp(a.clone().normalize().dot(b.clone().normalize()), -1, 1));
    const N = Math.max(2, Math.round(theta / (Math.PI / 24)));
    out.push(T1.clone());
    if (Om > 1e-3) for (let j = 1; j < N; j++) {
      const u = j / N;
      const s1 = Math.sin((1 - u) * Om) / Math.sin(Om);
      const s2 = Math.sin(u * Om) / Math.sin(Om);
      out.push(O.clone().add(a.clone().multiplyScalar(s1)).add(b.clone().multiplyScalar(s2)));
    }
    out.push(T2.clone());
  }
  out.push(pts[pts.length - 1].clone());
  return out;
}

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
        const t = (d - cum[i]) / ((cum[i + 1] - cum[i]) || 1), a = verts[i], b = verts[i + 1];
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
  const rawSticks: THREE.Vector3[][] = [];
  const stickRanges: { start: number; end: number }[] = [];
  for (let k = 0; k < bounds.length - 1; k++) {
    const lo = bounds[k], hi = bounds[k + 1];
    const raw: number[][] = [pointAt(lo)];
    for (let i = 0; i < verts.length; i++) if (cum[i] > lo + 1e-6 && cum[i] < hi - 1e-6) raw.push(verts[i]);
    raw.push(pointAt(hi));
    rawSticks.push(raw.map(tf));
    stickRanges.push({ start: lo / total, end: hi / total });
  }

  const couplers = cuts.map((d) => {
    const o = dirAt(d);
    const dir = new THREE.Vector3(o[0], o[2], o[1]).normalize();
    return { pos: tf(pointAt(d)), quat: new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir), frac: d / total };
  });

  const localVerts = verts.map(tf);
  const bendFrac: number[] = [];
  for (let i = 1; i < verts.length - 1; i++) bendFrac.push(cum[i] / total);
  const segs = [];
  for (let i = 0; i < verts.length - 1; i++)
    segs.push({ mid: localVerts[i].clone().add(localVerts[i + 1]).multiplyScalar(0.5), len: cum[i + 1] - cum[i], frac: (cum[i] + cum[i + 1]) / 2 / total });
  const tipAt = (f: number) => tf(pointAt(clamp(f, 0, 1) * total));

  return { rawSticks, stickRanges, couplers, localVerts, bendFrac, segs, tipAt, s };
}

function CameraRig({ view }: { view: { dir: string; k: number } | null }) {
  const { camera, controls } = useThree() as any;
  useEffect(() => {
    if (!view) return;
    const D = 16;
    const pos: Record<string, [number, number, number]> = {
      iso: [D * 0.7, D * 0.55, D * 0.85], top: [0, D, 0.001], front: [0, 0, D], side: [D, 0, 0],
    };
    const p = pos[view.dir]; if (!p) return;
    camera.position.set(p[0], p[1], p[2]);
    if (controls) { controls.target.set(0, 0, 0); controls.update(); }
    camera.lookAt(0, 0, 0);
  }, [view, camera, controls]);
  return null;
}

function FitTrigger({ k }: { k: number }) {
  const api = useBounds();
  useEffect(() => { if (k > 0) api.refresh().clip().fit(); }, [k]); // eslint-disable-line
  return null;
}

function Scene({ verts, angles, cuts, progress = 1, odMm, bendRadiusMm, dims, fitK }:
  Props & { odMm?: number | null; bendRadiusMm?: number | null; dims: boolean; fitK: number }) {
  const [hovered, setHovered] = useState<number | null>(null);
  const d = useMemo(() => build(verts, cuts || []), [verts, cuts]);
  const { rawSticks, stickRanges, couplers, localVerts, bendFrac, segs, tipAt, s } = d;

  const tubeR = clamp((odMm && odMm > 0 ? odMm / 2 : 12) * s, 0.045, 0.5);
  const bendR = clamp((bendRadiusMm && bendRadiusMm > 0 ? bendRadiusMm : 60) * s, tubeR * 1.4, 6);

  const rolls = useMemo(() => {
    const p = localVerts, dirs: THREE.Vector3[] = [];
    for (let i = 1; i < p.length; i++) dirs.push(p[i].clone().sub(p[i - 1]).normalize());
    const normals: (THREE.Vector3 | null)[] = [];
    for (let i = 1; i < p.length - 1; i++) {
      const n = new THREE.Vector3().crossVectors(dirs[i - 1], dirs[i]);
      normals.push(n.length() > 1e-4 ? n.normalize() : null);
    }
    return normals.map((n, i) => (i === 0 || !n || !normals[i - 1]) ? 0
      : Math.round(THREE.MathUtils.radToDeg(Math.acos(THREE.MathUtils.clamp(normals[i - 1]!.dot(n), -1, 1)))));
  }, [localVerts]);

  const geoms = useMemo(() => rawSticks.map((sv) => {
    if (sv.length < 2) return null;
    const pts = fillet(sv, bendR);
    const curve = new THREE.CatmullRomCurve3(pts, false, "centripetal", 0.5);
    return new THREE.TubeGeometry(curve, Math.max(40, pts.length * 8), tubeR, 16, false);
  }), [rawSticks, bendR, tubeR]);

  useEffect(() => {
    geoms.forEach((g, i) => {
      if (!g || !g.index) return;
      const total = g.index.count, r = stickRanges[i];
      const f = clamp((progress - r.start) / Math.max(1e-6, r.end - r.start), 0, 1);
      g.setDrawRange(0, f >= 1 ? Infinity : Math.floor((total * f) / 6) * 6);
    });
  }, [progress, geoms, stickRanges]);

  const bends = localVerts.slice(1, -1);
  // Show the always-on angle chips only on simple runs; on dense runs they'd
  // overlap, so hide them and let the operator hover instead.
  const showTags = bends.length <= 5;
  const forming = progress < 0.999;
  const tip = forming ? tipAt(progress) : null;
  const markR = Math.max(0.16, tubeR * 1.6);

  return (
    <Bounds fit clip observe margin={1.25}>
      <FitTrigger k={fitK} />
      <group>
        {geoms.map((g, i) => g && (
          <mesh key={i} geometry={g}>
            <meshStandardMaterial color={STICK_METAL[i % STICK_METAL.length]} metalness={0.82} roughness={0.38} />
          </mesh>
        ))}
        {couplers.map((cp, i) => cp.frac <= progress && (
          <mesh key={i} position={cp.pos} quaternion={cp.quat}>
            <cylinderGeometry args={[tubeR * 1.5, tubeR * 1.5, tubeR * 4, 20]} />
            <meshStandardMaterial color="#d3dbd9" metalness={0.8} roughness={0.22} />
          </mesh>
        ))}
        {tip && (
          <mesh position={[tip.x, tip.y, tip.z]}>
            <sphereGeometry args={[markR, 18, 18]} />
            <meshStandardMaterial color="#28e0e8" emissive="#0bd" emissiveIntensity={0.9} />
          </mesh>
        )}
        {dims && segs.map((sg, i) => sg.frac <= progress + 1e-6 && sg.len > 1 && (
          <Html key={i} position={[sg.mid.x, sg.mid.y, sg.mid.z]} center distanceFactor={12} zIndexRange={[20, 0]} style={{ pointerEvents: "none" }}>
            <span style={{
              background: "rgba(13,20,19,.8)", color: "#cfe6d8", padding: "1px 6px", borderRadius: 5,
              fontSize: 10.5, fontFamily: "var(--font-mono, monospace)", whiteSpace: "nowrap", border: "1px solid #ffffff18",
            }}>{ftIn(sg.len)}</span>
          </Html>
        ))}
        {[localVerts[0], localVerts[localVerts.length - 1]].map((p, i) => (i === 1 && forming ? null : (
          <group key={i} position={[p.x, p.y, p.z]}>
            <mesh><sphereGeometry args={[markR * 1.25, 18, 18]} /><meshStandardMaterial color="#2f9e63" emissive="#154" emissiveIntensity={0.3} /></mesh>
            <Html center distanceFactor={11} zIndexRange={[50, 0]} style={{ pointerEvents: "none" }}>
              <span style={{ display: "inline-block", transform: "translateY(-150%)", color: "#7ee6a3", fontSize: 12, fontWeight: 600, letterSpacing: ".03em", fontFamily: "var(--font-mono, monospace)", textShadow: "0 1px 4px #000, 0 0 4px #000" }}>{i === 0 ? "START" : "END"}</span>
            </Html>
          </group>
        )))}
        {bends.map((p, i) => bendFrac[i] <= progress + 1e-6 && (
          <group key={i} position={[p.x, p.y, p.z]}>
            <mesh
              onPointerOver={(e) => { e.stopPropagation(); setHovered(i); document.body.style.cursor = "pointer"; }}
              onPointerOut={() => { setHovered((h) => (h === i ? null : h)); document.body.style.cursor = "default"; }}>
              <sphereGeometry args={[hovered === i ? markR * 1.4 : markR, 18, 18]} />
              <meshStandardMaterial color={hovered === i ? "#ffd24d" : "#ff5a4d"} emissive="#611" emissiveIntensity={0.35} />
            </mesh>
            {/* always-on: a small angle chip so every bend reads at a glance.
                on hover: the full detail (roll + bend number), enlarged. keeping
                the always-on chip tiny stops the labels piling up on dense runs. */}
            {hovered === i ? (
              <Html center distanceFactor={9} zIndexRange={[130, 0]} style={{ pointerEvents: "none" }}>
                <div style={{ transform: "translateY(-165%)", background: "rgba(13,20,19,.95)", padding: "3px 10px", borderRadius: 8, fontFamily: "var(--font-mono, monospace)", border: "1px solid #00c2cb99", whiteSpace: "nowrap", textAlign: "center", lineHeight: 1.25, boxShadow: "0 4px 14px rgba(0,0,0,.55)" }}>
                  <span style={{ color: "#eafcff", fontSize: 14, fontWeight: 700 }}>{angles[i]}&deg;</span>
                  {rolls[i] ? <span style={{ color: "#5fdbe3", fontSize: 11, marginLeft: 6 }}>&#8635;&nbsp;{rolls[i]}&deg; roll</span> : null}
                  <div style={{ color: "#8fb0ab", fontSize: 9, letterSpacing: ".08em", marginTop: 1 }}>BEND {i + 1}</div>
                </div>
              </Html>
            ) : showTags ? (
              <Html center distanceFactor={17} zIndexRange={[60, 0]} style={{ pointerEvents: "none" }}>
                <span style={{ transform: "translateY(-150%)", display: "inline-block", background: "rgba(13,20,19,.78)", color: "#fff", padding: "0 5px", borderRadius: 5, fontFamily: "var(--font-mono, monospace)", fontSize: 12, fontWeight: 700, border: "1px solid #ff8a4d55", whiteSpace: "nowrap" }}>{angles[i]}&deg;</span>
              </Html>
            ) : null}
          </group>
        ))}
      </group>
    </Bounds>
  );
}

export default function Conduit3D({ verts, angles, cuts, progress = 1, od_mm, bend_radius_mm }: Props) {
  const [dims, setDims] = useState(true);
  const [view, setView] = useState<{ dir: string; k: number } | null>(null);
  const [fitK, setFitK] = useState(0);
  if (!verts || verts.length < 2) return <div style={{ padding: 24, color: "var(--muted)", fontSize: 13 }}>No 3-D path for this run.</div>;

  const btn: React.CSSProperties = { background: "rgba(20,30,29,.85)", color: "#bfeef0", border: "1px solid #ffffff1f", borderRadius: 7, padding: "4px 9px", fontSize: 11.5, fontFamily: "var(--font-mono, monospace)", cursor: "pointer" };

  return (
    <div style={{ position: "relative", height: 400, borderRadius: 10, overflow: "hidden", background: "#0e1514", border: "1px solid var(--border)" }}>
      <Canvas camera={{ position: [11, 8.5, 13], fov: 40 }} dpr={[1, 2]}>
        <hemisphereLight args={["#cfeff2", "#0a1211", 0.7]} />
        <directionalLight position={[10, 16, 8]} intensity={1.15} />
        <directionalLight position={[-8, -3, -6]} intensity={0.35} />
        <gridHelper args={[60, 30, "#1e3a38", "#152825"]} position={[0, -4, 0]} />
        <Scene verts={verts} angles={angles} cuts={cuts} progress={progress}
          odMm={od_mm} bendRadiusMm={bend_radius_mm} dims={dims} fitK={fitK} />
        <CameraRig view={view} />
        <OrbitControls makeDefault enableDamping dampingFactor={0.1} />
        <GizmoHelper alignment="bottom-right" margin={[60, 60]}>
          <GizmoViewport axisColors={["#e06", "#0c9", "#29f"]} labelColor="#dfe" />
        </GizmoHelper>
      </Canvas>

      <div style={{ position: "absolute", top: 10, right: 10, display: "flex", gap: 5, flexWrap: "wrap", justifyContent: "flex-end" }}>
        {(["iso", "top", "front", "side"] as const).map((v) => (
          <button key={v} style={btn} onClick={() => setView({ dir: v, k: Date.now() })}>{v}</button>
        ))}
        <button style={btn} onClick={() => setFitK((k) => k + 1)}>fit</button>
        <button style={{ ...btn, ...(dims ? { background: "#0a6f74", color: "#eafeff", borderColor: "#00c2cb" } : {}) }} onClick={() => setDims((x) => !x)}>dims</button>
      </div>

      <div style={{ position: "absolute", left: 12, bottom: 10, fontSize: 11.5, color: "#7fa39f", fontFamily: "var(--font-mono, monospace)", pointerEvents: "none", lineHeight: 1.5 }}>
        drag to orbit &middot; hover any bend for its angle &amp; roll &middot; silver collar = cut &amp; couple by hand<br />numbers = straight-run lengths (toggle <b style={{ color: dims ? "#7fe" : "#7fa39f" }}>dims</b>) &middot; top / front / side change the view
      </div>
    </div>
  );
}
