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
export type Run = {
  run: number; kind: string; od_mm: number | null; die: string;
  length_ft: number; n_bends: number; n_sticks: number;
  review: string[]; bends: Bend[]; pieces: Piece[];
};
export type Stats = {
  conduit: string; conduits: number; bends: number; sticks: number;
  total_ft: number; raw_sticks: number; review: number; flags: string[];
};
export type JobDetail = {
  ok: boolean; stem: string; name: string; stats: Stats;
  urls: Record<string, string>; runs: Run[]; sim: boolean; error?: string;
};

export type Command = { board: number; cmd: string; response: string };
export type Axis = { position: number; enabled: boolean };
export type MachineResult = {
  ok: boolean; run: number | string;
  sticks: { run: number; piece: number; bends: number }[];
  commands: Command[]; truncated: boolean; warnings: string[];
  final_state: Record<string, Axis>;
  counts: { commands: number; warnings: number; sticks: number };
  error?: string;
};

async function j<T>(r: Response): Promise<T> {
  const data = await r.json();
  return data as T;
}

export const getJobs = () =>
  fetch(`${API}/api/jobs`, { cache: "no-store" }).then(j<{ ok: boolean; jobs: Job[] }>);

export const getJob = (stem: string) =>
  fetch(`${API}/api/jobs/${stem}`, { cache: "no-store" }).then(j<JobDetail>);

export const runMachine = (stem: string, run: number | "all") =>
  fetch(`${API}/api/jobs/${stem}/machine`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run }),
  }).then(j<MachineResult>);

export const fileUrl = (path: string) => `${API}${path}`;
