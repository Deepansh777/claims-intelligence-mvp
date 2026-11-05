export type Part = { text: string } | { lang: string; code: string };

// shortcut: only top-level ``` fences at line start; unclosed or indented fences stay text. Use a Markdown parser if answers need more.
const FENCE = /^```[ \t]*([\w+#.-]*)[^\n]*\n([\s\S]*?)^```[ \t]*$/gm;

/** Splits answer text into prose and fenced code blocks, keeping code exactly as written. */
export function splitFences(text: string): Part[] {
  const parts: Part[] = [];
  let last = 0;
  for (const m of text.matchAll(FENCE)) {
    const before = text.slice(last, m.index).trim();
    if (before) parts.push({ text: before });
    parts.push({ lang: m[1].toLowerCase(), code: m[2].replace(/\n$/, "") });
    last = m.index! + m[0].length;
  }
  const rest = text.slice(last).trim();
  if (rest) parts.push({ text: rest });
  return parts;
}
