"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { API, getJobs, type Job } from "../lib/api";

export default function Home() {
  const router = useRouter();
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [resolve, setResolve] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    getJobs().then((d) => setJobs(d.jobs)).catch(() => setJobs([]));
  }, []);
  useEffect(load, [load]);

  const upload = useCallback(async () => {
    if (!file) return;
    setBusy(true); setError("");
    const fd = new FormData();
    fd.append("ifc", file);
    if (resolve) fd.append("resolve", "true");
    try {
      const r = await fetch(`${API}/api/process`, { method: "POST", body: fd });
      const j = await r.json();
      if (!j.ok) { setError(j.error || "Something went wrong."); setBusy(false); return; }
      router.push(`/job/${j.stem}`);
    } catch {
      setError(`Couldn't reach the pipeline API at ${API}. Is it running?`);
      setBusy(false);
    }
  }, [file, resolve, router]);

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault(); setDrag(false);
    const f = e.dataTransfer.files?.[0];
    if (f) setFile(f);
  };

  return (
    <main className="wrap">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <h1>Conduit Fabrication</h1>
          <p className="sub">Turn a Revit / BIM <b>.ifc</b> model into a machine-ready fabrication package — then run it on the machine.</p>
        </div>
        <Link className="btn ghost" href="/bend">+ Create a bend by hand</Link>
      </div>

      <div
        className={`drop ${drag ? "hi" : ""}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
      >
        <div style={{ fontSize: 38 }}>📁</div>
        <div><b>Drag &amp; drop</b> a <b>.ifc</b> here, or <b>click to browse</b></div>
        <div className="sub" style={{ marginTop: 6 }}>{file ? file.name : "no file chosen"}</div>
        <input ref={inputRef} type="file" accept=".ifc" hidden
          onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </div>

      <div className="row" style={{ marginTop: 14 }}>
        <button className="btn" disabled={!file || busy} onClick={upload}>
          {busy ? <><span className="spin" /> Processing…</> : "Process model"}
        </button>
        <label className="chk">
          <input type="checkbox" checked={resolve} onChange={(e) => setResolve(e.target.checked)} />
          Standardize odd angles (snap to trade)
        </label>
      </div>
      {error && <div className="banner warn" style={{ marginTop: 16 }}>⚠ {error}</div>}

      <h2>Recent jobs</h2>
      {jobs === null ? (
        <div className="empty"><span className="spin" style={{ borderColor: "#9fb0c8", borderTopColor: "transparent" }} /> loading…</div>
      ) : jobs.length === 0 ? (
        <div className="panel empty">No jobs yet — process a model above to get started.</div>
      ) : (
        <div style={{ overflowX: "auto" }}>
        <table className="tbl">
          <thead>
            <tr><th>Job</th><th>Conduit</th><th className="num">Runs</th><th className="num">Bends</th><th>Status</th></tr>
          </thead>
          <tbody>
            {jobs.map((jb) => (
              <tr key={jb.stem} className="click" onClick={() => router.push(`/job/${jb.stem}`)}>
                <td><b style={{ color: "var(--navy)" }}>{jb.name}</b></td>
                <td className="muted">{jb.conduit}</td>
                <td className="num">{jb.conduits}</td>
                <td className="num">{jb.bends}</td>
                <td>{jb.review > 0
                  ? <span className="badge warn">{jb.review} to review</span>
                  : <span className="badge ok">ready</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}
    </main>
  );
}
