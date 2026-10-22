// Number formatting of the desktop UI and hidden amounts (SPEC §8.7): format.js is the
// single place where amounts are formatted, so hiding them there covers every view.
import { test } from "node:test";
import assert from "node:assert/strict";

import * as f from "../../mywealth/web/js/format.js";

const visible = (fn) => { f.setMasked(false); return fn(); };
const hidden = (fn) => { f.setMasked(true); try { return fn(); } finally { f.setMasked(false); } };

test("amounts are formatted it-IT with the currency code after", () => {
  visible(() => {
    assert.equal(f.money("1234.5", "EUR"), "1.234,50 EUR");
    assert.equal(f.money(1000, "JPY", 0), "1.000 JPY");
    assert.equal(f.signedMoney("-12.3", "USD"), "−12,30 USD");
    assert.equal(f.pct(4.25, 1), "+4,3%");
    assert.equal(f.share(42), "42,0%");
    assert.equal(f.tone(-1), "neg");
  });
});

test("hidden amounts keep the currency and lose digits, sign and colour", () => {
  hidden(() => {
    assert.equal(f.money("1234.5", "EUR"), `${f.MASK} EUR`);
    assert.equal(f.money(0, "USD"), `${f.MASK} USD`);
    assert.equal(f.signedMoney("-12.3", "USD"), `${f.MASK} USD`);
    assert.equal(f.signedMoney(99, "CHF"), `${f.MASK} CHF`);
    assert.equal(f.pct(-3.2), "•••%");
    assert.equal(f.share(42), "•••%");
    assert.equal(f.compact(125000), "•••");
    assert.equal(f.qty("12.5", 4), f.MASK);
    assert.equal(f.maskRaw("-45,20"), f.MASK);
    assert.equal(f.tone(-1), "");
    assert.equal(f.tone(5), "");
  });
});

test("no digit of the value survives in the hidden text", () => {
  hidden(() => {
    for (const out of [f.money("98765.43", "EUR"), f.signedMoney(-98765, "GBP"), f.pct(98.7), f.compact(98765), f.qty(98.7)]) {
      assert.doesNotMatch(out, /\d/);
    }
  });
});

test("missing values, exchange rates and prices stay as they are", () => {
  hidden(() => {
    assert.equal(f.money(null), "—");
    assert.equal(f.pct(null), "—");
    assert.equal(f.qty(null), "—");
    assert.equal(f.maskRaw(""), "");
    assert.equal(f.num("1.08345", 4), "1,0835");
  });
});

test("showing again restores the normal format", () => {
  f.setMasked(true);
  f.setMasked(false);
  assert.equal(f.isMasked(), false);
  assert.equal(f.money("10", "EUR"), "10,00 EUR");
});
