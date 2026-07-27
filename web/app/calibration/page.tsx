"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getCalibration, saveCalibration, type Calibration } from "../../lib/api";

const FIELDS: { key: keyof Calibration; label: string; hint: string; step: number }[] = [
  { key: "advance_steps_per_mm", label: "ADVANCE — steps / mm", hint: "feed axis", step: 0.001 },
  { key: "rotate_steps_per_deg", label: "ROTATE — steps / °", hint: "roll axis", step: 0.1 },
  { key: "bend_steps_per_deg", label: "BEND — steps / °", hint: "bend axis", step: 1 },
  { key: "springback_factor", label: "Springback — factor", hint: "commanded = target·(1+factor) + offset", step: 0.001 },
  { key: "springback_offset_deg", label: "Springback — offset (°)", hint: "added over-bend", step: 0.1 },
];

export default function CalibrationPage() {
  const [cal, setCal] = useState<Calibration | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => { getCalibration().then((d) => setCal(d.calibration)).catch(() => {}); }, []);

  const set = (k: keyof Calibration, v: number | boolean) => { setSaved(false); setCal((c) => c && { ...c, [k]: v }); };
  const save = async () => {
    if (!cal) return;
    setBusy(true);
    try { const d = await saveCalibration(cal); setCal(d.calibration); setSaved(true); }
    catch { alert("Couldn't reach the API."); }
    setBusy(false);
  };

  if (!cal) return <main className="wrap"><div className="empty"><span className="spin" style={{ borderColor: "#9fb0c8", borderTopColor: "transparent" }} /> loading…</div></main>;

  const inSteps = Math.round(cal.advance_steps_per_mm * 100);            // 100 mm
  const bendSteps = Math.round(cal.bend_steps_per_deg * (90 * (1 + cal.springback_factor) + cal.springback_offset_deg));

  return (
    <main className="wrap" style={{ maxWidth: 760 }}>
      <div className="crumbs"><Link href="/">Jobs</Link> / Calibration</div>
      <h1>Machine calibration</h1>
      <p className="sub">The shop&rsquo;s measured numbers turn every job into <b>motor steps</b>. Until this is on, programs export in conduit units (mm / °), clearly flagged.</p>

      {cal.calibrated
        ? <div className="banner ok">✓ Calibrated — jobs &amp; downloaded programs carry motor-step values.</div>
        : <div className="banner warn">⚠ Not calibrated — programs export in <b>mm / degrees</b>, not motor steps. Enter the measured values below and turn it on.</div>}

      <div className="panel">
        <label className="chk" style={{ fontSize: 15, marginBottom: 16 }}>
          <input type="checkbox" checked={cal.calibrated} onChange={(e) => set("calibrated", e.target.checked)} />
          <b>Calibrated</b> — apply these to every job &amp; program
        </label>
        <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 14 }}>
          {FIELDS.map((f) => (
            <div key={f.key} className="row" style={{ justifyContent: "space-between", gap: 14 }}>
              <div>
                <div style={{ fontWeight: 600 }}>{f.label}</div>
                <div className="muted" style={{ fontSize: 12.5 }}>{f.hint}</div>
              </div>
              <input type="number" step={f.step} value={cal[f.key] as number}
                onChange={(e) => set(f.key, parseFloat(e.target.value) || 0)}
                style={{ width: 170, padding: "9px 11px", borderRadius: 9, border: "1px solid var(--border-2)", fontSize: 15, fontFamily: "var(--font-mono, monospace)" }} />
            </div>
          ))}
        </div>

        <div className="banner" style={{ background: "var(--sunken)", border: "1px solid var(--border)", marginTop: 18, fontFamily: "var(--font-mono, monospace)", fontSize: 13 }}>
          quick check → 100&nbsp;mm feed = <b>{inSteps.toLocaleString()}</b> ADVANCE steps &nbsp;·&nbsp; a 90° bend = <b>{bendSteps.toLocaleString()}</b> BEND steps
        </div>

        <div className="row" style={{ marginTop: 18 }}>
          <button className="btn" onClick={save} disabled={busy}>{busy ? <><span className="spin" /> Saving…</> : "Save calibration"}</button>
          {saved && <span className="badge ok">saved</span>}
        </div>
      </div>

      <p className="muted" style={{ fontSize: 12.5, marginTop: 14 }}>
        Stored on the server. The BEND anchor (~19,507 steps/°) is from Josh&rsquo;s bend-calibration session — replace with the final measured value. Springback zeros mean no over-bend compensation yet.
      </p>
    </main>
  );
}
