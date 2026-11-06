// Browser-side exports, so they also work in saved and offline dashboards with no API behind them.

// Spreadsheet apps execute text cells starting with these as formulas (as csv_cell on the server).
const FORMULA = /^[=+\-@\t\r]/;

function csvCell(v: unknown): string {
  if (v === null || v === undefined) return "";
  const s = typeof v === "string" && FORMULA.test(v) ? `'${v}` : String(v);
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** Raw values: numbers keep full precision and their sign. */
export const toCsv = (header: string[], rows: unknown[][]) =>
  [header, ...rows].map((r) => r.map(csvCell).join(",")).join("\r\n") + "\r\n";

export const fileStem = (title: string) =>
  title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 80) || "export";

function save(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const downloadCsv = (title: string, header: string[], rows: unknown[][]) =>
  save(`${fileStem(title)}.csv`, new Blob([toCsv(header, rows)], { type: "text/csv;charset=utf-8" }));

const PAD = 24;
const SCALE = 2;

/** The card's chart SVG drawn under its title, with the legend below when there is one. */
export async function downloadChartPng(card: HTMLElement, title: string, legend: { name: string; color: string }[]) {
  const svg = card.querySelector<SVGSVGElement>(".chart-wrap svg")!;
  const { width, height } = svg.getBoundingClientRect();
  const clone = svg.cloneNode(true) as SVGSVGElement;
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));
  clone.style.fontFamily = getComputedStyle(svg).fontFamily;
  const img = new Image();
  img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(new XMLSerializer().serializeToString(clone));
  await img.decode();

  const titleStyle = getComputedStyle(card.querySelector(".card-title")!);
  const bodyFont = getComputedStyle(card).fontFamily;
  const titleH = 40;
  const legendH = legend.length ? 32 : 0;
  const canvas = document.createElement("canvas");
  canvas.width = (width + PAD * 2) * SCALE;
  canvas.height = (PAD + titleH + height + legendH + PAD) * SCALE;
  const ctx = canvas.getContext("2d")!;
  ctx.scale(SCALE, SCALE);
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = titleStyle.color;
  ctx.font = `${titleStyle.fontSize} ${titleStyle.fontFamily}`;
  ctx.textBaseline = "top";
  ctx.fillText(title, PAD, PAD, width);
  ctx.drawImage(img, PAD, PAD + titleH, width, height);
  ctx.font = `12px ${bodyFont}`;
  ctx.textBaseline = "middle";
  let x = PAD;
  const y = PAD + titleH + height + legendH / 2;
  for (const { name, color } of legend) {
    ctx.fillStyle = color;
    ctx.fillRect(x, y - 5, 10, 10);
    ctx.fillStyle = "#142225";
    ctx.fillText(name, x + 16, y);
    x += 16 + ctx.measureText(name).width + 20;
  }
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
  if (blob) save(`${fileStem(title)}.png`, blob);
}
