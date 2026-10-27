/* Tests for the valuation engine. Run: node --test pulse/test/ */
import test from "node:test";
import assert from "node:assert/strict";
import * as C from "../js/crowd.js";

const ev = (markets, extra = {}) => ({slug: "x", title: "x", ...extra,
  markets: markets.map(([title, yes, more = {}]) => ({title, yes, ...more}))});
const close = (a, b, tol = 1e-9) => assert.ok(Math.abs(a - b) <= tol * Math.max(1, Math.abs(b)), `${a} vs ${b}`);

test("bracket titles in every format the markets use", () => {
  assert.deepEqual(C.parseBracket("$1.25–$1.50T"), {kind: "range", lo: 1.25e12, hi: 1.5e12});
  assert.deepEqual(C.parseBracket("750B–1T"), {kind: "range", lo: 750e9, hi: 1e12});
  assert.deepEqual(C.parseBracket("$1.0T–$1.25T"), {kind: "range", lo: 1e12, hi: 1.25e12});
  assert.deepEqual(C.parseBracket("<100B"), {kind: "below", hi: 100e9});
  assert.deepEqual(C.parseBracket("<$1T"), {kind: "below", hi: 1e12});
  assert.deepEqual(C.parseBracket("$2.50T+"), {kind: "above", lo: 2.5e12});
  assert.deepEqual(C.parseBracket("600B+"), {kind: "above", lo: 600e9});
  assert.equal(C.parseBracket("No IPO by December 31, 2027"), null);
});

test("a uniform distribution has the textbook mean and quantiles", () => {
  const d = C.capDistribution(ev([["$1–$2T", 0.25], ["$2–$3T", 0.25], ["$3–$4T", 0.25], ["$4–$5T", 0.25]]));
  close(C.mean(d), 3e12);
  close(C.quantile(d, 0.5), 3e12);
  close(C.quantile(d, 0.1), 1.4e12);
  close(C.quantile(d, 0.9), 4.6e12);
  close(C.probAtLeast(d, 3e12), 0.5);
  close(C.probAtLeast(d, 0), 1);
  close(C.probAtLeast(d, 9e12), 0);
});

test("prices are renormalised and 'No IPO' is reported, not counted as zero", () => {
  const d = C.capDistribution(ev([["$1–$2T", 0.2], ["$2–$3T", 0.2], ["$3–$4T", 0.2], ["No IPO by December 31, 2027", 0.4]]));
  close(d.total, 0.6);
  close(C.mean(d), 2.5e12);
  close(d.pNone, 0.4);
});

test("open brackets are spread by the stated assumption and the sensitivity brackets the mean", () => {
  const d = C.capDistribution(ev([["<$1T", 0.2], ["$1–$2T", 0.5], ["$2T+", 0.3]]));
  close(d.brackets[0].lo, 0.5e12);
  close(d.brackets[2].hi, 2.5e12);
  close(d.openTopMass, 0.3);
  close(d.openBottomMass, 0.2);
  const s = C.summarize(d);
  assert.ok(s.meanIfTopLow < s.mean && s.mean < s.meanIfTopHigh);
  const notes = C.assumptions(d, v => `$${(v / 1e12).toFixed(2)}T`);
  assert.ok(notes.some(n => n.includes("no ceiling")) && notes.some(n => n.includes("no floor")));
});

test("fewer than three brackets is not a distribution", () => {
  assert.equal(C.capDistribution(ev([["$1–$2T", 0.5], ["$2T+", 0.5]])), null);
});

test("the event that leaves least to assumption is chosen", () => {
  const vague = ev([["<600B", 0.05], ["600B–800B", 0.05], ["800B+", 0.9]], {slug: "vague"});
  const sharp = ev([["<1T", 0.05], ["$1–$2T", 0.6], ["$2–$3T", 0.3], ["$3T+", 0.05]], {slug: "sharp"});
  assert.equal(C.bestDistribution([vague, sharp]).slug, "sharp");
});

