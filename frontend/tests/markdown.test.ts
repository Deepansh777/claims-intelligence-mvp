import assert from "node:assert/strict";
import test from "node:test";
import { splitFences } from "../src/lib/markdown.ts";

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
