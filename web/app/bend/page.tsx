"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { runManual, type MachineResult, type Command, type ManualBend } from "../../lib/api";
import { AXES, freshAxes, applyCmd } from "../../lib/machine";
import dynamic from "next/dynamic";

const Conduit3D = dynamic(() => import("../../components/Conduit3D"), {
  ssr: false,
  loading: () => <div className="empty" style={{ height: 380 }}>Loading 3-D viewer…</div>,
});

const STANDARD = [22.5, 30, 45, 90];
const clampAngle = (v: number) => Math.max(0, Math.min(90, isNaN(v) ? 0 : v));
const cell: React.CSSProperties = { width: 96, padding: "8px 10px", borderRadius: 8, border: "1px solid var(--border-2)", background: "var(--surface)", color: "var(--ink)", fontSize: 14 };

export default function BendBuilder() {
  const [count, setCount] = useState(1);
  const [bends, setBends] = useState<ManualBend[]>(
    Array.from({ length: 4 }, () => ({ angle: 45, roll: 0, distance: 12 })));
  const set = (i: number, k: keyof ManualBend, v: number) =>
    setBends((bs) => bs.map((b, j) => (j === i ? { ...b, [k]: v } : b)));

  const [phase, setPhase] = useState<"idle" | "loading" | "run" | "done">("idle");
  const [res, setRes] = useState<MachineResult | null>(null);
  const [shown, setShown] = useState(0);
  const [paused, setPaused] = useState(false);
  const [view3d, setView3d] = useState(true);
  const consoleRef = useRef<HTMLDivElement>(null);
  const diagRef = useRef<HTMLDivElement>(null);

  const run = useCallback(async () => {
    setPhase("loading"); setRes(null); setShown(0); setPaused(false);
    try {
      const r = await runManual(bends.slice(0, count));
      if (!r.ok) { setPhase("idle"); alert(r.error || "Run failed"); return; }
      setRes(r); setShown(0); setPhase("run");
    } catch { setPhase("idle"); alert("Couldn't reach the machine API."); }
  }, [bends, count]);

  useEffect(() => {
    if (phase !== "run" || !res || paused) return;
    const total = res.commands.length;
    const per = Math.max(1, Math.floor(total / 120));
    const id = setInterval(() => setShown((s) => {
      const next = s + per;
      if (next >= total) { clearInterval(id); setPhase("done"); return total; }
      return next;
    }), 55);
    return () => clearInterval(id);
  }, [phase, res, paused]);

  useEffect(() => { if (consoleRef.current) consoleRef.current.scrollTop = consoleRef.current.scrollHeight; }, [shown]);

  // light up the diagram's bends as the program plays
  useEffect(() => {
    const el = diagRef.current;
    if (!el || !res) return;
    const dots = el.querySelectorAll(".bd");
    const n = dots.length;
    if (!n) return;
    const cur = Math.min(n - 1, Math.floor((res.commands.length ? shown / res.commands.length : 0) * n));
    dots.forEach((d, i) => {
      d.classList.toggle("done", phase === "done" || i < cur);
      d.classList.toggle("active", phase === "run" && i === cur);
    });
  }, [shown, phase, res]);

  const axes = useMemo(() => {
    const ax = freshAxes();
    if (res) res.commands.slice(0, shown).forEach((c) => applyCmd(ax, c.cmd));
    return ax;
  }, [res, shown]);

  const total = res?.commands.length ?? 0;
  const pct = total ? Math.round((shown / total) * 100) : 0;
  const tail = res ? res.commands.slice(Math.max(0, shown - 200), shown) : [];

  return (
    <main className="wrap">
      <div className="crumbs"><Link href="/">Jobs</Link> / New bend</div>
      <h1>Create a bend</h1>
      <p className="sub">Build a bend program by hand and run it on the machine — no model needed.</p>

      <div className="panel">
        <div className="row" style={{ gap: 10, marginBottom: 18 }}>
          <span className="muted" style={{ fontSize: 13 }}>Number of bends</span>
          <div className="seg">
            {[1, 2, 3, 4].map((n) => (
              <button key={n} className={count === n ? "on" : ""} onClick={() => setCount(n)}>{n}</button>
            ))}
          </div>
        </div>

        {count === 1 ? (
          <div>
            <label className="muted" style={{ fontSize: 13 }}>Bend angle</label>
            <div className="row" style={{ marginTop: 8, alignItems: "center", gap: 8 }}>
              <input type="number" min={0} max={90} step={0.5} value={bends[0].angle}
                onChange={(e) => set(0, "angle", clampAngle(parseFloat(e.target.value)))}
                style={{ ...cell, width: 130, fontSize: 20, fontWeight: 700, color: "var(--accent-text)" }} />
              <span className="muted" style={{ fontSize: 18 }}>degrees</span>
            </div>
            <div className="row" style={{ marginTop: 12, gap: 8, alignItems: "center" }}>
              <span className="muted" style={{ fontSize: 12.5 }}>Standard angles</span>
              {STANDARD.map((s) => (
                <button key={s} className={`btn ghost sm ${bends[0].angle === s ? "" : ""}`} onClick={() => set(0, "angle", s)}>{s}&deg;</button>
              ))}
            </div>
            <p className="muted" style={{ fontSize: 12.5, marginTop: 12 }}>Any angle 0&ndash;90&deg;, in 0.5&deg; steps.</p>
          </div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="tbl">
              <thead>
                <tr><th>Bend</th><th>Angle (&deg;)</th><th>Roll (&deg;)</th><th>Distance to bend (in)</th></tr>
              </thead>
              <tbody>
                {bends.slice(0, count).map((b, i) => (
                  <tr key={i}>
                    <td><b style={{ color: "var(--accent-text)" }}>#{i + 1}</b></td>
                    <td><input type="number" min={0} max={90} step={0.5} value={b.angle}
                      onChange={(e) => set(i, "angle", clampAngle(parseFloat(e.target.value)))} style={cell} /></td>
                    <td><input type="number" step={0.5} value={b.roll}
                      onChange={(e) => set(i, "roll", parseFloat(e.target.value) || 0)} style={cell} /></td>
                    <td><input type="number" min={0} step={0.5} value={b.distance}
                      onChange={(e) => set(i, "distance", Math.max(0, parseFloat(e.target.value) || 0))} style={cell} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted" style={{ fontSize: 12.5, marginTop: 10 }}>
              Roll is the rotation into each bend&rsquo;s plane; distance is the straight fed before it. (Layout to be finalized with the contractor.)
            </p>
          </div>
        )}

        <div className="row" style={{ marginTop: 18 }}>
          <button className="btn green" onClick={run} disabled={phase === "loading" || phase === "run"}>
            {phase === "loading" || phase === "run" ? <><span className="spin" /> Running…</> : "▶ Run on machine"}
          </button>
          <span className="muted" style={{ fontSize: 12.5 }}>Simulation only — drives the ClearCore protocol; nothing physical moves.</span>
        </div>
      </div>

      {res && (
        <div className="machine" style={{ marginTop: 18 }}>
          <div>
            {(res.path || res.svg) && (
              <div className="panel" style={{ padding: 12, marginBottom: 14 }}>
                <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
                  <span className="muted" style={{ fontSize: 12 }}>BEND SHAPE{view3d ? " — drag to orbit" : " — lights up as it runs"}</span>
                  <div className="seg">
                    <button className={view3d ? "on" : ""} onClick={() => setView3d(true)} disabled={!res.path}>3D</button>
                    <button className={!view3d ? "on" : ""} onClick={() => setView3d(false)} disabled={!res.svg}>2D</button>
                  </div>
                </div>
                {view3d && res.path
                  ? <Conduit3D verts={res.path.verts} angles={res.path.angles} />
                  : <div className="diagram" ref={diagRef} dangerouslySetInnerHTML={{ __html: res.svg || "" }} />}
              </div>
            )}
            <div className="progress"><div style={{ width: `${pct}%` }} /></div>
            <div className="row" style={{ justifyContent: "space-between", fontSize: 12.5 }}>
              <span className="muted">{shown} / {total} commands</span>
              {phase === "run"
                ? <button className="btn ghost sm" onClick={() => setPaused((p) => !p)}>{paused ? "▶ Resume" : "❚❚ Pause"}</button>
                : <button className="btn ghost sm" onClick={run}>↺ Run again</button>}
            </div>
            <div className="axes">
              {AXES.map((n) => (
                <div className={`axis ${axes[n].enabled ? "enabled" : ""}`} key={n}>
                  <div className="name">{n}</div>
                  <div className="val">{Math.round(axes[n].position).toLocaleString()}</div>
                  <div className={`en ${axes[n].enabled ? "" : "off"}`}>{axes[n].enabled ? "● enabled" : "○ disabled"}</div>
                </div>
              ))}
            </div>
            {phase === "done" && (
              <div className={`banner ${res.warnings.length ? "warn" : "ok"}`} style={{ marginTop: 14 }}>
                {res.warnings.length
                  ? <><b>Completed with {res.warnings.length} warning(s).</b></>
                  : <><b>✓ Bend program complete.</b> {res.counts.commands} firmware commands, no warnings.</>}
              </div>
            )}
          </div>
          <div>
            <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>FIRMWARE COMMAND STREAM (board · command → response)</div>
            <div className="console" ref={consoleRef}>
              {tail.map((c: Command, i) => {
                const isErr = c.response.startsWith("ERR");
                return (
                  <div className="line" key={i}>
                    <span className={c.board === 2 ? "b2" : "hd"}>{c.board}</span>{"  "}
                    {c.cmd}{"  "}<span className={isErr ? "err" : "resp"}>→ {c.response}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