test("the day's move is the change in the mean, from each bracket's own move", () => {
  const d = C.capDistribution(ev([["$1–$2T", 0.6, {dayChange: 0.1}], ["$2–$3T", 0.2, {dayChange: -0.1}], ["$3–$4T", 0.2, {dayChange: 0}]]));
  const s = C.summarize(d);
  // yesterday 0.5 / 0.3 / 0.2: mean 2.2T. today 0.6 / 0.2 / 0.2: mean 2.1T.
  close(s.dayChange, 2.1 / 2.2 - 1, 1e-9);
});

test("isotonic regression fixes a dip and leaves a clean series alone", () => {
  assert.deepEqual(C.isotonic([0.1, 0.3, 0.2, 0.6]), [0.1, 0.25, 0.25, 0.6]);
  assert.deepEqual(C.isotonic([0.1, 0.2, 0.3]), [0.1, 0.2, 0.3]);
});

test("the timeline is ordered, monotone, treats closed markets as resolved, and finds the median", () => {
  const t = C.ipoTimeline(ev([
    ["December 31, 2026", 0.40], ["June 30, 2026", 0.02, {closed: true}],
    ["March 31, 2027", 0.35], ["June 30, 2027", 0.70],
  ]), Date.UTC(2026, 9, 27));
  assert.deepEqual(t.points.map(p => p.title), ["June 30, 2026", "December 31, 2026", "March 31, 2027", "June 30, 2027"]);
  assert.equal(t.points[0].p, 0);                 // closed and did not happen
  assert.ok(t.adjusted);                          // Dec 0.40 > Mar 0.35 was pooled
  for(let i = 1; i < t.points.length; i++) assert.ok(t.points[i].p >= t.points[i - 1].p);
  assert.equal(t.future.length, 3);
  const m = new Date(t.median.t);
  assert.equal(m.getUTCFullYear(), 2027);
  assert.ok(m.getUTCMonth() >= 3 && m.getUTCMonth() <= 5);
});

test("touch ladders find where the valuation stands and keep higher levels no likelier", () => {
  const l = C.touchLadder(ev([["↑$200B", 0.065], ["↑$150B", 0.37], ["↑$175B", 0.4], ["↑$110B", 1], ["↓$80B", 1], ["↓$70B", 0.06]]));
  assert.equal(l.floor, 110e9);
  assert.deepEqual(l.next.map(r => r.level), [150e9, 175e9, 200e9]);
  for(let i = 1; i < l.up.length; i++) assert.ok(l.up[i].p <= l.up[i - 1].p + 1e-12);
});

test("a stake in percent scales with the company and dilution", () => {
  const d = C.capDistribution(ev([["$1–$2T", 0.5], ["$2–$3T", 0.25], ["$3–$4T", 0.25]]));
  const r = C.stakeOutcomes(d, {mode: "percent", percent: 0.001}, 0);
  close(r.median, 0.001 / 100 * C.quantile(d, 0.5));
  close(r.mean, 0.001 / 100 * C.mean(d), 1e-6);
  const diluted = C.stakeOutcomes(d, {mode: "percent", percent: 0.001}, 0.2);
  close(diluted.median, r.median * 0.8);
});

test("options are worth nothing below the strike and the target odds invert correctly", () => {
  const d = C.capDistribution(ev([["$1–$2T", 0.5], ["$2–$3T", 0.5], ["$3–$4T", 0]]));
  // 1,000 options, 1,000,000,000 shares in total, strike $1,500 a share:
  // the company must be worth more than $1.5T for the options to pay.
  const h = {mode: "shares", shares: 1000, totalShares: 1e9, strike: 1500};
  const r = C.stakeOutcomes(d, h, 0, 500_000);
  close(r.pZero, 0.25, 1e-2);                     // half of the $1–2T bracket is under water
  // $500k needs $500/share of profit: value per share $2,000, company $2T.
  close(r.pTarget, 0.5, 1e-6);
});
