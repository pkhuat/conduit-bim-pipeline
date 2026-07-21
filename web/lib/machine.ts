// Shared client-side model of the machine axes, driven by the command stream.
export type AxisMap = Record<string, { position: number; enabled: boolean }>;
export const AXES = ["ADVANCE", "ROTATE", "BEND", "SQUEEZE"];

export const freshAxes = (): AxisMap =>
  Object.fromEntries(AXES.map((a) => [a, { position: 0, enabled: false }]));

export function applyCmd(ax: AxisMap, cmd: string) {
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
