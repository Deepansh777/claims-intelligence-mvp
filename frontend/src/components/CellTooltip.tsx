import { useEffect, useState } from "react";

const MAX_W = 480;
const GAP = 4;

type Tip = { text: string; left: number; top?: number; bottom?: number };

/** Full text of any truncated `.table` cell on hover; one listener covers every table on the page. */
// shortcut: hover only; keyboard users don't get it because cells aren't focusable (screen readers read the full text).
export function CellTooltip() {
  const [tip, setTip] = useState<Tip | null>(null);
  useEffect(() => {
    const over = (e: MouseEvent) => {
      const td = (e.target as Element).closest?.(".table td");
      if (!td || td.scrollWidth <= td.clientWidth) return setTip(null);
      const r = td.getBoundingClientRect();
      const left = Math.max(GAP, Math.min(r.left, window.innerWidth - MAX_W - GAP));
      const below = r.bottom + 120 < window.innerHeight;
      setTip({
        text: td.textContent ?? "",
        left,
        ...(below ? { top: r.bottom + GAP } : { bottom: window.innerHeight - r.top + GAP }),
      });
    };
    const hide = () => setTip(null);
    document.addEventListener("mouseover", over);
    document.addEventListener("scroll", hide, true);
    document.documentElement.addEventListener("mouseleave", hide);
    return () => {
      document.removeEventListener("mouseover", over);
      document.removeEventListener("scroll", hide, true);
      document.documentElement.removeEventListener("mouseleave", hide);
    };
  }, []);
  if (!tip) return null;
  return (
    <div className="cell-tip" role="tooltip" style={{ left: tip.left, top: tip.top, bottom: tip.bottom, maxWidth: MAX_W }}>
      {tip.text}
    </div>
  );
}
