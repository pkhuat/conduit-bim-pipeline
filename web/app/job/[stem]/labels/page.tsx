"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { getJob, type JobDetail } from "../../../../lib/api";

const ftIn = (ft: number) => { const t = Math.round(ft * 12); const f = Math.floor(t / 12); const i = t - f * 12; return f > 0 ? `${f}' ${i}"` : `${i}"`; };

export default function Labels() {
  const stem = String(useParams().stem);
  const [job, setJob] = useState<JobDetail | null>(null);
  useEffect(() => { getJob(stem).then((d) => d.ok && setJob(d)).catch(() => {}); }, [stem]);

  if (!job) return <main className="labels"><div className="empty">Loading labels…</div></main>;

  const labels = job.runs
    .filter((r) => r.n_bends > 0)
    .flatMap((r) => r.pieces.filter((p) => p.bends.length > 0).map((p) => ({ run: r.run, piece: p.piece, kind: r.die || r.kind, cut: p.cut_length_ft, bends: p.bends.length })));

  return (
    <main className="labels">
      <div className="pk-toolbar noprint">
        <button className="btn" onClick={() => window.print()}>🖨 Save as PDF / Print</button>
        <span className="muted" style={{ fontSize: 13 }}>{labels.length} stick label(s) — one per bent stick, for the shop bins.</span>
      </div>
      <h1 className="noprint">{job.name} — stick labels</h1>
      <div className="labelgrid">
        {labels.map((l, i) => (
          <div className="label" key={i}>
            <div className="lh"><span>RUN #{l.run}</span><span>STICK #{l.piece}</span></div>
            <div className="lb">{ftIn(l.cut)} cut</div>
            <div className="lm">{l.kind} · {l.bends} bend{l.bends === 1 ? "" : "s"}</div>
          </div>
        ))}
        {labels.length === 0 && <div className="empty">No bent sticks to label.</div>}
      </div>
    </main>
  );
}
