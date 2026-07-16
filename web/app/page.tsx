"use client";

import { useCallback, useRef, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:5000";

type Stats = {
  conduit: string; conduits: number; bends: number; sticks: number;
  total_ft: number; raw_sticks: number; review: number; flags: string[];
};
type Result = {
  ok: boolean; stem?: string; stats?: Stats;
  urls?: Record<string, string>; error?: string; resolved?: boolean;
};

const TILES: [keyof Stats, string][] = [
  ["conduits", "conduit runs"], ["bends", "bends"], ["sticks", "sticks to bend"],
  ["raw_sticks", "raw sticks to buy"], ["total_ft", "total ft"], ["review", "runs to review"],
];
const LINKS: [string, string, string][] = [
  ["cards", "Bend cards", "printable, per stick"],
  ["diagrams", "Diagrams", "run shapes, colored by stick"],
  ["cutlist", "Cut list", "offcut-optimized cut plan"],
  ["pieces", "Pieces", "per-stick data"],
  ["health", "Data health", "runs to review"],
  ["job", "Machine job", "machine-ready recipe"],
];

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [resolve, setResolve] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const upload = useCallback(async (f: File, force = false) => {
    setBusy(true); setError("");
    const fd = new FormData();
    fd.append("ifc", f);
    if (force) fd.append("resolve", "true");
    try {
      const r = await fetch(`${API}/api/process`, { method: "POST", body: fd });
      const j: Result = await r.json();
      if (!j.ok) setError(j.error || "Something went wrong.");
      else setResult(j);
    } catch {
      setError(`Couldn't reach the pipeline API at ${API}. Is it running?`);
    }
    setBusy(false);
  }, []);

  const standardize = useCallback(async () => {
    if (!result?.stem) return;
    setBusy(true);
    try {
      const r = await fetch(`${API}/api/resolve/${result.stem}`, { method: "POST" });
      setResult(await r.json());
    } catch { setError("Couldn't reach the API."); }
    setBusy(false);
  }, [result]);

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault(); setDrag(false);
    const f = e.dataTransfer.files?.[0];
    if (f) { setFile(f); }
  };

  if (result?.ok && result.stats && result.urls) {
    const s = result.stats, urls = result.urls;
    return (
      <main className="wrap">
        <h1>{result.stem}</h1>
        <p className="sub">{s.conduit} · fabrication package</p>

        {s.review > 0 && !result.resolved ? (
          <div className="banner warn">
            <b>⚠ {s.review} run(s) need review</b> (odd angles / drift). Bend as-is, or standardize the odd angles:
            <div className="row" style={{ marginTop: 10 }}>
              <button className="btn" onClick={standardize} disabled={busy}>
                {busy ? "Working…" : "Standardize odd angles"}
              </button>
              <a className="btn ghost" href={`${API}${urls.health}`} target="_blank" rel="noreferrer">See the report</a>
            </div>
            <pre className="flags">{s.flags.join("\n")}</pre>
          </div>
        ) : (
          <div className="banner ok">✓ All runs ready to fabricate{result.resolved ? " — odd angles standardized" : ""}.</div>
        )}

        <div className="tiles">
          {TILES.map(([k, label]) => (
            <div className="tile" key={label}>
              <div className="n">{String(s[k])}</div><div className="l">{label}</div>
            </div>
          ))}
        </div>

        <div className="cards">
          {LINKS.map(([key, title, desc]) => (
            <a className="card" key={key} href={`${API}${urls[key]}`} target="_blank" rel="noreferrer">
              <div className="t">{title}</div><div className="d">{desc}</div>
            </a>
          ))}
        </div>

        <div className="row" style={{ marginTop: 22 }}>
          <a className="btn" href={`${API}${urls.download}`}>⭳ Download package (.zip)</a>
          <button className="btn ghost" onClick={() => { setResult(null); setFile(null); }}>Process another</button>
        </div>
      </main>
    );
  }

  return (
    <main className="wrap">
      <h1>Conduit Fabrication Pipeline</h1>
      <p className="sub">
        Drop a Revit / BIM <b>.ifc</b> export — get bend cards, a cut list, a bill of
        materials, a data-health report, and a machine job.
      </p>

      <div
        className={`drop ${drag ? "hi" : ""}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
      >
        <div style={{ fontSize: 40 }}>📁</div>
        <div><b>Drag &amp; drop</b> your <b>.ifc</b> here, or <b>click to browse</b></div>
        <div className="sub" style={{ marginTop: 8 }}>{file ? file.name : "no file chosen"}</div>
        <input ref={inputRef} type="file" accept=".ifc" hidden
          onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </div>

      <div className="row" style={{ marginTop: 16 }}>
        <button className="btn" disabled={!file || busy} onClick={() => file && upload(file, resolve)}>
          {busy ? "Processing…" : "Process"}
        </button>
        <label className="chk">
          <input type="checkbox" checked={resolve} onChange={(e) => setResolve(e.target.checked)} />
          Standardize odd angles (snap to trade)
        </label>
      </div>

      {error && <div className="banner warn" style={{ marginTop: 20 }}>⚠ {error}</div>}
    </main>
  );
}
