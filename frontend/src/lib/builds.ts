import type { BuildStatus } from "./types";

export const AUTO_DISMISS_MS = 120_000;

/** Completed and cancelled outcomes close themselves; failures stay until dismissed. */
export const autoDismisses = (status: BuildStatus) => status === "built" || status === "cancelled";

/** Elapsed time as m:ss. */
export function clock(ms: number) {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export const stepLabel = (done: number, total: number) => `Step ${Math.min(Math.max(done, 1), total)} of ${total}`;
