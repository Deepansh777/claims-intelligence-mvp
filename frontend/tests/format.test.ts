import assert from "node:assert/strict";
import test from "node:test";
import { toCsv } from "../src/lib/download.ts";
import { formatTick, formatValue } from "../src/lib/format.ts";

test("negatives show in parentheses with their unit", () => {
  assert.equal(formatValue(-1250, "usd"), "($1,250)");
  assert.equal(formatValue(-90, "usd"), "($90)");
  assert.equal(formatValue(-0.052, "pct_ratio"), "(5.2%)");
  assert.equal(formatValue(-0.4, "usd"), "$0");
  assert.equal(formatValue(25, "usd"), "$25");
  assert.equal(formatTick(-1_500_000, "usd"), "($1.5M)");
});

test("csv keeps raw signed values and neutralises formulas", () => {
  assert.equal(
    toCsv(["name", "amount"], [["=SUM(A1)", -1250.125], ['a "b", c', null], ["-x", 0.1 + 0.2]]),
    "name,amount\r\n'=SUM(A1),-1250.125\r\n\"a \"\"b\"\", c\",\r\n'-x,0.30000000000000004\r\n",
  );
});
