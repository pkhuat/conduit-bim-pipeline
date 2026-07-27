"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  fileUrl, getJob, runMachine, resolveRun, setSize, getTradeSizes, programUrl,
  type JobDetail, type Run, type MachineResult, type Command, type TradeSize,
} from "../../../lib/api";
import { AXES, freshAxes, applyCmd } from "../../../lib/machine";
import dynamic from "next/dynamic";

const Conduit3D = dynamic(() => import("../../../components/Conduit3D"), {
  ssr: false,
  loading: () => <div className="empty" style={{ height: 380 }}>Loading 3-D viewer…</div>,
});
const Bender3D = dynamic(() => import("../../../components/Bender3D"), {
  ssr: false,
  loading: () => <div className="empty" style={{ height: 400 }}>Loading bender…</div>,
});

type Tab = "overview" | "runs" | "machine";

const inMark = (mm: number) => `${(mm / 25.4).toFixed(1)}"`;                 // mark distance in inches
const ftInFromFt = (ft: number) => { const t = Math.round(ft * 12); const f = Math.floor(t / 12); const i = t - f * 12; return f > 0 ? `${f}' ${i}"` : `${i}"`; };

export default function Workspace() {
  const stem = String(useParams().stem);
  const [job, setJob] = useState<JobDetail | null>(null);
  const [err, setErr] = useState("");
  const [tab, setTab] = useState<Tab>("overview");
  const [machineTarget, setMachineTarget] = useState<number | number[] | null>(null);
  const [sizes, setSizes] = useState<TradeSize[]>([]);

  useEffect(() => { getTradeSizes().then((d) => setSizes(d.sizes)).catch(() => {}); }, []);
  const refresh = useCallback(
    () => getJob(stem).then((d) => { if (d.ok) setJob(d); }).catch(() => {}),
    [stem]);
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
      {tab === "runs" && <Runs job={job} stem={stem} sizes={sizes} refresh={refresh}
        onSend={(r) => { setMachineTarget(r); setTab("machine"); }}
        onQueue={(list) => { setMachineTarget(list); setTab("machine"); }} />}
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
function Runs({ job, stem, sizes, refresh, onSend, onQueue }:
  { job: JobDetail; stem: string; sizes: TradeSize[]; refresh: () => Promise<void>;
    onSend: (run: number) => void; onQueue: (runs: number[]) => void }) {
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<"all" | "review" | "bent">("all");
  const [openNo, setOpenNo] = useState<number | null>(null);
  const [sel, setSel] = useState<Set<number>>(new Set());
  const open = openNo != null ? job.runs.find((r) => r.run === openNo) ?? null : null;

  const rows = useMemo(() => job.runs.filter((r) => {
    if (filter === "review" && r.review.length === 0) return false;
    if (filter === "bent" && r.n_bends === 0) return false;
    if (q && !(`${r.run} ${r.kind}`.toLowerCase().includes(q.toLowerCase()))) return false;
    return true;
  }), [job.runs, q, filter]);

  const bentRows = rows.filter((r) => r.n_bends > 0);
  const toggle = (n: number) => setSel((s) => { const x = new Set(s); x.has(n) ? x.delete(n) : x.add(n); return x; });
  const allBentSelected = bentRows.length > 0 && bentRows.every((r) => sel.has(r.run));
  const toggleAll = () => setSel(allBentSelected ? new Set() : new Set(bentRows.map((r) => r.run)));

  if (open) return <RunDetail run={open} stem={stem} sizes={sizes} refresh={refresh}
    onBack={() => setOpenNo(null)} onSend={() => onSend(open.run)} />;

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
      {sel.size > 0 && (
        <div className="banner ok" style={{ display: "flex", alignItems: "center", gap: 12, justifyContent: "space-between" }}>
          <span><b>{sel.size} run{sel.size > 1 ? "s" : ""} selected</b> for the machine queue.</span>
          <span className="row">
            <button className="btn green sm" onClick={() => { onQueue([...sel].sort((a, b) => a - b)); }}>▶ Run {sel.size} on machine</button>
            <button className="btn ghost sm" onClick={() => setSel(new Set())}>Clear</button>
          </span>
        </div>
      )}
      <div style={{ overflowX: "auto" }}>
        <table className="tbl">
          <thead>
            <tr>
              <th style={{ width: 34 }}><input type="checkbox" checked={allBentSelected} onChange={toggleAll} aria-label="Select all bent runs" /></th>
              <th>Run</th><th>Conduit</th><th className="num">Length (ft)</th><th className="num">Bends</th><th className="num">Sticks</th><th>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.run} className="click" onClick={() => setOpenNo(r.run)}>
                <td onClick={(e) => e.stopPropagation()}>
                  {r.n_bends > 0 && <input type="checkbox" checked={sel.has(r.run)} onChange={() => toggle(r.run)} aria-label={`Select run ${r.run}`} />}
                </td>
                <td><b style={{ color: "var(--accent-text)" }}>#{r.run}</b></td>
                <td>{r.kind}{r.die ? <span className="muted"> · {r.die}</span> : null}</td>
                <td className="num">{r.length_ft}</td>
                <td className="num">{r.n_bends}</td>
                <td className="num">{r.n_sticks}</td>
                <td>{r.review.length
                  ? <span className="badge warn">review</span>
                  : r.n_bends ? <span className="badge ok">ready</span> : <span className="badge mut">straight</span>}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={7} className="empty">No runs match.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}

