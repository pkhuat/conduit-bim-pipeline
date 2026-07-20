"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  fileUrl, getJob, runMachine,
  type JobDetail, type Run, type MachineResult, type Command,
} from "../../../lib/api";

type Tab = "overview" | "runs" | "machine";
type AxisMap = Record<string, { position: number; enabled: boolean }>;
const AXES = ["ADVANCE", "ROTATE", "BEND", "SQUEEZE"];

const freshAxes = (): AxisMap =>
  Object.fromEntries(AXES.map((a) => [a, { position: 0, enabled: false }]));

function applyCmd(ax: AxisMap, cmd: string) {
  const [sub, act, val] = cmd.split(" ");
  const a = ax[sub];
  if (!a) return;
  if (act === "ENABLE") a.enabled = true;
  else if (act === "DISABLE") a.enabled = false;
  else if (act === "TO") a.position = parseFloat(val) || 0;
  else if (act === "BY") a.position += parseFloat(val) || 0;
  else if (act === "CLOSE") a.position += 5000;
  else if (act === "OPEN") a.position -= 5000;
}

export default function Workspace() {
  const stem = String(useParams().stem);
  const [job, setJob] = useState<JobDetail | null>(null);
  const [err, setErr] = useState("");
  const [tab, setTab] = useState<Tab>("overview");
  const [machineTarget, setMachineTarget] = useState<number | null>(null);

  useEffect(() => {
    getJob(stem).then((d) => (d.ok ? setJob(d) : setErr(d.error || "Not found")))
      .catch(() => setErr("Couldn't reach the API."));
  }, [stem]);

  if (err) return <main className="wrap"><div className="banner warn">⚠ {err}</div><Link className="btn ghost" href="/">← Back to jobs</Link></main>;
  if (!job) return <main className="wrap"><div className="empty"><span className="spin" style={{ borderColor: "#9fb0c8", borderTopColor: "transparent" }} /> loading…</div></main>;

  return (
    <main className="wrap">
      <div className="crumbs"><Link href="/">Jobs</Link> / {job.name}</div>
      <h1>{job.name}</h1>
      <p className="sub">{job.stats.conduit} · fabrication package</p>

      <div className="tabs">
        <button className={tab === "overview" ? "on" : ""} onClick={() => setTab("overview")}>Overview</button>
        <button className={tab === "runs" ? "on" : ""} onClick={() => setTab("runs")}>Runs <span className="badge mut">{job.runs.length}</span></button>
        <button className={tab === "machine" ? "on" : ""} onClick={() => setTab("machine")}>Machine</button>
      </div>

      {tab === "overview" && <Overview job={job} />}
      {tab === "runs" && <Runs job={job} onSend={(r) => { setMachineTarget(r); setTab("machine"); }} />}
      {tab === "machine" && <Machine job={job} target={machineTarget} />}
    </main>
  );
}

/* ---------------- Overview ---------------- */
function Overview({ job }: { job: JobDetail }) {
  const s = job.stats;
  const tiles: [number | string, string, boolean?][] = [
    [s.conduits, "conduit runs"], [s.bends, "bends"], [s.sticks, "sticks to bend"],
    [s.raw_sticks, "raw sticks to buy"], [s.total_ft, "total ft"], [s.review, "runs to review", true],
  ];
  const links: [string, string, string][] = [
    ["cards", "Bend cards", "printable, per stick"],
    ["diagrams", "Diagrams", "run shapes, colored by stick"],
    ["cutlist", "Cut list", "offcut-optimized cut plan"],
    ["pieces", "Pieces", "per-stick data"],
    ["health", "Data health", "runs to review"],
    ["job", "Machine job", "machine-ready recipe"],
  ];
  return (
    <>
      {s.review > 0
        ? <div className="banner warn"><b>⚠ {s.review} run(s) need review</b> — odd angles or drift. Open the <b>Runs</b> tab to see which.</div>
        : <div className="banner ok">✓ All runs ready to fabricate.</div>}
      <div className="tiles">
        {tiles.map(([n, l, flag]) => (
          <div className={`tile ${flag && Number(n) > 0 ? "flag" : ""}`} key={l}>
            <div className="n">{n}</div><div className="l">{l}</div>
          </div>
        ))}
      </div>
      <div className="cards">
        {links.map(([k, t, d]) => job.urls[k] && (
          <a className="card" key={k} href={fileUrl(job.urls[k])} target="_blank" rel="noreferrer">
            <div className="t">{t}</div><div className="d">{d}</div>
          </a>
        ))}
      </div>
      <div className="row" style={{ marginTop: 20 }}>
        <a className="btn" href={fileUrl(job.urls.download)}>⭳ Download package (.zip)</a>
      </div>
    </>
  );
}

