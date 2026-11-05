import type { Format } from "./types";

const NUMERIC_TYPES = new Set(["int2", "int4", "int8", "float4", "float8", "numeric"]);

export const isNumericType = (type: string) => NUMERIC_TYPES.has(type);

const fixed = (v: number, digits: number) =>
  v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });

/** Same output as format_value in backend/app/llm/guards.py, so text and visuals agree. */
export function formatValue(v: unknown, fmt: Format): string {
  if (v === null || v === undefined) return "not available";
  if (fmt === "text" || fmt === "date" || typeof v !== "number") return String(v);
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
      ? `${(v / 1e6).toFixed(1)}M`
      : abs >= 1e4
        ? `${(v / 1e3).toFixed(0)}k`
        : abs >= 1e3
          ? `${(v / 1e3).toFixed(1).replace(/\.0$/, "")}k`
          : String(Math.round(v * 100) / 100);
  if (fmt === "usd" || fmt === "usd2") return `$${compact}`;
  if (fmt === "pct") return `${compact}%`;
  if (fmt === "pct_ratio") return `${Math.round(v * 100)}%`;
  return compact;
}

export const formatDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

export const formatMs = (ms: number | null | undefined) =>
  ms == null ? "—" : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
