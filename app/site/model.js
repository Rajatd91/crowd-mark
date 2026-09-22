/* The valuation model, in the browser.

   This is a line for line port of model.py. It exists so the page can compute
   a mark itself instead of replaying one that was computed elsewhere: the
   visitor fetches the prediction markets from their own browser, this file
   turns them into a value, and the result is what gets signed and published.

   The two copies are held together by a test that runs both over the same
   stored snapshot and compares every field. If they ever disagree, that test
   fails rather than the chain quietly recording two different answers.
*/
const TRILLION = 1e12, BILLION = 1e9;

/* Yes price of a Polymarket market. outcomePrices arrives as a JSON string. */
function priceOf(market){
  let raw = market.outcomePrices;
  if(typeof raw === "string") raw = JSON.parse(raw);
  return parseFloat(raw[0]);
}

const RANGE = new RegExp(
  "^\\s*(?:(?<lt><)\\s*\\$?(?<upper>[\\d.]+)(?<upper_unit>[TB])" +
  "|\\$?(?<lo>[\\d.]+)(?<lo_unit>[TB])?\\s*[–-]\\s*\\$?(?<hi>[\\d.]+)(?<hi_unit>[TB])" +
  "|\\$?(?<plus>[\\d.]+)(?<plus_unit>[TB])\\s*\\+)\\s*$", "i");

const scale = unit => ((unit || "T").toUpperCase() === "T") ? TRILLION : BILLION;

/* Sorting must match Python's tuple ordering, or the brackets hash differently. */
const byTuple = (a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2];

export function capBrackets(event, topOpenEndMultiple = 1.25){
  const brackets = [], assumptions = [];
  let pNoIpo = 0;
  for(const m of event.markets){
    const title = (m.groupItemTitle || "").trim();
    const p = priceOf(m);
    if(title.toLowerCase().startsWith("no ipo")){ pNoIpo = p; continue; }
    const g = RANGE.exec(title);
    if(!g){ assumptions.push(`skipped an unreadable bracket: '${title}'`); continue; }
    const d = g.groups;
    if(d.lt){
      brackets.push([0, parseFloat(d.upper) * scale(d.upper_unit), p]);
    } else if(d.hi !== undefined){
      const hi = parseFloat(d.hi) * scale(d.hi_unit);
      const lo = parseFloat(d.lo) * scale(d.lo_unit || d.hi_unit);
      brackets.push([lo, hi, p]);
    } else {
      const lo = parseFloat(d.plus) * scale(d.plus_unit);
      const hi = lo * topOpenEndMultiple;
      brackets.push([lo, hi, p]);
      assumptions.push(
        `the open-ended top bracket (${title}) is valued at ` +
        `$${(hi / TRILLION).toFixed(2)}T, that is ${topOpenEndMultiple.toFixed(2)} times its floor`);
    }
  }
  brackets.sort(byTuple);
  return {brackets, pNoIpo, assumptions};
}

/* Expected listing-day cap, conditional on the listing happening at all. Each
   bracket contributes its midpoint, renormalised over the brackets alone. */
export function expectedCap(brackets){
  const total = brackets.reduce((s, b) => s + b[2], 0);
  if(total <= 0) return [null, 0];
  const ev = brackets.reduce((s, [lo, hi, p]) => s + (lo + hi) / 2 * p, 0) / total;
  return [ev, total];
}

/* Probability sitting in the one bracket whose value had to be assumed. */
export function openTopMass(event){
  const {brackets} = capBrackets(event);
  const [, total] = expectedCap(brackets);
  if(!brackets.length || !total) return 1;
  return brackets[brackets.length - 1][2] / total;
}

export function rescaleOpenTop(brackets, multiple){
  if(!brackets.length) return brackets;
  const rest = brackets.slice(0, -1), [lo, , p] = brackets[brackets.length - 1];
  return [...rest, [lo, lo * multiple, p]];
}

/* Of the markets pricing the same question, take the one that leaves least to
   assumption. Fewer than three brackets is not a distribution, so it is refused. */
export function chooseCapEvent(polymarket, cfg){
  let best = null;
  for(const [role, slug] of Object.entries(cfg.polymarket || {})){
    if(!role.startsWith("cap")) continue;
    let ev = polymarket[slug];
    if(!ev) continue;
    if(Array.isArray(ev)) ev = ev[0];
    const {brackets, pNoIpo, assumptions} = capBrackets(ev);
    if(brackets.length < 3) continue;
    const mass = openTopMass(ev);
    if(best === null || mass < best.mass) best = {slug, brackets, pNoIpo, assumptions, mass};
  }
  return best;
}