/* ---------------- Runs ---------------- */
function Runs({ job, onSend }: { job: JobDetail; onSend: (run: number) => void }) {
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<"all" | "review" | "bent">("all");
  const [open, setOpen] = useState<Run | null>(null);

  const rows = useMemo(() => job.runs.filter((r) => {
    if (filter === "review" && r.review.length === 0) return false;
    if (filter === "bent" && r.n_bends === 0) return false;
    if (q && !(`${r.run} ${r.kind}`.toLowerCase().includes(q.toLowerCase()))) return false;
    return true;
  }), [job.runs, q, filter]);

  if (open) return <RunDetail run={open} onBack={() => setOpen(null)} onSend={() => onSend(open.run)} />;

  return (
    <>
      <div className="toolbar">
        <input type="search" placeholder="Search run # or conduit…" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="seg">
          {(["all", "bent", "review"] as const).map((f) => (
            <button key={f} className={filter === f ? "on" : ""} onClick={() => setFilter(f)}>
              {f === "all" ? "All" : f === "bent" ? "Bent" : "Needs review"}
            </button>
          ))}
        </div>
      </div>
      <table className="tbl">
        <thead>
          <tr><th>Run</th><th>Conduit</th><th className="num">Length (ft)</th><th className="num">Bends</th><th className="num">Sticks</th><th>Status</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.run} className="click" onClick={() => setOpen(r)}>
              <td><b style={{ color: "var(--navy)" }}>#{r.run}</b></td>
              <td>{r.kind}{r.die ? <span className="muted"> · {r.die}</span> : null}</td>
              <td className="num">{r.length_ft}</td>
              <td className="num">{r.n_bends}</td>
              <td className="num">{r.n_sticks}</td>
              <td>{r.review.length
                ? <span className="badge warn">review</span>
                : r.n_bends ? <span className="badge ok">ready</span> : <span className="badge mut">straight</span>}</td>
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={6} className="empty">No runs match.</td></tr>}
        </tbody>
      </table>
    </>
  );
}

