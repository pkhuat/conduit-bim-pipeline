"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { getJob, type JobDetail } from "../../../../lib/api";

const mark = (mm: number) => `${(mm / 25.4).toFixed(1)}"`;
const ftIn = (ft: number) => { const t = Math.round(ft * 12); const f = Math.floor(t / 12); const i = t - f * 12; return f > 0 ? `${f}' ${i}"` : `${i}"`; };

export default function Packet() {
  const stem = String(useParams().stem);
  const [job, setJob] = useState<JobDetail | null>(null);
  useEffect(() => { getJob(stem).then((d) => d.ok && setJob(d)).catch(() => {}); }, [stem]);

  if (!job) return <main className="packet"><div className="empty">Loading job packet…</div></main>;
  const s = job.stats;
  const bent = job.runs.filter((r) => r.n_bends > 0);
  const mats = job.materials || [];
  const tiles: [number | string, string][] = [
    [s.conduits, "runs"], [s.bends, "bends"], [s.sticks, "sticks"],
    [s.raw_sticks, "raw sticks"], [s.total_ft, "total ft"], [s.review, "to review"],
  ];

  return (
    <main className="packet">
      <div className="pk-toolbar noprint">
        <button className="btn" onClick={() => window.print()}>🖨 Save as PDF / Print</button>
        <span className="muted" style={{ fontSize: 13 }}>Choose <b>Save as PDF</b> in the print dialog for an emailable file.</span>
      </div>

      <section className="pk-cover">
        <div className="pk-brand"><span className="dot" />TUBENDER</div>
        <h1>{job.name}</h1>
        <div className="muted">{s.conduit} · conduit fabrication package · {new Date().toLocaleDateString()}</div>
        <div className="pk-stats">
          {tiles.map(([n, l]) => <div className="tile" key={l}><div className="n">{n}</div><div className="l">{l}</div></div>)}
        </div>
      </section>

      <section className="pk-sec">
        <h2>Materials to order</h2>
        <table className="tbl">
          <thead><tr><th>Conduit</th><th className="num">Buy (10-ft sticks)</th><th className="num">Couplers</th><th className="num">Runs</th><th className="num">Bends</th><th className="num">Conduit used (ft)</th></tr></thead>
          <tbody>
            {mats.map((m) => (
              <tr key={m.label}>
                <td><b>{m.label}</b></td>
                <td className="num">{m.buy_sticks}</td><td className="num">{m.couplers}</td>
                <td className="num">{m.runs}</td><td className="num">{m.bends}</td><td className="num">{m.len_ft}</td>
              </tr>
            ))}
            {mats.length === 0 && <tr><td colSpan={6} className="muted">No bent conduit.</td></tr>}
          </tbody>
        </table>
      </section>

      <section className="pk-sec">
        <h2>Data health</h2>
        {s.review > 0
          ? <><p className="muted" style={{ marginTop: 0 }}>{s.review} run(s) need review before fabricating:</p>
              <div style={{ fontFamily: "var(--font-mono, monospace)", fontSize: 12.5, whiteSpace: "pre-wrap", color: "var(--warn)" }}>{s.flags.join("\n")}</div></>
          : <p style={{ marginTop: 0, color: "var(--good)" }}>✓ All runs clean — every bend a trade angle, no drift, no coupler warnings.</p>}
      </section>

      <h2 style={{ borderBottom: "1px solid var(--border)", paddingBottom: 7 }}>Runs &amp; bend cards</h2>
      {bent.map((run) => (
        <section className="pk-run" key={run.run}>
          <h3>Run #{run.run} — {run.die || run.kind} · {run.length_ft} ft · {run.n_bends} bends · {run.n_sticks} sticks</h3>
          {run.svg && <div className="pk-diagram" dangerouslySetInnerHTML={{ __html: run.svg }} />}
          <div className="pk-cards">
            {run.pieces.filter((p) => p.bends.length > 0).map((p) => {
              let acc = 0;
              const rows = p.bends.map((b) => { acc += b.advance; return { mark: acc, angle: b.angle, rotate: b.rotate, roll_dir: b.roll_dir }; });
              return (
                <div key={p.piece} className="bendcard">
                  <div className="bc-head">STICK #{p.piece} · cut {ftIn(p.cut_length_ft)} · {p.load} → {p.end}</div>
                  <table className="tbl">
                    <thead><tr><th>#</th><th className="num">Mark @</th><th className="num">Bend</th><th>Roll</th></tr></thead>
                    <tbody>
                      {rows.map((r, i) => (
                        <tr key={i}><td>{i + 1}</td><td className="num">{mark(r.mark)}</td><td className="num">{r.angle}°</td>
                          <td>{r.rotate ? `${r.rotate}° ${r.roll_dir > 0 ? "CW" : r.roll_dir < 0 ? "CCW" : ""}` : "—"}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              );
            })}
          </div>
        </section>
      ))}
    </main>
  );
}