export function timingLadder(event){
  const out = [];
  for(const m of event.markets){
    const p = priceOf(m);
    if(p <= 0) continue;                  // a date that passed without the event
    out.push([(m.groupItemTitle || "").trim(), p]);
  }
  return out.sort((a, b) => a[1] - b[1]);
}

/* Touch odds, not a distribution: these price whether a valuation REACHES a
   level by a date. Only the upward rungs ask that question. */
export function valuationLadder(event){
  const rungs = [];
  for(const m of event.markets){
    const title = (m.groupItemTitle || "").trim();
    if(!title.startsWith("↑")) continue;
    const g = /^↑\$?([\d.]+)([TB])/.exec(title);
    if(!g) continue;
    rungs.push([parseFloat(g[1]) * scale(g[2]), priceOf(m)]);
  }
  return rungs.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
}

/* Interpolated between the rungs either side. Outside the ladder it returns
   null, because guessing past the last rung invents a number nobody bet on. */
export function crowdOddsAt(rungs, value){
  if(!rungs.length || value < rungs[0][0] || value > rungs[rungs.length - 1][0]) return null;
  for(let i = 0; i < rungs.length - 1; i++){
    const [x0, p0] = rungs[i], [x1, p1] = rungs[i + 1];
    if(x0 <= value && value <= x1){
      if(x1 === x0) return p0;
      return p0 + (value - x0) / (x1 - x0) * (p1 - p0);
    }
  }
  return null;
}

const pct = (x, digits = 0) => `${(x * 100).toFixed(digits)}%`;

/* One company's mark, from the markets and the token's own figures.

   `fixed` carries what a browser cannot fetch for itself: the issuer's mark
   price and the share count it implies. Those come from the published snapshot
   and are named as such wherever this result is shown. */
export function buildCard(polymarket, symbol, cfg, fixed){
  const shares = fixed.shares;
  const card = {
    symbol, company: cfg.company, kind: cfg.kind,
    token_price: fixed.token_price, mark_price: fixed.mark_price,
    premium_to_mark: fixed.token_price / fixed.mark_price - 1,
    shares, token_implied_value: fixed.token_price * shares,
    crowd_value: null, crowd_per_token: null, p_listing: null, cap_source: null,
    open_top_mass: null, crowd_low: null, crowd_high: null,
    brackets: [], timing: [], ladder: [],
    crowd_odds_at_token_price: null, assumptions: [],
  };

  if(cfg.kind === "ipo"){
    const chosen = chooseCapEvent(polymarket, cfg);
    if(chosen){
      const [cap, mass] = expectedCap(chosen.brackets);
      card.crowd_value = cap;
      card.crowd_per_token = cap ? cap / shares : null;
      card.p_listing = mass;
      card.cap_source = chosen.slug;
      card.open_top_mass = chosen.mass;
      const total = chosen.brackets.reduce((s, b) => s + b[2], 0) || 1;
      card.brackets = chosen.brackets.map(([low, high, p]) => ({low, high, p: p / total}));
      const lo = expectedCap(rescaleOpenTop(chosen.brackets, 1.10))[0];
      const hi = expectedCap(rescaleOpenTop(chosen.brackets, 1.50))[0];
      card.crowd_low = lo; card.crowd_high = hi;
      card.assumptions.push(...chosen.assumptions);
      if(chosen.mass && chosen.mass >= 0.10){
        card.assumptions.push(
          `${pct(chosen.mass)} of the crowd's probability sits in that open-ended top ` +
          `bracket, so the value would be ${(lo / 1e12).toFixed(2)}T to ${(hi / 1e12).toFixed(2)}T ` +
          "if it were worth 1.1 to 1.5 times its floor instead");
      }
      if(chosen.pNoIpo){
        card.assumptions.push(
          `the crowd puts ${pct(chosen.pNoIpo, 1)} on no listing in the market's window, ` +
          "which is excluded from the value above rather than priced");
      }
    }
    let tv = polymarket[cfg.polymarket.timing];
    if(tv) card.timing = timingLadder(Array.isArray(tv) ? tv[0] : tv);
  } else {
    let lv = polymarket[cfg.polymarket.ladder];
    if(lv){
      card.ladder = valuationLadder(Array.isArray(lv) ? lv[0] : lv);
      card.crowd_odds_at_token_price = crowdOddsAt(card.ladder, card.token_implied_value);
      card.assumptions.push(
        "these markets price whether the valuation REACHES a level by 31 December, " +
        "so they are touch odds, not a distribution over a final value");
    }
  }
  return card;
}
