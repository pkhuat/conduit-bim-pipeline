// API base + shared types for the conduit fabrication app.
export const API =
  process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:5050";

export type Job = {
  stem: string; name: string; conduit: string;
  conduits: number; bends: number; review: number; mtime: number;
};

export type Bend = { advance: number; angle: number; rotate: number; roll_dir: number };
export type Piece = {
  piece: number; load: string; end: string;
  length_ft: number; cut_length_ft: number; bends: Bend[]; tail_advance: number;
};
export type Path3D = { verts: number[][]; angles: number[]; cuts?: number[]; od_mm?: number | null; bend_radius_mm?: number | null };
export type Run = {
  run: number; kind: string; od_mm: number | null; bend_radius_mm: number | null; die: string;
  length_ft: number; n_bends: number; n_sticks: number;
  review: string[]; svg: string | null; path: Path3D | null; bends: Bend[]; pieces: Piece[];
};
export type Stats = {
  conduit: string; conduits: number; bends: number; sticks: number;
  total_ft: number; raw_sticks: number; review: number; flags: string[];
};
export type Material = {
  label: string; runs: number; sticks: number; couplers: number; bends: number;
  offsets: number; saddles: number; buy_sticks: number; len_ft: number;
};
export type JobDetail = {
  ok: boolean; stem: string; name: string; stats: Stats;
  urls: Record<string, string>; runs: Run[]; materials?: Material[]; sim: boolean; error?: string;
};

export type Command = { board: number; cmd: string; response: string; stick?: number };
export type Axis = { position: number; enabled: boolean };
export type MachineResult = {
  ok: boolean; run: number | string;
  sticks: { run: number; piece: number; bends: number }[];
  commands: Command[]; truncated: boolean; warnings: string[];
  final_state: Record<string, Axis>;
  counts: { commands: number; warnings: number; sticks: number };
  svg?: string | null; path?: Path3D | null; error?: string;
};

async function j<T>(r: Response): Promise<T> {
  const data = await r.json();
  return data as T;
}

export const getJobs = () =>
  fetch(`${API}/api/jobs`, { cache: "no-store" }).then(j<{ ok: boolean; jobs: Job[] }>);

export const getJob = (stem: string) =>
  fetch(`${API}/api/jobs/${stem}`, { cache: "no-store" }).then(j<JobDetail>);

export const runMachine = (stem: string, run: number | "all" | number[]) =>
  fetch(`${API}/api/jobs/${stem}/machine`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(Array.isArray(run) ? { runs: run } : { run }),
  }).then(j<MachineResult>);

export const resolveRun = (stem: string, run: number) =>
  fetch(`${API}/api/jobs/${stem}/resolve-run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run }),
  }).then(j<JobDetail>);

export type TradeSize = { size: string; od_mm: number };
export const getTradeSizes = () =>
  fetch(`${API}/api/trade-sizes`, { cache: "no-store" })
    .then(j<{ ok: boolean; sizes: TradeSize[] }>);

export const setSize = (stem: string, run: number, od_mm: number) =>
  fetch(`${API}/api/jobs/${stem}/set-size`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run, od_mm }),
  }).then(j<JobDetail>);

export type ManualBend = { angle: number; roll: number; distance: number };
export const runManual = (bends: ManualBend[]) =>
  fetch(`${API}/api/machine/manual`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bends }),
  }).then(j<MachineResult>);

export type Calibration = {
  calibrated: boolean; advance_steps_per_mm: number; rotate_steps_per_deg: number;
  bend_steps_per_deg: number; springback_factor: number; springback_offset_deg: number;
};
export const getCalibration = () =>
  fetch(`${API}/api/calibration`, { cache: "no-store" }).then(j<{ ok: boolean; calibration: Calibration }>);
export const saveCalibration = (patch: Partial<Calibration>) =>
  fetch(`${API}/api/calibration`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch),
  }).then(j<{ ok: boolean; calibration: Calibration }>);
export const programUrl = (stem: string, run: number) => `${API}/api/jobs/${stem}/program?run=${run}`;

export const fileUrl = (path: string) => `${API}${path}`;
