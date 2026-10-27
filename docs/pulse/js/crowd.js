/* The valuation engine. Pure functions, no page code, so it can be tested on
   its own and trusted wherever it is used.

   Prediction markets ask three kinds of question about a private company, and
   each one says something different:

     1. "What will the company be worth on its first day of trading?"
        A set of brackets ($1.5T to $1.75T, $1.75T to $2T, ...) whose prices are
        probabilities. Together they are a distribution of the listing value.

     2. "Will the company list by <date>?"
        One market per date. Read in order they trace the chance of a listing
        happening by each date, which is a timeline.

     3. "Will the company's valuation reach <level> by <date>?"
        Touch odds on the next private round. They are not a distribution of a
        final value, and are never treated as one here.

   Everything below turns those prices into numbers a person can use, and says
   exactly where an assumption had to be made.
*/

export const TRILLION = 1e12, BILLION = 1e9;

const RANGE = new RegExp(
  "^\\s*(?:(?<lt><)\\s*\\$?(?<upper>[\\d.]+)\\s*(?<upper_unit>[TB])" +
  "|\\$?(?<lo>[\\d.]+)\\s*(?<lo_unit>[TB])?\\s*[–-]\\s*\\$?(?<hi>[\\d.]+)\\s*(?<hi_unit>[TB])" +
  "|\\$?(?<plus>[\\d.]+)\\s*(?<plus_unit>[TB])\\s*\\+)\\s*$", "i");

const unitScale = u => ((u || "T").toUpperCase() === "T" ? TRILLION : BILLION);

/* One bracket title, such as "$1.25–$1.50T", "<100B" or "$2.50T+". */
export function parseBracket(title){
  const g = RANGE.exec(title || "");
  if(!g) return null;
  const d = g.groups;
  if(d.lt) return {kind: "below", hi: parseFloat(d.upper) * unitScale(d.upper_unit)};
  if(d.hi !== undefined){
    const hi = parseFloat(d.hi) * unitScale(d.hi_unit);
    const lo = parseFloat(d.lo) * unitScale(d.lo_unit || d.hi_unit);
    return {kind: "range", lo, hi};
  }
  return {kind: "above", lo: parseFloat(d.plus) * unitScale(d.plus_unit)};
}

export const DEFAULTS = {
  topMultiple: 1.25,       // an open top bracket "$2.5T+" is spread up to 1.25 times its floor
  topLow: 1.10,            // ...and the answer is also shown at 1.1 and 1.5 times
  topHigh: 1.50,
  bottomFraction: 0.5,     // an open bottom bracket "<$1T" is spread down to half its ceiling
};

/* The listing-value distribution in one event, or null if it is not one.

   Bracket prices are renormalised over the brackets alone. A separate
   "No IPO by ..." market is reported, not folded in: a value cannot be put on
   a listing that does not happen, and treating it as zero would quietly drag
   the answer down. */
export function capDistribution(event, opts = {}){
  const o = {...DEFAULTS, ...opts};
  const brackets = [], skipped = [];
  let pNone = null;
  for(const m of event.markets || []){
    if(m.yes == null || !isFinite(m.yes)) continue;
    if(/^\s*no\s+ipo/i.test(m.title)){ pNone = m.yes; continue; }
    const b = parseBracket(m.title);
    if(!b){ skipped.push(m.title); continue; }
    const prev = m.dayChange != null && isFinite(m.dayChange)
      ? Math.min(1, Math.max(0, m.yes - m.dayChange)) : null;
    if(b.kind === "below") brackets.push({lo: b.hi * o.bottomFraction, hi: b.hi, p: m.yes, prev, open: "bottom", title: m.title});
    else if(b.kind === "above") brackets.push({lo: b.lo, hi: b.lo * o.topMultiple, p: m.yes, prev, open: "top", title: m.title});
    else brackets.push({lo: b.lo, hi: b.hi, p: m.yes, prev, open: null, title: m.title});
  }
  brackets.sort((a, b) => a.lo - b.lo || a.hi - b.hi);
  const total = brackets.reduce((s, b) => s + b.p, 0);
  if(brackets.length < 3 || total <= 0) return null;
  for(const b of brackets) b.q = b.p / total;
  const top = brackets[brackets.length - 1], bottom = brackets[0];
  return {
    slug: event.slug, title: event.title,
    brackets, total, pNone, skipped,
    openTopMass: top.open === "top" ? top.q : 0,
    openBottomMass: bottom.open === "bottom" ? bottom.q : 0,
    opts: o,
  };
}

