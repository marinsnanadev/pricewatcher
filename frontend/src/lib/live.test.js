import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { applyChecked, applyCheckedToHistory } from "./live.js";

const product = { id: "p1", current_price: 100, previousPrice: 110, name: "Fone" };

const event = (over = {}) => ({
  product_id: "p1",
  status: "success",
  current_price: 80,
  previous_price: 100,
  changed: true,
  recorded: true,
  checked_at: "2026-10-21T12:00:00+00:00",
  next_check_at: "2026-10-21T18:00:00+00:00",
  last_error: null,
  consecutive_failures: 0,
  ...over,
});

describe("applyChecked", () => {
  it("applies a price drop and flags it", () => {
    const next = applyChecked(product, event());
    assert.equal(next.current_price, 80);
    assert.equal(next.previousPrice, 100);
    assert.equal(next.flash, "down");
    assert.equal(next.flashKey, 1);
    assert.equal(next.name, "Fone"); // the rest is untouched
    assert.equal(product.current_price, 100); // and the input isn't mutated
  });

  it("flags a rise and bumps the key on every change so the animation replays", () => {
    const up = applyChecked(product, event({ current_price: 120, previous_price: 100 }));
    assert.equal(up.flash, "up");
    const again = applyChecked(up, event({ current_price: 130, previous_price: 120 }));
    assert.equal(again.flashKey, 2);
  });

  it("an unchanged price only refreshes the check times", () => {
    const next = applyChecked(product, event({ changed: false, current_price: 100 }));
    assert.equal(next.flash, undefined);
    assert.equal(next.previousPrice, 110);
    assert.equal(next.last_checked_at, "2026-10-21T12:00:00+00:00");
  });

  it("an error keeps the old price and shows the error", () => {
    const next = applyChecked(
      product,
      event({ status: "error", current_price: 100, changed: false, last_error: "Amazon showed a captcha", consecutive_failures: 2 })
    );
    assert.equal(next.current_price, 100);
    assert.equal(next.last_error, "Amazon showed a captcha");
    assert.equal(next.consecutive_failures, 2);
  });

  it("a later success clears the error", () => {
    const failing = { ...product, last_error: "boom" };
    assert.equal(applyChecked(failing, event({ changed: false })).last_error, null);
  });
});

describe("applyCheckedToHistory", () => {
  const history = [{ id: "h1", product_id: "p1", price: 100, collected_at: "2026-10-20T12:00:00+00:00" }];

  it("appends a recorded point", () => {
    const next = applyCheckedToHistory(history, event());
    assert.equal(next.length, 2);
    assert.deepEqual(
      { price: next[1].price, at: next[1].collected_at },
      { price: 80, at: "2026-10-21T12:00:00+00:00" }
    );
    assert.equal(history.length, 1); // not mutated
  });

  it("ignores checks that weren't recorded, and errors", () => {
    assert.equal(applyCheckedToHistory(history, event({ recorded: false })), history);
    assert.equal(applyCheckedToHistory(history, event({ status: "error" })), history);
  });

  it("doesn't add the same point twice", () => {
    const once = applyCheckedToHistory(history, event());
    assert.equal(applyCheckedToHistory(once, event()), once);
  });
});
