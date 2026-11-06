export type Part = { text: string } | { lang: string; code: string };

// shortcut: only top-level ``` fences at line start; unclosed or indented fences stay text. Use a Markdown parser if answers need more.
const FENCE = /^```[ \t]*([\w+#.-]*)[^\n]*\n([\s\S]*?)^```[ \t]*$/gm;

export type Block =
  | { type: "heading"; level: number; text: string }
  | { type: "paragraph"; text: string }
  | { type: "list"; items: string[] }
  | { type: "table"; head: string[]; rows: string[][] };

const unescape = (s: string) => s.replace(/\\\|/g, "|");
const cells = (line: string) =>
  line.trim().replace(/^\|/, "").replace(/(?<!\\)\|$/, "").split(/(?<!\\)\|/).map((c) => unescape(c.trim()));

// shortcut: the subset the methodology writer emits (headings, paragraphs, "- " lists, pipe tables), as text only.
export function parseMarkdown(md: string): Block[] {
  const blocks: Block[] = [];
  let prev = "";
  for (const line of md.split("\n")) {
    const last = blocks[blocks.length - 1];
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) blocks.push({ type: "heading", level: heading[1].length, text: unescape(heading[2]) });
    else if (line.startsWith("- ")) {
      if (last?.type === "list" && prev.startsWith("- ")) last.items.push(unescape(line.slice(2)));
      else blocks.push({ type: "list", items: [unescape(line.slice(2))] });
    } else if (line.startsWith("|")) {
      if (/^\|[\s|:-]+$/.test(line)) {
        // header separator row
      } else if (last?.type === "table" && prev.startsWith("|")) last.rows.push(cells(line));
      else blocks.push({ type: "table", head: cells(line), rows: [] });
    } else if (line.trim()) {
      if (last?.type === "paragraph" && prev.trim()) last.text += " " + unescape(line.trim());
      else blocks.push({ type: "paragraph", text: unescape(line.trim()) });
    }
    prev = line;
  }
  return blocks;
}

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
