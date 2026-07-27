"use client";

import { useMemo } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, ContactShadows } from "@react-three/drei";
import * as THREE from "three";

const clamp = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x));
const RS = 1.5;      // bend-shoe radius
const CR = 0.19;     // conduit radius

function conduitPath(thetaDeg: number) {
  const th = THREE.MathUtils.degToRad(clamp(thetaDeg, 0, 120));
  const pts = [new THREE.Vector3(-6, 0, RS), new THREE.Vector3(-1.1, 0, RS)];
  if (th < 0.02) { pts.push(new THREE.Vector3(5, 0, RS)); return pts; }
  const N = Math.max(2, Math.round(THREE.MathUtils.radToDeg(th) / 7));
  for (let j = 0; j <= N; j++) {
    const a = Math.PI / 2 - th * (j / N);
    pts.push(new THREE.Vector3(RS * Math.cos(a), 0, RS * Math.sin(a)));
  }
  const ae = Math.PI / 2 - th;
  const exit = new THREE.Vector3(RS * Math.cos(ae), 0, RS * Math.sin(ae));
  const dir = new THREE.Vector3(Math.sin(ae), 0, -Math.cos(ae));
  pts.push(exit.clone().add(dir.multiplyScalar(4.8)));
  return pts;
}

function Bar({ from, to, radius, color, metal = 0.4, rough = 0.4 }:
  { from: THREE.Vector3; to: THREE.Vector3; radius: number; color: string; metal?: number; rough?: number }) {
  const mid = from.clone().add(to).multiplyScalar(0.5);
  const dir = to.clone().sub(from);
  const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.clone().normalize());
  return (
    <mesh position={mid} quaternion={q} castShadow>
      <cylinderGeometry args={[radius, radius, dir.length(), 20]} />
      <meshStandardMaterial color={color} metalness={metal} roughness={rough} />
    </mesh>
  );
}

function Bender({ bend, squeeze }: { bend: number; squeeze: boolean }) {
  const th = clamp(bend, 0, 120);
  const pts = useMemo(() => conduitPath(th), [th]);
  const tube = useMemo(() =>
    new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts, false, "centripetal", 0.5), Math.max(48, pts.length * 5), CR, 14, false),
    [pts]);

  const ae = Math.PI / 2 - THREE.MathUtils.degToRad(th);
  const rollR = 0.28;
  const rollerPos = new THREE.Vector3((RS + CR + rollR) * Math.cos(ae), 0, (RS + CR + rollR) * Math.sin(ae));
  const clampZ = RS + CR + (squeeze ? 0.02 : 0.55);

  return (
    <group>
      {/* base + frame */}
      <mesh position={[-0.5, -1.35, 0]} receiveShadow castShadow>
        <boxGeometry args={[12, 0.5, 5.5]} /><meshStandardMaterial color="#48555a" metalness={0.35} roughness={0.65} />
      </mesh>
      <mesh position={[0, -0.6, 0]} castShadow><boxGeometry args={[1.4, 1.6, 3.6]} /><meshStandardMaterial color="#59656b" metalness={0.4} roughness={0.55} /></mesh>

      {/* bending shoe (die) + groove */}
      <mesh rotation={[Math.PI / 2, 0, 0]} castShadow>
        <cylinderGeometry args={[RS, RS, 0.72, 48]} /><meshStandardMaterial color="#7b868c" metalness={0.5} roughness={0.38} />
      </mesh>
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[RS, CR * 1.25, 14, 60]} /><meshStandardMaterial color="#3a4247" metalness={0.4} roughness={0.5} />
      </mesh>
      <mesh position={[0, 0.42, 0]}><cylinderGeometry args={[0.16, 0.16, 0.35, 16]} /><meshStandardMaterial color="#12d3db" metalness={0.3} roughness={0.4} emissive="#00b3bb" emissiveIntensity={0.55} /></mesh>

      {/* the conduit — bright galvanized */}
      <mesh geometry={tube} castShadow>
        <meshStandardMaterial color="#cdd7db" metalness={0.55} roughness={0.3} />
      </mesh>

      {/* bend arm + pressure roller */}
      <Bar from={new THREE.Vector3(0, 0, 0)} to={rollerPos} radius={0.13} color="#17c2ca" metal={0.35} />
      <mesh position={[rollerPos.x, 0, rollerPos.z]} castShadow>
        <cylinderGeometry args={[rollR, rollR, 0.6, 24]} /><meshStandardMaterial color="#8b959b" metalness={0.5} roughness={0.4} />
      </mesh>

      {/* clamp / follow bar */}
      <group position={[-2.6, 0, 0]}>
        <mesh position={[0, 0, clampZ + 0.35]} castShadow>
          <boxGeometry args={[1.5, 0.7, 0.6]} /><meshStandardMaterial color={squeeze ? "#17c2ca" : "#6b757b"} metalness={0.4} roughness={0.45} emissive={squeeze ? "#008f96" : "#000"} emissiveIntensity={squeeze ? 0.35 : 0} />
        </mesh>
        {[-1.1, 1.1].map((dx, i) => (
          <mesh key={i} position={[dx, 0, RS - CR - 0.32]} rotation={[0, 0, Math.PI / 2]} castShadow>
            <cylinderGeometry args={[0.34, 0.34, 0.5, 24]} /><meshStandardMaterial color="#7b868c" metalness={0.5} roughness={0.4} />
          </mesh>
        ))}
      </group>

      <ContactShadows position={[0, -1.08, 0]} opacity={0.42} scale={16} blur={2.6} far={4} />
    </group>
  );
}

export default function Bender3D({ bend, squeeze }: { bend: number; squeeze: boolean }) {
  return (
    <div style={{ position: "relative", height: 400, borderRadius: 10, overflow: "hidden", background: "linear-gradient(180deg, #37474a 0%, #1a2422 100%)", border: "1px solid var(--border)" }}>
      <Canvas shadows gl={{ alpha: true }} camera={{ position: [7.5, 6, 9.5], fov: 42 }} dpr={[1, 2]}>
        <ambientLight intensity={0.55} />
        <hemisphereLight args={["#eaf6f6", "#20302e", 1.1]} />
        <directionalLight position={[8, 14, 6]} intensity={1.9} castShadow shadow-mapSize={[1024, 1024]} />
        <directionalLight position={[-7, 5, 9]} intensity={0.85} />
        <directionalLight position={[0, 4, -10]} intensity={0.5} />
        <gridHelper args={[60, 30, "#33544f", "#24403a"]} position={[0, -1.34, 0]} />
        <Bender bend={bend} squeeze={squeeze} />
        <OrbitControls makeDefault enableDamping dampingFactor={0.12} target={[0, 0, 0.5]} />
      </Canvas>
      <div style={{ position: "absolute", left: 12, bottom: 10, fontSize: 11.5, color: "#bcd3d0", fontFamily: "var(--font-mono, monospace)", pointerEvents: "none", textShadow: "0 1px 3px #000" }}>
        the bender working &middot; arm swings to each bend &middot; clamp closes on SQUEEZE &middot; drag to orbit
      </div>
      <div style={{ position: "absolute", top: 10, right: 12, fontFamily: "var(--font-mono, monospace)", fontSize: 12, color: "#eafeff", background: "rgba(13,20,19,.6)", padding: "4px 9px", borderRadius: 7 }}>
        BEND {Math.round(bend)}° &middot; {squeeze ? "CLAMPED" : "open"}
      </div>
    </div>
  );
}
