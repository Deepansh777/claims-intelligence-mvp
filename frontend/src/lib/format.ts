import type { Format } from "./types";

const NUMERIC_TYPES = new Set(["int2", "int4", "int8", "float4", "float8", "numeric"]);

export const isNumericType = (type: string) => NUMERIC_TYPES.has(type);

const fixed = (v: number, digits: number) =>
  v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });

/** Negatives in parentheses, unless the shown value rounds to zero. */
const negative = (v: number, s: string) => (v < 0 && /[1-9]/.test(s) ? `(${s})` : s);

/** Same output as format_value in backend/app/llm/guards.py, so text and visuals agree. */
export function formatValue(v: unknown, fmt: Format): string {
  if (v === null || v === undefined) return "not available";
  if (fmt === "text" || fmt === "date" || typeof v !== "number") return String(v);
  return negative(v, formatAbs(Math.abs(v), fmt));
}

function formatAbs(v: number, fmt: Format): string {
  switch (fmt) {
    case "usd":
      return `$${fixed(v, 0)}`;
    case "usd2":
      return `$${fixed(v, 2)}`;
    case "int":
      return fixed(v, 0);
    case "pct":
      return `${fixed(v, 1)}%`;
    case "pct_ratio":
      return `${fixed(v * 100, 1)}%`;
    case "rate":
      return fixed(v, 2);
    default:
      return v.toLocaleString("en-US", { maximumFractionDigits: 2 });
  }
}

/** Compact axis tick, as in the static charts. */
export function formatTick(v: number, fmt: Format): string {
  const abs = Math.abs(v);
  const compact =
    abs >= 1e6
      ? `${(abs / 1e6).toFixed(1)}M`
      : abs >= 1e4
        ? `${(abs / 1e3).toFixed(0)}k`
        : abs >= 1e3
          ? `${(abs / 1e3).toFixed(1).replace(/\.0$/, "")}k`
          : String(Math.round(abs * 100) / 100);
  if (fmt === "usd" || fmt === "usd2") return negative(v, `$${compact}`);
  if (fmt === "pct") return negative(v, `${compact}%`);
  if (fmt === "pct_ratio") return negative(v, `${Math.round(abs * 100)}%`);
  return negative(v, compact);
}

export const formatDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

export const formatMs = (ms: number | null | undefined) =>
  ms == null ? "—" : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
