"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { getMachineMode, runMachineProgram, machineEstop, getXbox, setXbox, getMachineState,
  getMachineLive, machineZero,
  type MachineResult, type Command, type ManualBend, type MachineMode,
  type XboxStatus, type MachineState, type LiveTwin } from "../../lib/api";
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
  const [mode, setMode] = useState<MachineMode | null>(null);
  const [estopped, setEstopped] = useState(false);
  const [xbox, setXboxState] = useState<XboxStatus | null>(null);
  const [mstate, setMstate] = useState<MachineState | null>(null);
  const [twin, setTwin] = useState<LiveTwin | null>(null);
  const consoleRef = useRef<HTMLDivElement>(null);
  const diagRef = useRef<HTMLDivElement>(null);

  const live = !!mode?.live;

  useEffect(() => { getMachineMode().then(setMode).catch(() => setMode(null)); }, []);

  // While live, poll the controller status + axis state so the manual panel is live.
  useEffect(() => {
    if (!live) return;
    let on = true;
    const tick = () => {
      getXbox().then((x) => on && setXboxState(x)).catch(() => {});
      getMachineState().then((s) => on && setMstate(s)).catch(() => {});
    };
    tick();
    const id = setInterval(tick, 1500);
    return () => { on = false; clearInterval(id); };
  }, [live]);

  const toggleJog = useCallback(async (action: "start" | "stop") => {
    try { const x = await setXbox(action); setXboxState(x); }
    catch { alert("Couldn't reach the machine API."); }
  }, []);

  // While jogging, poll the live twin fast so the conduit forms as he moves.
  const jogging = live && !!xbox?.running;
  useEffect(() => {
    if (!jogging) return;
    let on = true;
    const tick = () => { getMachineLive().then((d) => on && d.ok && setTwin(d)).catch(() => {}); };
    tick();
    const id = setInterval(tick, 350);
    return () => { on = false; clearInterval(id); };
  }, [jogging]);

  const zeroAndStart = useCallback(async () => {
    try { await machineZero(); setTwin(null); } catch { /* ignore */ }
  }, []);

  const run = useCallback(async () => {
    if (live) {
      const ok = window.confirm(
        "LIVE MACHINE\n\nThis will MOVE THE REAL BENDER. Motions are bounded safe-test " +
        "moves and angles are not calibrated yet. Make sure the machine area is clear " +
        "and the physical e-stop is within reach.\n\nRun on the real machine?");
      if (!ok) return;
    }
    setPhase("loading"); setRes(null); setShown(0); setPaused(false); setEstopped(false);
    try {
      const r = await runMachineProgram(bends.slice(0, count), live);
      if (!r.ok) { setPhase("idle"); alert(r.error || "Run failed"); return; }
      setRes(r); setShown(0); setPhase("run");
    } catch { setPhase("idle"); alert("Couldn't reach the machine API."); }
  }, [bends, count, live]);

  const estop = useCallback(async () => {
    setEstopped(true); setPaused(true);
    try { await machineEstop(); } catch { /* physical e-stop is the real safety device */ }
  }, []);

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

      <div className={`machine-mode ${live ? "live" : "sim"}`}>
        <div className="mm-left">
          <span className="mm-dot" />
          <b>{live ? "LIVE MACHINE" : "SIMULATION"}</b>
          <span className="muted" style={{ fontSize: 12.5 }}>
            {live
              ? (mode?.safe
                  ? "Running moves the real bender — bounded safe-test motion, angles not yet calibrated."
                  : "Running moves the real bender — SAFE CAPS OFF.")
              : "Runs against the ClearCore protocol in software — nothing physical moves."}
          </span>
        </div>
        {live && (
          <button className="btn estop" onClick={estop} title="Emergency stop (board 1)">
            ⬛ E-STOP
          </button>
        )}
      </div>
      {estopped && <div className="banner warn" style={{ marginBottom: 14 }}><b>E-STOP sent.</b> The physical e-stop is the primary safety device — use it if in doubt.</div>}

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
          <button className={`btn ${live ? "danger" : "green"}`} onClick={run} disabled={phase === "loading" || phase === "run"}>
            {phase === "loading" || phase === "run"
              ? <><span className="spin" /> Running…</>
              : live ? "▶ Run on real machine" : "▶ Run on machine"}
          </button>
          {live && <button className="btn estop sm" onClick={estop}>⬛ E-STOP</button>}
          <span className="muted" style={{ fontSize: 12.5 }}>
            {live
              ? "Moves the real bender (bounded). Clear the area; keep the physical e-stop in reach."
              : "Simulation only — drives the ClearCore protocol; nothing physical moves."}
          </span>
        </div>
      </div>

      {live && (
        <div className="panel" style={{ marginTop: 14 }}>
          <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <b>Manual control — Xbox controller</b>
              <div className="muted" style={{ fontSize: 12.5, marginTop: 3, maxWidth: 520 }}>
                {xbox?.running
                  ? <>Jogging live{xbox.controller ? ` · ${xbox.controller}` : ""} — shares the machine with bend programs; jog freezes automatically while a program runs.</>
                  : xbox?.available
                    ? <>Controller ready{xbox.controller ? ` · ${xbox.controller}` : ""}. Start jog to move the machine by hand.</>
                    : (xbox?.reason || "Checking for a controller…")}
              </div>
            </div>
            {xbox?.running
              ? <button className="btn ghost" onClick={() => toggleJog("stop")}>■ Stop jog</button>
              : <button className="btn green" onClick={() => toggleJog("start")} disabled={!xbox?.available}>▶ Start jog</button>}
          </div>
          {mstate?.axes && (
            <div className="axes" style={{ marginTop: 14 }}>
              {Object.entries(mstate.axes).map(([n, s]) => {
                const fault = /FAULT|ERR/.test(s);
                const moving = /MOVING/.test(s);
                return (
                  <div className={`axis ${moving ? "enabled" : ""}`} key={n}>
                    <div className="name">{n}</div>
                    <div className="val" style={{ fontSize: 12.5 }}>{s.replace(/^OK\s*/, "") || "idle"}</div>
                    <div className={`en ${fault ? "" : "off"}`}>{fault ? "● fault" : moving ? "● moving" : "○ idle"}</div>
                  </div>
                );
              })}
            </div>
          )}
          {jogging && (
            <div style={{ marginTop: 14 }}>
              <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
                <span className="muted" style={{ fontSize: 12 }}>
                  LIVE SHAPE — forms as you jog{twin && twin.calibrated === false ? " · uncalibrated, relative scale" : ""}
                </span>
                <button className="btn ghost sm" onClick={zeroAndStart}>⦿ Zero &amp; start</button>
              </div>
              {twin?.path && twin.path.verts.length > 1
                ? <Conduit3D verts={twin.path.verts} angles={twin.path.angles} cuts={twin.path.cuts}
                    progress={1} od_mm={twin.path.od_mm} bend_radius_mm={twin.path.bend_radius_mm} />
                : <div className="empty" style={{ height: 220 }}>Move the controller to start forming the conduit…</div>}
              <div className="row" style={{ gap: 18, marginTop: 8, fontFamily: "var(--font-mono, ui-monospace, monospace)", fontSize: 12.5 }}>
                <span className="muted">feed <b style={{ color: "var(--ink)" }}>{Math.round(twin?.feed_mm ?? 0)} mm</b></span>
                <span className="muted">bend <b style={{ color: "var(--ink)" }}>{Math.round(twin?.bend_deg ?? 0)}°</b></span>
                <span className="muted">roll <b style={{ color: "var(--ink)" }}>{Math.round(twin?.roll_deg ?? 0)}°</b></span>
                <span className="muted">bends <b style={{ color: "var(--ink)" }}>{twin?.n_bends ?? 0}</b></span>
              </div>
            </div>
          )}
          <div className="muted" style={{ fontSize: 12, marginTop: 12 }}>
            Left stick: advance / rotate · Right stick: bend · Triggers: squeeze · Bumpers: chuck · D-pad: enable a motor · B: bend on/off · X: disable all · Y: E-STOP.
          </div>
        </div>
      )}

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
                  ? <Conduit3D verts={res.path.verts} angles={res.path.angles} cuts={res.path.cuts}
                      progress={total ? shown / total : 1} od_mm={res.path.od_mm} bend_radius_mm={res.path.bend_radius_mm} />
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
                  : <><b>✓ {res.live ? "Ran on the real machine." : "Bend program complete."}</b> {res.counts.commands} firmware commands, no warnings.</>}
                {res.clamped && <div style={{ marginTop: 4, fontSize: 12.5 }}>Motions were clamped to safe caps for this wired test.</div>}
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
