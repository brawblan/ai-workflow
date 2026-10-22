import { test } from "node:test";
import assert from "node:assert/strict";
import { label } from "./widget.js";

test("one item", () => {
  assert.equal(label(1), "1 item");
});