/* Several events often price the same listing. Use the one that leaves least
   to assumption: the smallest probability sitting in open-ended brackets. */
export function bestDistribution(events, opts){
  let best = null;
  for(const ev of events){
    if(!ev) continue;
    const d = capDistribution(ev, opts);
    if(!d) continue;
    const open = d.openTopMass + d.openBottomMass;
    if(!best || open < best.open) best = {dist: d, open};
  }
  return best ? best.dist : null;
}

export function mean(dist, probKey = "q"){
  return dist.brackets.reduce((s, b) => s + b[probKey] * (b.lo + b.hi) / 2, 0);
}

/* Value below which a fraction u of the probability sits, treating value as
   spread evenly inside each bracket. */
export function quantile(dist, u){
  let acc = 0;
  for(const b of dist.brackets){
    if(acc + b.q >= u - 1e-12){
      const within = b.q > 0 ? (u - acc) / b.q : 0;
      return b.lo + Math.min(1, Math.max(0, within)) * (b.hi - b.lo);
    }
    acc += b.q;
  }
  const last = dist.brackets[dist.brackets.length - 1];
  return last.hi;
}

/* Probability the value is at or above v. */
export function probAtLeast(dist, v){
  let p = 0;
  for(const b of dist.brackets){
    if(v <= b.lo) p += b.q;
    else if(v < b.hi) p += b.q * (b.hi - v) / (b.hi - b.lo);
  }
  return p;
}

function withTop(dist, multiple){
  const brackets = dist.brackets.map(b => ({...b}));
  const top = brackets[brackets.length - 1];
  if(top.open === "top") top.hi = top.lo * multiple;
  return {...dist, brackets};
}

/* The headline numbers for one listing-value distribution. */
export function summarize(dist){
  const o = dist.opts;
  const out = {
    mean: mean(dist),
    median: quantile(dist, 0.5),
    p10: quantile(dist, 0.10),
    p90: quantile(dist, 0.90),
    meanIfTopLow: mean(withTop(dist, o.topLow)),
    meanIfTopHigh: mean(withTop(dist, o.topHigh)),
    dayChange: null,
  };
  if(dist.brackets.every(b => b.prev != null)){
    const prevTotal = dist.brackets.reduce((s, b) => s + b.prev, 0);
    if(prevTotal > 0){
      const prevMean = dist.brackets.reduce((s, b) => s + b.prev / prevTotal * (b.lo + b.hi) / 2, 0);
      out.dayChange = out.mean / prevMean - 1;
    }
  }
  return out;
}

/* Plain-language statements of every assumption the numbers depend on. */
export function assumptions(dist, fmt){
  const o = dist.opts, out = [];
  if(dist.openTopMass > 0){
    const top = dist.brackets[dist.brackets.length - 1];
    out.push(`The top bracket (${top.title}) has no ceiling, so it is spread up to ${o.topMultiple} times its floor. ` +
      `${pct(dist.openTopMass)} of the probability sits there. At ${o.topLow} to ${o.topHigh} times instead, ` +
      `the average would be ${fmt(mean(withTop(dist, o.topLow)))} to ${fmt(mean(withTop(dist, o.topHigh)))}.`);
  }
  if(dist.openBottomMass > 0){
    const b = dist.brackets[0];
    out.push(`The bottom bracket (${b.title}) has no floor, so it is spread down to ${o.bottomFraction * 100}% of its ceiling. ` +
      `${pct(dist.openBottomMass)} of the probability sits there.`);
  }
  if(dist.pNone != null && dist.pNone > 0){
    out.push(`The crowd puts ${pct(dist.pNone)} on no listing inside this market's window. ` +
      `That case is left out of the value rather than counted as zero.`);
  }
  if(Math.abs(dist.total - 1) > 0.02){
    out.push(`The bracket prices add up to ${pct(dist.total)}, not 100%, so they were rescaled to sum to one.`);
  }
  if(dist.skipped.length){
    out.push(`${dist.skipped.length} bracket(s) could not be read and were left out: ${dist.skipped.join(", ")}.`);
  }
  return out;
}

