import assert from "node:assert/strict";
import test from "node:test";
import { autoDismisses, clock, stepLabel } from "../src/lib/builds.ts";

test("only completed and cancelled toasts close themselves", () => {
  assert.equal(autoDismisses("built"), true);
  assert.equal(autoDismisses("cancelled"), true);
  assert.equal(autoDismisses("failed"), false);
  assert.equal(autoDismisses("running"), false);
});

test("clock shows m:ss", () => {
  assert.equal(clock(0), "0:00");
  assert.equal(clock(102_400), "1:42");
  assert.equal(clock(-5), "0:00");
});

test("step label stays within 1..total", () => {
  assert.equal(stepLabel(0, 4), "Step 1 of 4");
  assert.equal(stepLabel(3, 4), "Step 3 of 4");
  assert.equal(stepLabel(9, 4), "Step 4 of 4");
});
