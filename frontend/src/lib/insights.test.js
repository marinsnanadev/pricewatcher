import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  actionInfo,
  dealInfo,
  diagnosisText,
  discountText,
  healthInfo,
  layerShares,
  msText,
  percentText,
} from "./insights.js";

describe("discountText", () => {
  it("shows discounts, premiums, zero and unknown", () => {
    assert.equal(discountText(39.6), "−40%");
    assert.equal(discountText(-12.2), "+12%");
    assert.equal(discountText(0.3), "0%");
    assert.equal(discountText(null), "—");
  });
});

describe("labels", () => {
  it("knows every verdict the backend can send", () => {
    for (const v of ["genuine_deal", "fair_price", "price_above_usual", "misleading_discount", "fake_discount", "insufficient_data"]) {
      assert.notEqual(dealInfo(v).label, v, `${v} has no friendly label`);
    }
    for (const a of ["buy_now", "wait", "neutral"]) assert.notEqual(actionInfo(a).label, a);
    for (const h of ["healthy", "degraded", "down", "idle"]) assert.notEqual(healthInfo(h).label, h);
  });

  it("falls back gracefully for anything new", () => {
    assert.deepEqual(dealInfo("something_new"), { label: "something_new", tone: "muted" });
  });

  it("explains diagnoses and stays quiet when there is none", () => {
    assert.match(diagnosisText("layout_changed"), /layout/);
    assert.match(diagnosisText("blocked"), /captcha/);
    assert.equal(diagnosisText(null), null);
    assert.match(diagnosisText("???"), /unknown/);
  });
});

describe("formatting", () => {
  it("percentText and msText", () => {
    assert.equal(percentText(0.943), "94%");
    assert.equal(percentText(null), "—");
    assert.equal(msText(420), "420ms");
    assert.equal(msText(2500), "2.5s");
    assert.equal(msText(null), "—");
  });

  it("layerShares sorts by count and sums to ~100", () => {
    const shares = layerShares({ markup: 1, json_ld: 3 });
    assert.deepEqual(shares.map((s) => s.name), ["json_ld", "markup"]);
    assert.deepEqual(shares.map((s) => s.pct), [75, 25]);
    assert.deepEqual(layerShares({}), []);
    assert.deepEqual(layerShares(undefined), []);
  });
});