const pct = x => `${(x * 100).toFixed(x < 0.1 ? 1 : 0)}%`;

/* ------------------------------------------------------------- timeline */

const MONTHS = ["january","february","march","april","may","june","july","august",
                "september","october","november","december"];

/* "June 30, 2026" to a UTC timestamp at the end of that day. */
export function parseDateTitle(title){
  const g = /^\s*([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})\s*$/.exec(title || "");
  if(!g) return null;
  const m = MONTHS.indexOf(g[1].toLowerCase());
  if(m < 0) return null;
  return Date.UTC(+g[3], m, +g[2], 23, 59, 59);
}

/* Pool adjacent violators: the closest non-decreasing sequence to the input.
   The chance of listing by a later date can never be lower than by an earlier
   one, but separately traded markets can briefly disagree. */
export function isotonic(values, weights){
  const blocks = [];
  values.forEach((v, i) => {
    blocks.push({v, w: weights ? weights[i] : 1, n: 1});
    while(blocks.length > 1 && blocks[blocks.length - 2].v > blocks[blocks.length - 1].v){
      const b = blocks.pop(), a = blocks.pop();
      const w = a.w + b.w;
      blocks.push({v: (a.v * a.w + b.v * b.w) / w, w, n: a.n + b.n});
    }
  });
  return blocks.flatMap(b => Array(b.n).fill(b.v));
}

/* The chance of a listing by each date in an "IPO by ...?" event. A market
   that has closed has resolved, so it counts as 0 or 1, not its last price. */
export function ipoTimeline(event, now = Date.now()){
  const pts = [];
  for(const m of event.markets || []){
    const t = parseDateTitle(m.title);
    if(t == null || m.yes == null) continue;
    const p = m.closed ? (m.yes >= 0.5 ? 1 : 0) : m.yes;
    pts.push({t, raw: p, closed: !!m.closed, title: m.title});
  }
  if(!pts.length) return null;
  pts.sort((a, b) => a.t - b.t);
  const fitted = isotonic(pts.map(p => p.raw));
  pts.forEach((p, i) => { p.p = fitted[i]; });
  const adjusted = pts.some(p => Math.abs(p.p - p.raw) > 0.005);
  const listed = pts.some(p => p.closed && p.raw === 1);
  const future = pts.filter(p => p.t >= now);
  return {slug: event.slug, title: event.title, points: pts, future, adjusted, listed,
          median: medianDate(future)};
}

/* The first date by which the crowd thinks a listing is more likely than not,
   interpolated between the dates the markets ask about. */
export function medianDate(points){
  for(let i = 0; i < points.length; i++){
    if(points[i].p >= 0.5){
      if(i === 0) return {t: points[0].t, bounded: false};
      const a = points[i - 1], b = points[i];
      const f = (0.5 - a.p) / (b.p - a.p || 1);
      return {t: a.t + f * (b.t - a.t), bounded: true};
    }
  }
  return null;
}

/* Chance of a listing by time t, interpolated, or null outside the dates asked about. */
export function probListedBy(timeline, t){
  const pts = timeline.points;
  if(!pts.length || t < pts[0].t || t > pts[pts.length - 1].t) return null;
  for(let i = 0; i < pts.length - 1; i++){
    const a = pts[i], b = pts[i + 1];
    if(a.t <= t && t <= b.t) return a.p + (t - a.t) / (b.t - a.t || 1) * (b.p - a.p);
  }
  return pts[pts.length - 1].p;
}

