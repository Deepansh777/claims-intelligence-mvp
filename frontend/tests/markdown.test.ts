import assert from "node:assert/strict";
import test from "node:test";
import { parseMarkdown, splitFences } from "../src/lib/markdown.ts";

test("splits prose and code, preserving indentation", () => {
  const text = "Here it is:\n\n```Python\ndef f(x):\n    return x\n```\n\nRun it with Python 3.";
  assert.deepEqual(splitFences(text), [
    { text: "Here it is:" },
    { lang: "python", code: "def f(x):\n    return x" },
    { text: "Run it with Python 3." },
  ]);
});

test("plain text and unclosed fences stay text", () => {
  assert.deepEqual(splitFences("No code here."), [{ text: "No code here." }]);
  assert.deepEqual(splitFences("```sql\nSELECT 1"), [{ text: "```sql\nSELECT 1" }]);
});

test("block without a language", () => {
  assert.deepEqual(splitFences("```\na\n\n  b\n```"), [{ lang: "", code: "a\n\n  b" }]);
});

test("methodology markdown parses to text-only blocks", () => {
  const md = "# Title\n\nGenerated today.\n\n## Scope\n\n| Item | Detail |\n| --- | --- |\n| Request | # a \\| b |\n\n### Limitations\n\n- One\n- <b>Two</b>\n";
  assert.deepEqual(parseMarkdown(md), [
    { type: "heading", level: 1, text: "Title" },
    { type: "paragraph", text: "Generated today." },
    { type: "heading", level: 2, text: "Scope" },
    { type: "table", head: ["Item", "Detail"], rows: [["Request", "# a | b"]] },
    { type: "heading", level: 3, text: "Limitations" },
    { type: "list", items: ["One", "<b>Two</b>"] },
  ]);
});