function RunDetail({ run, onBack, onSend }: { run: Run; onBack: () => void; onSend: () => void }) {
  return (
    <div className="detail">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <button className="btn ghost sm" onClick={onBack}>← All runs</button>
        <button className="btn green sm" disabled={run.n_bends === 0} onClick={onSend}>Send to machine →</button>
      </div>
      <div className="panel">
        <h2 style={{ marginTop: 0 }}>Run #{run.run}</h2>
        <div className="kv">
          <span>{run.kind}</span>
          {run.die && <span>die: {run.die}</span>}
          {run.od_mm && <span>OD {run.od_mm} mm</span>}
          <span>{run.length_ft} ft</span>
          <span>{run.n_bends} bends</span>
          <span>{run.n_sticks} sticks</span>
        </div>
        {run.review.length > 0 && (
          <div className="banner warn" style={{ marginTop: 12 }}>
            {run.review.map((i, k) => <div key={k}>⚠ {i}</div>)}
          </div>
        )}
      </div>

      {run.n_bends > 0 && (
        <div className="panel">
          <h2 style={{ marginTop: 0 }}>Sticks</h2>
          <table className="tbl">
            <thead><tr><th>Stick</th><th>Load</th><th>End</th><th className="num">Cut (ft)</th><th className="num">Bends</th></tr></thead>
            <tbody>
              {run.pieces.map((p) => (
                <tr key={p.piece}>
                  <td>#{p.piece}</td><td className="muted">{p.load}</td><td className="muted">{p.end}</td>
                  <td className="num">{p.cut_length_ft}</td><td className="num">{p.bends.length}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ---------------- Machine ---------------- */
function Machine({ job, target }: { job: JobDetail; target: number | null }) {
  const bent = useMemo(() => job.runs.filter((r) => r.n_bends > 0), [job.runs]);
  const [sel, setSel] = useState<number | "all">(() => target ?? bent[0]?.run ?? "all");
  const [phase, setPhase] = useState<"idle" | "loading" | "run" | "done">("idle");
  const [res, setRes] = useState<MachineResult | null>(null);
  const [shown, setShown] = useState(0);
  const consoleRef = useRef<HTMLDivElement>(null);

  // pick up a run handed over from the Runs tab ("Send to machine")
  useEffect(() => { if (target != null) setSel(target); }, [target]);

  const start = useCallback(async () => {
    setPhase("loading"); setRes(null); setShown(0);
    try {
      const r = await runMachine(job.stem, sel);
      if (!r.ok) { setPhase("idle"); alert(r.error || "Machine run failed"); return; }
      setRes(r); setShown(0); setPhase("run");
    } catch { setPhase("idle"); alert("Couldn't reach the API."); }
  }, [job.stem, sel]);

  // animate the command stream
  useEffect(() => {
    if (phase !== "run" || !res) return;
    const total = res.commands.length;
    const batch = Math.max(1, Math.floor(total / 200));
    const id = setInterval(() => {
      setShown((s) => {
        const next = s + batch;
        if (next >= total) { clearInterval(id); setPhase("done"); return total; }
        return next;
      });
    }, 28);
    return () => clearInterval(id);
  }, [phase, res]);

  useEffect(() => { if (consoleRef.current) consoleRef.current.scrollTop = consoleRef.current.scrollHeight; }, [shown]);

  const axes = useMemo(() => {
    const ax = freshAxes();
    if (res) res.commands.slice(0, shown).forEach((c) => applyCmd(ax, c.cmd));
    return ax;
  }, [res, shown]);

  const total = res?.commands.length ?? 0;
  const pct = total ? Math.round((shown / total) * 100) : 0;
  const tail = res ? res.commands.slice(Math.max(0, shown - 220), shown) : [];

  return (
    <div className="machine">
      <div>
        <div className="panel">
          <div className="row" style={{ gap: 10 }}>
            <label className="muted" style={{ fontSize: 13 }}>Run</label>
            <select value={String(sel)} onChange={(e) => setSel(e.target.value === "all" ? "all" : Number(e.target.value))}
              style={{ padding: "8px 10px", borderRadius: 9, border: "1px solid var(--line)", fontSize: 14, flex: 1 }}>
              {bent.map((r) => <option key={r.run} value={r.run}>Run #{r.run} — {r.kind}, {r.n_bends} bends</option>)}
              <option value="all">Whole building — every bent run</option>
            </select>
            <button className="btn green" onClick={start} disabled={phase === "loading" || phase === "run"}>
              {phase === "loading" ? <><span className="spin" /> Loading…</> : phase === "run" ? <><span className="spin" /> Running…</> : "▶ Run machine"}
            </button>
          </div>
          <div className="sub" style={{ margin: "10px 0 0", fontSize: 12.5 }}>
            Simulation only — drives the ClearCore command protocol through the firmware model. No serial port is opened; nothing physical moves.
          </div>
        </div>

        <div className="progress" style={{ marginTop: 14 }}><div style={{ width: `${pct}%` }} /></div>
        <div className="row" style={{ justifyContent: "space-between", fontSize: 12.5 }}>
          <span className="muted">{res ? `${shown} / ${total} commands` : "idle"}</span>
          {res && <span className="muted">{res.counts.sticks} sticks · {res.counts.warnings} warnings{res.truncated ? " · truncated" : ""}</span>}
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

        {phase === "done" && res && (
          <div className={`banner ${res.warnings.length ? "warn" : "ok"}`} style={{ marginTop: 14 }}>
            {res.warnings.length
              ? <><b>Completed with {res.warnings.length} warning(s).</b>{res.warnings.slice(0, 4).map((w, k) => <div key={k} style={{ fontSize: 12.5 }}>· {w}</div>)}</>
              : <><b>✓ Run complete.</b> {res.counts.commands} firmware commands across {res.counts.sticks} sticks — no warnings.</>}
          </div>
        )}
      </div>

      <div>
        <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>FIRMWARE COMMAND STREAM (board · command → response)</div>
        <div className="console" ref={consoleRef}>
          {tail.length === 0 && <div className="muted">Press <b style={{ color: "#cfe0ff" }}>Run machine</b> to drive the selected run through the simulator.</div>}
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
  );
}