/* ---------------------------------------------------------- touch ladders */

/* "Will the valuation reach $150B by December 31?" markets. Upward rungs
   price reaching a level, downward rungs price falling to one. A rung priced
   at 1 has already happened, which tells you where the valuation stands. */
export function touchLadder(event){
  const up = [], down = [];
  for(const m of event.markets || []){
    const g = /^\s*([↑↓])\s*\$?([\d.]+)\s*([TB])/.exec(m.title || "");
    if(!g || m.yes == null) continue;
    const level = parseFloat(g[2]) * unitScale(g[3]);
    const rung = {level, p: m.yes, reached: m.yes >= 0.995, dayChange: m.dayChange ?? null, title: m.title};
    (g[1] === "↑" ? up : down).push(rung);
  }
  if(!up.length && !down.length) return null;
  up.sort((a, b) => a.level - b.level);
  down.sort((a, b) => b.level - a.level);
  // Reaching a higher level can never be more likely than reaching a lower one.
  const fittedUp = isotonic(up.map(r => -r.p)).map(v => -v);
  up.forEach((r, i) => { r.p = fittedUp[i]; });
  const reachedUp = up.filter(r => r.reached);
  const floor = reachedUp.length ? reachedUp[reachedUp.length - 1].level : null;
  return {slug: event.slug, title: event.title, up, down, floor,
          next: up.filter(r => !r.reached), deadline: event.endDate || null};
}

/* ------------------------------------------------------------- your stake */

/* What a person's equity would be worth at listing, across the crowd's
   distribution.

   holding = {mode: "percent", percent}                       share of the company
           | {mode: "shares", shares, totalShares, strike}    count, with an optional strike
   dilution: share of the company expected to be issued before the listing.

   Pre-tax, and before liquidation preferences, lockups and any secondary
   discount, which the result says wherever it is shown. */
export function stakeAt(holding, dilution = 0){
  const keep = 1 - Math.min(Math.max(dilution, 0), 0.95);
  if(holding.mode === "percent"){
    const f = (holding.percent / 100) * keep;
    return v => Math.max(0, f * v);
  }
  const shares = holding.shares, total = holding.totalShares / keep, strike = holding.strike || 0;
  return v => Math.max(0, shares * (v / total - strike));
}

export function stakeOutcomes(dist, holding, dilution = 0, target = null){
  const f = stakeAt(holding, dilution);
  const out = {
    p10: f(quantile(dist, 0.10)), median: f(quantile(dist, 0.5)), p90: f(quantile(dist, 0.90)),
    mean: 0, pZero: 0, pTarget: null,
  };
  // Expected value by integrating across each bracket. The payoff can be kinked
  // by a strike, so it is integrated numerically rather than at the midpoint.
  const N = 400;
  for(const b of dist.brackets){
    let s = 0, zero = 0;
    for(let i = 0; i < N; i++){
      const v = b.lo + (i + 0.5) / N * (b.hi - b.lo);
      const x = f(v);
      s += x;
      if(x <= 0) zero++;
    }
    out.mean += b.q * s / N;
    out.pZero += b.q * zero / N;
  }
  if(target != null && target > 0){
    out.pTarget = probAtLeast(dist, valueNeeded(f, dist, target));
  }
  return out;
}

/* Smallest company value at which the stake reaches the target, by bisection.
   The stake rises with the company's value, so this is well defined. */
function valueNeeded(f, dist, target){
  let lo = 0, hi = dist.brackets[dist.brackets.length - 1].hi * 100;
  if(f(hi) < target) return Infinity;
  for(let i = 0; i < 200; i++){
    const mid = (lo + hi) / 2;
    if(f(mid) >= target) hi = mid; else lo = mid;
  }
  return hi;
}