function RunDetail({ run, stem, sizes, refresh, onBack, onSend }:
  { run: Run; stem: string; sizes: TradeSize[]; refresh: () => Promise<void>; onBack: () => void; onSend: () => void }) {
  const [busy, setBusy] = useState(false);
  const [od, setOd] = useState("");
  const [view3d, setView3d] = useState(true);
  const [fab, setFab] = useState<Record<number, { cut?: boolean; bent?: boolean; coupled?: boolean }>>({});
  const hasOdd = run.review.some((r) => r.startsWith("odd angle"));

  useEffect(() => {
    try { setFab(JSON.parse(localStorage.getItem(`tubender:fab:${stem}:${run.run}`) || "{}")); } catch { setFab({}); }
  }, [stem, run.run]);
  const toggleStep = (piece: number, step: "cut" | "bent" | "coupled") => setFab((prev) => {
    const next = { ...prev, [piece]: { ...prev[piece], [step]: !prev[piece]?.[step] } };
    try { localStorage.setItem(`tubender:fab:${stem}:${run.run}`, JSON.stringify(next)); } catch { /* ignore */ }
    return next;
  });
  const stickDone = (p: number) => !!(fab[p]?.cut && fab[p]?.bent && fab[p]?.coupled);
  const doneCount = run.pieces.filter((p) => stickDone(p.piece)).length;
  const hasUnknownSize = run.review.some((r) => r.startsWith("unknown size"));

  async function standardize() {
    setBusy(true);
    try { await resolveRun(stem, run.run); await refresh(); }
    catch { alert("Couldn't reach the API."); }
    setBusy(false);
  }

  async function applySize() {
    if (!od) return;
    setBusy(true);
    try { await setSize(stem, run.run, Number(od)); await refresh(); }
    catch { alert("Couldn't reach the API."); }
    setBusy(false);
  }

  return (
    <div className="detail">
      <div className="row noprint" style={{ justifyContent: "space-between" }}>
        <button className="btn ghost sm" onClick={onBack}>← All runs</button>
        <span className="row">
          {run.n_bends > 0 && <a className="btn ghost sm" href={programUrl(stem, run.run)}>⤓ Machine program</a>}
          <button className="btn ghost sm" onClick={() => window.print()}>🖨 Print traveler</button>
          <button className="btn green sm" disabled={run.n_bends === 0} onClick={onSend}>Send to machine →</button>
        </span>
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
        {run.review.length > 0 ? (
          <div className="banner warn" style={{ marginTop: 12 }}>
            {run.review.map((i, k) => <div key={k}>⚠ {i}</div>)}
            {hasOdd && (
              <div className="row" style={{ marginTop: 10 }}>
                <button className="btn sm" onClick={standardize} disabled={busy}>
                  {busy ? <><span className="spin" /> Standardizing…</> : "Standardize this run’s angles"}
                </button>
                <span className="muted" style={{ fontSize: 12.5 }}>Snaps the odd angle(s) to the nearest trade angle.</span>
              </div>
            )}
            {hasUnknownSize && (
              <div className="row" style={{ marginTop: 10 }}>
                <select value={od} onChange={(e) => setOd(e.target.value)}
                  style={{ padding: "7px 10px", borderRadius: 8, border: "1px solid var(--border-2)", fontSize: 13.5 }}>
                  <option value="">Set conduit size…</option>
                  {sizes.map((s) => <option key={s.size} value={s.od_mm}>{s.size}&quot; ({s.od_mm} mm OD)</option>)}
                </select>
                <button className="btn sm" onClick={applySize} disabled={!od || busy}>
                  {busy ? <><span className="spin" /> Applying…</> : "Set size"}
                </button>
                <span className="muted" style={{ fontSize: 12.5 }}>Enables take-up correction &amp; the die.</span>
              </div>
            )}
          </div>
        ) : (
          <div className="banner ok" style={{ marginTop: 12 }}>✓ Ready to fabricate.</div>
        )}
      </div>

      {(run.path || run.svg) && (
        <div className="panel">
          <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
            <h2 style={{ margin: 0 }}>Run shape</h2>
            <div className="seg">
              <button className={view3d ? "on" : ""} onClick={() => setView3d(true)} disabled={!run.path}>3D</button>
              <button className={!view3d ? "on" : ""} onClick={() => setView3d(false)} disabled={!run.svg}>2D</button>
            </div>
          </div>
          {view3d && run.path ? (
            <Conduit3D verts={run.path.verts} angles={run.path.angles} cuts={run.path.cuts}
              od_mm={run.od_mm} bend_radius_mm={run.bend_radius_mm} />
          ) : run.svg ? (
            <>
              <div className="diagram" dangerouslySetInnerHTML={{ __html: run.svg }} />
              <div className="legend">
                <span><i className="sw start" /> start / end</span>
                <span><i className="sw bend" /> bend (angle labeled)</span>
                <span><i className="sw stick" /> each color = one 10-ft stick</span>
                <span><i className="sw cplr" /> coupler joint</span>
              </div>
            </>
          ) : null}
        </div>
      )}

      {run.n_bends > 0 && (
        <div className="panel">
          <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
            <h2 style={{ margin: 0 }}>Sticks &amp; shop floor</h2>
            <span className={`badge ${doneCount === run.pieces.length ? "ok" : "mut"}`}>{doneCount} / {run.pieces.length} sticks done</span>
          </div>
          <div style={{ overflowX: "auto" }}>
            <table className="tbl">
              <thead><tr><th>Stick</th><th>Load</th><th>End</th><th className="num">Cut (ft)</th><th className="num">Bends</th><th>Track (tap as you go)</th></tr></thead>
              <tbody>
                {run.pieces.map((p) => (
                  <tr key={p.piece} className={stickDone(p.piece) ? "donerow" : ""}>
                    <td>#{p.piece}</td><td className="muted">{p.load}</td><td className="muted">{p.end}</td>
                    <td className="num">{p.cut_length_ft}</td><td className="num">{p.bends.length}</td>
                    <td>
                      <div className="stepcell">
                        {(["cut", "bent", "coupled"] as const).map((st) => (
                          <button key={st} className={`stepchip ${fab[p.piece]?.[st] ? "on" : ""}`} onClick={() => toggleStep(p.piece, st)}>
                            {fab[p.piece]?.[st] ? "✓ " : ""}{st}
                          </button>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>Tap each step as you fabricate a stick — saved on this device.</p>
        </div>
      )}

      {run.pieces.some((p) => p.bends.length > 0) && (
        <div className="panel">
          <h2 style={{ marginTop: 0 }}>Bend cards</h2>
          <p className="muted" style={{ fontSize: 12.5, margin: "0 0 12px" }}>
            One card per stick — cut to length, then measure &amp; mark from the load end at each distance and bend. Marks are take-up corrected.
          </p>
          <div className="bendcards">
            {run.pieces.filter((p) => p.bends.length > 0).map((p) => {
              let acc = 0;
              const rows = p.bends.map((b) => { acc += b.advance; return { mark: acc, angle: b.angle, rotate: b.rotate, roll_dir: b.roll_dir }; });
              return (
                <div key={p.piece} className="bendcard">
                  <div className="bc-head">STICK #{p.piece} · cut {ftInFromFt(p.cut_length_ft)} · {p.load} → {p.end}</div>
                  <table className="tbl">
                    <thead><tr><th>#</th><th className="num">Mark @</th><th className="num">Bend</th><th>Roll</th></tr></thead>
                    <tbody>
                      {rows.map((r, i) => (
                        <tr key={i}>
                          <td>{i + 1}</td>
                          <td className="num">{inMark(r.mark)}</td>
                          <td className="num">{r.angle}°</td>
                          <td>{r.rotate ? `${r.rotate}° ${r.roll_dir > 0 ? "CW" : r.roll_dir < 0 ? "CCW" : ""}` : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------------- Machine ---------------- */
type Sel = number | "all" | number[];
function Machine({ job, target }: { job: JobDetail; target: number | number[] | null }) {
  const bent = useMemo(() => job.runs.filter((r) => r.n_bends > 0), [job.runs]);
  const [sel, setSel] = useState<Sel>(() => target ?? bent[0]?.run ?? "all");
  const [phase, setPhase] = useState<"idle" | "loading" | "run" | "done">("idle");
  const [res, setRes] = useState<MachineResult | null>(null);
  const [shown, setShown] = useState(0);
  const [paused, setPaused] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [waiting, setWaiting] = useState(false);   // stopped at a stick boundary for a hand cut & couple
  const [show3d, setShow3d] = useState<"bender" | "conduit">("bender");
  const consoleRef = useRef<HTMLDivElement>(null);

  // command indices that begin a NEW stick — the machine bends one stick, then you
  // cut & couple by hand before the next
  const stickStarts = useMemo(() => {
    const s = new Set<number>();
    if (res) for (let i = 1; i < res.commands.length; i++)
      if (res.commands[i].stick !== res.commands[i - 1].stick) s.add(i);
    return s;
  }, [res]);

  const startWith = useCallback(async (selection: Sel) => {
    setPhase("loading"); setRes(null); setShown(0); setPaused(false); setWaiting(false);
    try {
      const r = await runMachine(job.stem, selection);
      if (!r.ok) { setPhase("idle"); alert(r.error || "Machine run failed"); return; }
      setRes(r); setShown(0); setPhase("run");
    } catch { setPhase("idle"); alert("Couldn't reach the API."); }
  }, [job.stem]);
  const start = () => startWith(sel);

  // pick up a hand-off from the Runs tab: a single "Send to machine" preselects;
  // a queue ("Run N on machine") preselects AND starts.
  useEffect(() => {
    if (target == null) return;
    setSel(target);
    if (Array.isArray(target)) startWith(target);
  }, [target, startWith]);

  const step = useCallback(() => {
    if (!res) return;
    setShown((s) => {
      const next = Math.min(s + 1, res.commands.length);
      if (next >= res.commands.length) setPhase("done");
      return next;
    });
  }, [res]);

  const restart = useCallback(() => {
    if (!res) return;
    setShown(0); setPaused(false); setWaiting(false); setPhase("run");
  }, [res]);

  // animate the command stream — honors pause/speed, and stops at each stick
  // boundary so the operator can cut & couple by hand before continuing
  useEffect(() => {
    if (phase !== "run" || !res || paused || waiting) return;
    const total = res.commands.length;
    const per = Math.max(1, Math.floor(total / 200));
    const id = setInterval(() => {
      setShown((s) => {
        const next = s + per;
        for (let b = s + 1; b <= Math.min(next, total); b++)
          if (stickStarts.has(b)) { setWaiting(true); return b; }   // pause at end of the stick
        if (next >= total) { clearInterval(id); setPhase("done"); return total; }
        return next;
      });
    }, Math.max(8, Math.round(30 / speed)));
    return () => clearInterval(id);
  }, [phase, res, paused, speed, waiting, stickStarts]);

  useEffect(() => { if (consoleRef.current) consoleRef.current.scrollTop = consoleRef.current.scrollHeight; }, [shown]);

  const axes = useMemo(() => {
    const ax = freshAxes();
    if (res) res.commands.slice(0, shown).forEach((c) => applyCmd(ax, c.cmd));
    return ax;
  }, [res, shown]);

  const total = res?.commands.length ?? 0;
  const pct = total ? Math.round((shown / total) * 100) : 0;
  const tail = res ? res.commands.slice(Math.max(0, shown - 220), shown) : [];
  const curRun = typeof sel === "number" ? job.runs.find((r) => r.run === sel) ?? null : null;
  const formProgress = res ? (total ? shown / total : 1) : 1;
  const nSticks = res?.counts.sticks ?? 0;
  const curStick = res && shown > 0 ? (res.commands[Math.min(shown, total) - 1]?.stick ?? 1) : 1;

  return (
    <div className="machine">
      <div>
        <div className="panel">
          <div className="row" style={{ gap: 10 }}>
            <label className="muted" style={{ fontSize: 13 }}>Run</label>
            {Array.isArray(sel) ? (
              <div style={{ flex: 1, display: "flex", gap: 8, alignItems: "center", fontSize: 14 }}>
                <span><b>Queue:</b> {sel.length} runs (#{sel.slice(0, 6).join(", #")}{sel.length > 6 ? "…" : ""})</span>
                <button className="btn ghost sm" onClick={() => setSel(bent[0]?.run ?? "all")}>change</button>
              </div>
            ) : (
              <select value={String(sel)} onChange={(e) => setSel(e.target.value === "all" ? "all" : Number(e.target.value))}
                style={{ padding: "8px 10px", borderRadius: 9, border: "1px solid var(--border-2)", fontSize: 14, flex: 1 }}>
                {bent.map((r) => <option key={r.run} value={r.run}>Run #{r.run} — {r.kind}, {r.n_bends} bends</option>)}
                <option value="all">Whole building — every bent run</option>
              </select>
            )}
            <button className="btn green" onClick={start} disabled={phase === "loading" || phase === "run"}>
              {phase === "loading" ? <><span className="spin" /> Loading…</> : phase === "run" ? <><span className="spin" /> Running…</> : "▶ Run machine"}
            </button>
          </div>
          <div className="sub" style={{ margin: "10px 0 0", fontSize: 12.5 }}>
            The bender does one 10-ft stick at a time — it pauses after each so you cut &amp; couple the next by hand.
            Simulation only: drives the ClearCore command protocol through the firmware model; nothing physical moves.
          </div>
          {curRun && curRun.n_bends > 0 && (
            <div style={{ marginTop: 12 }}>
              <a className="btn ghost sm" href={programUrl(job.stem, curRun.run)}>⤓ Download machine program (run #{curRun.run})</a>
            </div>
          )}
        </div>

        <div className="progress" style={{ marginTop: 14 }}><div style={{ width: `${pct}%` }} /></div>
        <div className="row" style={{ justifyContent: "space-between", fontSize: 12.5 }}>
          <span className="muted">{res ? `${shown} / ${total} commands` : "idle"}</span>
          {res && <span className="muted">{nSticks > 1 ? `stick ${curStick} of ${nSticks} · ` : ""}{res.counts.warnings} warning{res.counts.warnings === 1 ? "" : "s"}{res.truncated ? " · truncated" : ""}</span>}
        </div>

        {waiting && (
          <div className="banner warn" style={{ marginTop: 12, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
            <span>✂ <b>Stick {curStick} bent.</b> Cut the next 10-ft stick &amp; couple it by hand, then continue.</span>
            <button className="btn sm" onClick={() => setWaiting(false)}>Continue → stick {Math.min(curStick + 1, nSticks)}</button>
          </div>
        )}

        {res && (
          <div className="row" style={{ marginTop: 12, gap: 8 }}>
            {phase === "run" && (
              <button className="btn ghost sm" onClick={() => setPaused((p) => !p)}>
                {paused ? "▶ Resume" : "❚❚ Pause"}
              </button>
            )}
            <button className="btn ghost sm" onClick={step} disabled={shown >= total}>Step ▷</button>
            <button className="btn ghost sm" onClick={restart}>↺ Restart</button>
            <span className="muted" style={{ fontSize: 12.5, marginLeft: 4 }}>Speed</span>
            <div className="seg">
              {[0.5, 1, 2, 4].map((s) => (
                <button key={s} className={speed === s ? "on" : ""} onClick={() => setSpeed(s)}>{s}×</button>
              ))}
            </div>
          </div>
        )}

        <div className="axes">
          {AXES.map((n) => (
            <div className={`axis ${axes[n].enabled ? "enabled" : ""}`} key={n}>
              <div className="name">{n}</div>
              <div className="val">{Math.round(axes[n].position).toLocaleString()}</div>
              <div className={`en ${axes[n].enabled ? "" : "off"}`}>{axes[n].enabled ? "● enabled" : "○ disabled"}</div>
            </div>
          ))}
        </div>

        {curRun?.path && (
          <div className="panel" style={{ marginTop: 14, padding: 12 }}>
            <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
              <span className="muted" style={{ fontSize: 12 }}>
                {show3d === "bender" ? "THE BENDER — watch it work" : `RUN #${curRun.run} — ${phase === "run" ? "forming as it bends" : "3-D shape"}`}
              </span>
              <div className="seg">
                <button className={show3d === "bender" ? "on" : ""} onClick={() => setShow3d("bender")}>Bender</button>
                <button className={show3d === "conduit" ? "on" : ""} onClick={() => setShow3d("conduit")}>Conduit</button>
              </div>
            </div>
            {show3d === "bender"
              ? <Bender3D bend={axes.BEND.position} squeeze={axes.SQUEEZE.position > 100} />
              : <Conduit3D verts={curRun.path.verts} angles={curRun.path.angles} cuts={curRun.path.cuts}
                  progress={formProgress} od_mm={curRun.od_mm} bend_radius_mm={curRun.bend_radius_mm} />}
          </div>
        )}

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
            const newStick = i > 0 && c.stick !== tail[i - 1].stick;
            return (
              <div key={i}>
                {newStick && (
                  <div className="line" style={{ color: "#e0a54f", margin: "5px 0", opacity: .9 }}>
                    ── cut &amp; couple by hand · load stick {c.stick} ──
                  </div>
                )}
                <div className="line">
                  <span className={c.board === 2 ? "b2" : "hd"}>{c.board}</span>{"  "}
                  {c.cmd}{"  "}<span className={isErr ? "err" : "resp"}>→ {c.response}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
