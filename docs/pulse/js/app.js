/* Crowd Mark: what private companies are worth, according to the people
   betting real money on it, and what that means for your own equity. */
import * as C from "./crowd.js";
import {loadEvents, searchEvents, polymarketUrl} from "./markets.js";
import {COMPANIES, allSlugs, slugsFor, byId} from "./companies.js";
import {distributionChart, timelineChart, ladderChart, rangeBar} from "./charts.js";
import {SIGNUP_ENDPOINT, REPO_URL, REQUEST_URL} from "./config.js";

const $ = (s, el = document) => el.querySelector(s);
const view = $("#view");
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));

/* ------------------------------------------------------------ formatting */

export function money(v){
  if(v == null || !isFinite(v)) return "n/a";
  const a = Math.abs(v), s = v < 0 ? "−" : "";
  if(a >= 1e12) return `${s}$${(a / 1e12).toFixed(a >= 1e13 ? 1 : 2)}T`;
  if(a >= 1e9) return `${s}$${+(a / 1e9).toFixed(a >= 1e11 ? 0 : 1)}B`;
  if(a >= 1e6) return `${s}$${+(a / 1e6).toFixed(a >= 1e8 ? 0 : 1)}M`;
  if(a >= 1e4) return `${s}$${Math.round(a / 1e3)}k`;
  return `${s}$${Math.round(a).toLocaleString("en-US")}`;
}
const short = v => v >= 1e12 ? `$${+(v / 1e12).toFixed(2)}T` : `$${+(v / 1e9).toFixed(0)}B`;
const pct = (p, d = 0) => p == null ? "n/a" : `${(p * 100).toFixed(d)}%`;
const date = t => new Date(t).toLocaleDateString("en-GB", {day: "numeric", month: "short", year: "numeric", timeZone: "UTC"});
const monthYear = t => new Date(t).toLocaleDateString("en-GB", {month: "long", year: "numeric", timeZone: "UTC"});
const change = (c, unit = "pct") => c == null ? "" :
  `<span class="chg ${c > 0.0005 ? "up" : c < -0.0005 ? "down" : "flat"}">${c > 0 ? "▲" : c < 0 ? "▼" : "•"} ${unit === "pts" ? `${(Math.abs(c) * 100).toFixed(1)} pts` : pct(Math.abs(c), 1)} today</span>`;

/* ------------------------------------------------------------ the data */

let state = {events: {}, from: {}, source: "none", asOf: null, loadedAt: null};
let loading = null;

async function refresh(){
  if(!loading){
    loading = loadEvents(allSlugs()).then(r => {
      state = {...r, loadedAt: Date.now()};
      loading = null;
      renderStatus();
      return state;
    });
  }
  return loading;
}

function analyse(company, events = state.events, now = Date.now()){
  const out = {company, volume: 0, sources: []};
  for(const slug of slugsFor(company)){
    const ev = events[slug];
    if(!ev) continue;
    out.volume += ev.volume || 0;
    out.sources.push(ev);
  }
  if(company.kind === "ipo"){
    out.dist = C.bestDistribution((company.caps || []).map(s => events[s]));
    if(out.dist) out.summary = C.summarize(out.dist);
    if(company.timing && events[company.timing]) out.timeline = C.ipoTimeline(events[company.timing], now);
  } else if(company.ladder && events[company.ladder]){
    out.ladder = C.touchLadder(events[company.ladder]);
  }
  return out;
}

/* Next date the timeline asks about that is still ahead, and its odds. */
function nextMilestone(timeline){
  if(!timeline || !timeline.future.length) return null;
  const dec = timeline.future.filter(p => new Date(p.t).getUTCMonth() === 11);
  const year = dec.length ? new Date(dec[0].t).getUTCFullYear() : null;
  const endOfYear = dec.filter(p => new Date(p.t).getUTCFullYear() === year).pop();
  return endOfYear || timeline.future[0];
}

function renderStatus(){
  const el = $("#status");
  if(!el) return;
  const s = state.source;
  if(s === "live") el.innerHTML = `<span class="dot live"></span>Live from Polymarket · ${new Date(state.loadedAt).toLocaleTimeString("en-GB", {hour: "2-digit", minute: "2-digit"})}`;
  else if(s === "snapshot" || s === "mixed") el.innerHTML = `<span class="dot stale"></span>Live prices unavailable · showing snapshot from ${state.asOf ? date(Date.parse(state.asOf)) : "an earlier fetch"}`;
  else el.innerHTML = `<span class="dot"></span>Loading prices…`;
}

/* ------------------------------------------------------------ home */

function companyCard(a){
  const c = a.company;
  if(c.kind === "ipo" && a.summary){
    const s = a.summary, m = nextMilestone(a.timeline);
    return `<a class="card co" href="#/c/${c.id}">
      <div class="co-head"><div><h3>${esc(c.name)}</h3><p class="muted">${esc(c.sector)}</p></div><span class="badge ipo">IPO</span></div>
      <p class="kicker">Expected listing value</p>
      <p class="big">${money(s.mean)}</p>
      ${rangeBar(s.p10, s.median, s.p90, s.p10 * 0.7, s.p90 * 1.15)}
      <p class="small muted">80% range ${money(s.p10)} – ${money(s.p90)}</p>
      <div class="co-foot">
        ${a.timeline && a.timeline.median ? `<span>Most likely listing <b>${monthYear(a.timeline.median.t)}</b></span>` : m ? `<span><b>${pct(m.p)}</b> chance of listing by ${date(m.t)}</span>` : `<span class="muted">No listing date priced</span>`}
        ${change(s.dayChange)}
      </div></a>`;
  }
  if(c.kind === "round" && a.ladder){
    const l = a.ladder, next = l.next.slice(0, 2);
    return `<a class="card co" href="#/c/${c.id}">
      <div class="co-head"><div><h3>${esc(c.name)}</h3><p class="muted">${esc(c.sector)}</p></div><span class="badge round">Private round</span></div>
      <p class="kicker">Valuation already reached</p>
      <p class="big">${l.floor ? `${money(l.floor)}+` : "n/a"}</p>
      <ul class="rungs">${next.map(r => `<li><span>${money(r.level)}</span><span class="bar"><i style="width:${r.p * 100}%"></i></span><b>${pct(r.p)}</b></li>`).join("")}</ul>
      <div class="co-foot"><span class="muted">Chance of reaching each level by the market's deadline</span></div></a>`;
  }
  return `<a class="card co" href="#/c/${c.id}"><div class="co-head"><h3>${esc(c.name)}</h3></div><p class="muted">No prices available right now.</p></a>`;
}

function heroVisual(a){
  if(!a || !a.dist) return "";
  return `<div class="hero-card card">
    <div class="hc-top"><span class="badge ipo">${state.source === "live" ? "Live example" : "Example"}</span><span class="muted small">${esc(a.company.name)} · listing value</span></div>
    <p class="big">${money(a.summary.mean)}</p>
    <p class="small muted">expected, from ${money(a.volume)} of bets</p>
    ${distributionChart(a.dist, a.summary.median, short)}
  </div>`;
}

async function home(){
  view.innerHTML = `
  <section class="hero">
    <div class="hero-copy">
      <p class="eyebrow">Private market valuations, priced by the crowd</p>
      <h1>What is a private company <em>really</em> worth?</h1>
      <p class="lede">Ask the people betting real money on it. Crowd Mark turns live prediction-market odds into a valuation range and an IPO timeline for the world's biggest private companies, then tells you what that means for <b>your</b> shares.</p>
      <form class="search" id="hero-search" role="search">
        <input name="q" type="search" placeholder="Search any company, e.g. Stripe, Databricks, SpaceX" aria-label="Search a company" autocomplete="off">
        <button class="btn primary">Search</button>
      </form>
      <p class="small muted">Free and open source. Every number shows its working.</p>
    </div>
    <div class="hero-visual" id="hero-visual"><div class="card skeleton" style="height:340px"></div></div>
  </section>

  <section class="section">
    <div class="section-head"><h2>Today's board</h2><p class="muted">Updated whenever a bet moves. Tap a company for the full picture.</p></div>
    <div class="grid cards" id="board">${COMPANIES.map(() => `<div class="card skeleton" style="height:250px"></div>`).join("")}</div>
  </section>

  <section class="section split">
    <div>
      <p class="eyebrow">For employees and early investors</p>
      <h2>Know what your equity could be worth</h2>
      <p>Enter your share count, options or ownership percentage. Crowd Mark runs it through the crowd's full range of outcomes, not a single headline number, and shows the likely value at listing, the range, and the chance it clears the figure you have in mind.</p>
      <a class="btn primary" href="#/equity">Value my equity</a>
    </div>
    <div class="card steps">
      <div><span class="num">1</span><p><b>Read the bets.</b> Brackets like “$1.75T to $2T at listing” trade at prices that are probabilities.</p></div>
      <div><span class="num">2</span><p><b>Build the range.</b> Those prices become a full distribution: average, median and an 80% range.</p></div>
      <div><span class="num">3</span><p><b>Apply it to you.</b> Your stake, any strike price and dilution, run through every outcome.</p></div>
    </div>
  </section>

  ${signupSection()}
  `;
  bindSearch($("#hero-search"));
  bindSignup();
  await refresh();
  const analyses = COMPANIES.map(c => analyse(c));
  $("#board").innerHTML = analyses.map(companyCard).join("");
  $("#hero-visual").innerHTML = heroVisual(analyses.find(a => a.dist)) || "";
}

/* ------------------------------------------------------------ company */

function marketsTable(sources){
  return `<table class="markets"><thead><tr><th>Market</th><th class="r">Bet so far</th><th></th></tr></thead><tbody>
    ${sources.map(e => `<tr><td>${esc(e.title)}</td><td class="r">${money(e.volume)}</td>
      <td class="r"><a href="${polymarketUrl(e.slug)}" target="_blank" rel="noopener">View ↗</a></td></tr>`).join("")}
  </tbody></table>`;
}

function ipoSection(a){
  const s = a.summary, t = a.timeline, m = nextMilestone(t);
  const notes = a.dist ? C.assumptions(a.dist, money) : [];
  if(t && t.adjusted) notes.push("A few dates were priced slightly out of order, so the timeline was smoothed to never go down over time.");
  return `
  <div class="kpis">
    <div class="kpi"><p class="kicker">Expected listing value</p><p class="big">${money(s.mean)}</p>${change(s.dayChange)}</div>
    <div class="kpi"><p class="kicker">Median</p><p class="big">${money(s.median)}</p><p class="small muted">half the odds above, half below</p></div>
    <div class="kpi"><p class="kicker">80% range</p><p class="big">${money(s.p10)} – ${money(s.p90)}</p><p class="small muted">1 in 10 below, 1 in 10 above</p></div>
    <div class="kpi"><p class="kicker">Most likely listing</p><p class="big">${t && t.median ? (t.median.bounded ? monthYear(t.median.t) : `by ${monthYear(t.median.t)}`) : t ? "After " + monthYear(t.points[t.points.length - 1].t) : "n/a"}</p>
      <p class="small muted">${m ? `${pct(m.p)} chance by ${date(m.t)}` : "date when odds pass 50%"}</p></div>
  </div>
  <div class="grid two">
    <div class="card"><h3>Where the crowd puts the listing value</h3><p class="small muted">Probability of each range, from the market “${esc(a.dist.title)}”</p>${distributionChart(a.dist, s.median, short)}</div>
    ${t ? `<div class="card"><h3>When will it list?</h3><p class="small muted">Chance of an IPO by each date. The dot on the dashed line is when it becomes more likely than not.</p>${timelineChart(t, Date.now())}</div>` : ""}
  </div>
  <div class="card" id="equity">${equityPanel(a)}</div>
  <div class="grid two">
    <div class="card"><h3>What this rests on</h3><ul class="notes">${notes.map(n => `<li>${esc(n)}</li>`).join("") || "<li>No assumptions beyond the bracket prices themselves.</li>"}</ul></div>
    <div class="card"><h3>The markets behind it</h3>${marketsTable(a.sources)}</div>
  </div>`;
}

function roundSection(a){
  const l = a.ladder;
  return `
  <div class="kpis">
    <div class="kpi"><p class="kicker">Valuation already reached</p><p class="big">${l.floor ? money(l.floor) + "+" : "n/a"}</p><p class="small muted">levels the market has already settled as hit</p></div>
    ${l.next.slice(0, 3).map(r => `<div class="kpi"><p class="kicker">Chance of ${money(r.level)}</p><p class="big">${pct(r.p)}</p>${r.dayChange != null ? change(r.dayChange, "pts") : ""}</div>`).join("")}
  </div>
  <div class="grid two">
    <div class="card"><h3>How high will the next valuation go?</h3><p class="small muted">Chance the company is valued at each level or more by the market's deadline${l.deadline ? ` (${date(Date.parse(l.deadline))})` : ""}.</p>${ladderChart(l, short)}</div>
    <div class="card" id="equity">${equityPanel(a)}</div>
  </div>
  <div class="grid two">
    <div class="card"><h3>What this rests on</h3><ul class="notes">
      <li>These markets ask whether the valuation <b>reaches</b> a level by a date. They are odds of reaching, not a forecast of one final number, so no single “expected value” is computed.</li>
      <li>Higher levels are never shown as likelier than lower ones; where separate markets disagreed, the odds were smoothed.</li>
      <li>“Already reached” means the market has settled that level as hit, usually because a funding round was announced at or above it.</li></ul></div>
    <div class="card"><h3>The markets behind it</h3>${marketsTable(a.sources)}</div>
  </div>`;
}

async function company(id){
  const c = byId(id);
  if(!c) return notFound();
  view.innerHTML = `<section class="page-head"><a class="back" href="#/">← All companies</a>
    <div class="ph-row"><div><h1>${esc(c.name)}</h1><p class="muted">${esc(c.sector)} · ${c.kind === "ipo" ? "IPO markets" : "Private funding round markets"}</p></div></div></section>
    <div id="body"><div class="card skeleton" style="height:420px"></div></div>`;
  await refresh();
  const a = analyse(c);
  const body = $("#body");
  if(c.kind === "ipo" && a.dist) body.innerHTML = ipoSection(a);
  else if(c.kind === "round" && a.ladder) body.innerHTML = roundSection(a);
  else { body.innerHTML = `<div class="card"><p>No prices for ${esc(c.name)} could be loaded right now. Try again in a minute.</p></div>`; return; }
  bindEquity(a);
}

/* ------------------------------------------------------------ your equity */

function equityPanel(a){
  const name = esc(a.company?.name || "this company");
  return `<div class="equity">
    <div class="eq-head"><h3>What is my equity in ${name} worth?</h3>
      <p class="small muted">Runs your stake through every outcome the crowd prices. Nothing you type leaves this page.</p></div>
    <form class="eq-form" autocomplete="off">
      <div class="seg" role="radiogroup">
        <label><input type="radio" name="mode" value="percent" checked> I know my ownership %</label>
        <label><input type="radio" name="mode" value="shares"> I know my shares or options</label>
      </div>
      <div class="fields">
        <label class="f mode-percent">Ownership of the company (%)<input name="percent" type="number" step="any" min="0" value="0.0005"></label>
        <label class="f mode-shares" hidden>Shares or options you hold<input name="shares" type="number" step="any" min="0" value="10000"></label>
        <label class="f mode-shares" hidden>Company's fully diluted shares<input name="total" type="number" step="any" min="1" placeholder="e.g. 3000000000"></label>
        <label class="f mode-shares" hidden>Strike price per share ($, 0 for shares/RSUs)<input name="strike" type="number" step="any" min="0" value="0"></label>
        <label class="f">Dilution before listing (%)<input name="dilution" type="number" step="any" min="0" max="90" value="0"></label>
        ${a.dist ? `<label class="f">A figure you have in mind ($, optional)<input name="target" type="number" step="any" min="0" placeholder="e.g. 1000000"></label>` : ""}
      </div>
    </form>
    <div class="eq-out" aria-live="polite"></div>
    <p class="fine">Estimates only, not advice. Before tax, liquidation preferences, lockups and any discount on a private sale. Your equity portal (Carta, Shareworks, Pulley) or offer letter shows your ownership or the fully diluted share count.</p>
  </div>`;
}

function bindEquity(a){
  const form = $(".eq-form"), out = $(".eq-out");
  if(!form) return;
  const update = () => {
    const f = new FormData(form), mode = f.get("mode");
    form.querySelectorAll(".mode-percent").forEach(el => el.hidden = mode !== "percent");
    form.querySelectorAll(".mode-shares").forEach(el => el.hidden = mode !== "shares");
    const dilution = (+f.get("dilution") || 0) / 100;
    let holding;
    if(mode === "percent"){
      const p = +f.get("percent");
      if(!(p > 0)) return out.innerHTML = `<p class="muted">Enter your ownership to see a result.</p>`;
      holding = {mode, percent: p};
    } else {
      const shares = +f.get("shares"), total = +f.get("total"), strike = +f.get("strike") || 0;
      if(!(shares > 0) || !(total > 0)) return out.innerHTML = `<p class="muted">Enter your shares and the company's fully diluted share count.</p>`;
      if(shares > total) return out.innerHTML = `<p class="warn">You can't hold more shares than the company has in total.</p>`;
      holding = {mode, shares, totalShares: total, strike};
    }
    out.innerHTML = a.dist ? stakeFromDist(a, holding, dilution, +f.get("target") || null)
                           : stakeFromLadder(a, holding, dilution);
  };
  form.addEventListener("input", update);
  update();
}

function stakeFromDist(a, holding, dilution, target){
  const r = C.stakeOutcomes(a.dist, holding, dilution, target);
  const m = nextMilestone(a.timeline);
  return `<div class="eq-result">
    <div class="eq-main"><p class="kicker">Likely value at listing</p><p class="huge">${money(r.median)}</p>
      <p class="small muted">median outcome · average ${money(r.mean)}</p></div>
    <div class="eq-side">
      <div><p class="kicker">80% range</p><p class="mid">${money(r.p10)} – ${money(r.p90)}</p></div>
      ${target ? `<div><p class="kicker">Chance of at least ${money(target)}</p><p class="mid">${pct(r.pTarget)}</p></div>` : ""}
      ${holding.strike > 0 ? `<div><p class="kicker">Chance options end up under water</p><p class="mid">${pct(r.pZero)}</p></div>` : ""}
      ${m ? `<div><p class="kicker">Chance it lists by ${date(m.t)}</p><p class="mid">${pct(m.p)}</p></div>` : ""}
    </div></div>`;
}

function stakeFromLadder(a, holding, dilution){
  const f = C.stakeAt(holding, dilution), l = a.ladder;
  const rows = [...(l.floor ? [{level: l.floor, p: 1, reached: true}] : []), ...l.next];
  return `<table class="markets eq-table"><thead><tr><th>If the company is valued at</th><th class="r">Your stake</th><th class="r">Chance of reaching it</th></tr></thead><tbody>
    ${rows.map(r => `<tr><td>${money(r.level)}</td><td class="r"><b>${money(f(r.level))}</b></td><td class="r">${r.reached ? "already reached" : pct(r.p)}</td></tr>`).join("")}
  </tbody></table>`;
}

async function equityPage(){
  const options = COMPANIES.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join("");
  view.innerHTML = `<section class="page-head"><a class="back" href="#/">← Home</a>
    <h1>Value my equity</h1><p class="lede">Pick your company and enter your stake. The answer is a range, because the crowd's view is a range.</p>
    <label class="pick">Company <select id="pick">${options}</select></label></section>
    <div class="card" id="eq-card"><div class="skeleton" style="height:300px"></div></div>`;
  await refresh();
  const draw = () => {
    const a = analyse(byId($("#pick").value));
    $("#eq-card").innerHTML = (a.dist || a.ladder) ? equityPanel(a) : `<p>No prices for this company right now.</p>`;
    bindEquity(a);
  };
  $("#pick").addEventListener("change", draw);
  draw();
}

/* ------------------------------------------------------------ search */

function bindSearch(form){
  form?.addEventListener("submit", e => {
    e.preventDefault();
    const q = new FormData(form).get("q").trim();
    if(q) location.hash = `#/search/${encodeURIComponent(q)}`;
  });
}

function classify(ev){
  if(C.capDistribution(ev)) return {kind: "Listing value", rank: 3};
  if(C.touchLadder(ev)) return {kind: "Valuation levels", rank: 2};
  if(C.ipoTimeline(ev)) return {kind: "IPO timing", rank: 2};
  return {kind: "Other odds", rank: 0};
}

async function search(q){
  view.innerHTML = `<section class="page-head"><a class="back" href="#/">← Home</a><h1>Markets for “${esc(q)}”</h1>
    <form class="search" id="s-again" role="search"><input name="q" type="search" value="${esc(q)}" aria-label="Search"><button class="btn primary">Search</button></form></section>
    <div id="results"><div class="card skeleton" style="height:200px"></div></div>`;
  bindSearch($("#s-again"));
  let found;
  try{ found = await searchEvents(q); }
  catch(e){ $("#results").innerHTML = `<div class="card"><p>Search needs a live connection to Polymarket, which could not be reached. Try again shortly.</p></div>`; return; }
  const known = COMPANIES.find(c => c.name.toLowerCase() === q.toLowerCase());
  const items = found.map(ev => ({ev, ...classify(ev)})).sort((a, b) => b.rank - a.rank);
  $("#results").innerHTML = `
    ${known ? `<div class="card note">We already cover ${esc(known.name)}. <a href="#/c/${known.id}">See the full analysis →</a></div>` : ""}
    ${items.length ? `<div class="grid cards">${items.map(({ev, kind, rank}) => `
      <div class="card result"><span class="badge ${rank ? "ipo" : ""}">${kind}</span><h3>${esc(ev.title)}</h3>
        <p class="small muted">${money(ev.volume)} bet · ${ev.markets.length} outcomes</p>
        ${rank ? `<a class="btn" href="#/e/${encodeURIComponent(ev.slug)}">Analyse →</a>` : `<a class="btn ghost" href="${polymarketUrl(ev.slug)}" target="_blank" rel="noopener">See odds on Polymarket ↗</a>`}
      </div>`).join("")}</div>`
      : `<div class="card"><p>No open markets mention “${esc(q)}” yet.</p></div>`}
    <p class="muted small">Missing a company? <a href="${REQUEST_URL}${encodeURIComponent(q)}" target="_blank" rel="noopener">Ask for it to be covered</a>.</p>`;
}

/* One market, analysed on the spot, for companies found through search. */
async function eventPage(slug){
  view.innerHTML = `<section class="page-head"><a class="back" href="javascript:history.back()">← Back</a><div id="ev-head"></div></section><div id="body"><div class="card skeleton" style="height:360px"></div></div>`;
  let ev;
  try{ ({events: {[slug]: ev}} = await loadEvents([slug])); }catch(e){}
  if(!ev) return void ($("#body").innerHTML = `<div class="card"><p>This market could not be loaded.</p></div>`);
  $("#ev-head").innerHTML = `<h1>${esc(ev.title)}</h1><p class="muted">${money(ev.volume)} bet · <a href="${polymarketUrl(slug)}" target="_blank" rel="noopener">View on Polymarket ↗</a></p>`;
  const a = {company: {name: ev.title.replace(/\?.*$/, "")}, sources: [ev], volume: ev.volume || 0};
  const dist = C.capDistribution(ev), timeline = C.ipoTimeline(ev), ladder = C.touchLadder(ev);
  if(dist){ a.dist = dist; a.summary = C.summarize(dist); $("#body").innerHTML = ipoSection(a); bindEquity(a); }
  else if(ladder){ a.ladder = ladder; $("#body").innerHTML = roundSection(a); bindEquity(a); }
  else if(timeline){
    const m = timeline.median;
    $("#body").innerHTML = `<div class="kpis"><div class="kpi"><p class="kicker">More likely than not by</p><p class="big">${m ? monthYear(m.t) : "not yet"}</p></div></div>
      <div class="card"><h3>Chance of it happening by each date</h3>${timelineChart(timeline, Date.now())}</div>`;
  } else $("#body").innerHTML = `<div class="card"><p>This market doesn't price a valuation or a date, so there is nothing to compute from it.</p></div>`;
}

/* ------------------------------------------------------------ method */

function method(){
  view.innerHTML = `<section class="page-head narrow"><a class="back" href="#/">← Home</a><h1>How it works, and what it doesn't claim</h1></section>
  <article class="prose narrow">
    <h2>Where the numbers come from</h2>
    <p>Prediction markets let people bet on questions like “What will OpenAI be worth on its first day of trading?”. Each answer, such as “$1.75T to $2T”, trades at a price between 0 and 1, and that price is the crowd's probability for it. Because people lose money when they are wrong, these prices tend to absorb information quickly.</p>
    <p>Crowd Mark reads those prices live from <a href="https://polymarket.com" target="_blank" rel="noopener">Polymarket</a> in your browser. Nothing passes through a server of ours, and nothing is stored or edited.</p>
    <h2>Three kinds of question, treated differently</h2>
    <ul>
      <li><b>Listing value.</b> A set of value ranges that together form a distribution. From it come the average, the median and the 80% range, treating value as spread evenly within each range.</li>
      <li><b>IPO timing.</b> “IPO by June 30?”, “IPO by December 31?” and so on. Read in date order they give the chance of a listing by each date. Settled markets count as 0 or 1, and the curve is never allowed to fall over time.</li>
      <li><b>Valuation levels.</b> “Will the valuation reach $150B by December 31?”. These are odds of <i>reaching</i> a level, not a forecast of one number, so they are shown as a ladder and never averaged.</li>
    </ul>
    <h2>Assumptions, stated rather than hidden</h2>
    <ul>
      <li>An open-ended top range such as “$2.5T+” is spread up to 1.25 times its floor, and every page shows how much the answer moves at 1.1 and 1.5 times.</li>
      <li>An open-ended bottom range such as “under $1T” is spread down to half its ceiling.</li>
      <li>The chance of no listing is reported separately, never counted as a value of zero.</li>
      <li>When several markets price the same listing, the one that leaves least probability in open-ended ranges is used.</li>
    </ul>
    <h2>What Crowd Mark is not</h2>
    <ul>
      <li><b>Not advice.</b> It is a way of reading public odds. It does not tell you to buy, sell or hold anything.</li>
      <li><b>Not a price you can sell at.</b> A listing value is not what a private share sells for today, and it says nothing about tender offers.</li>
      <li><b>Not the whole picture for your equity.</b> Liquidation preferences, tax, vesting, lockups and private-sale discounts all change what you actually receive.</li>
      <li><b>Only as good as the market.</b> Thin markets with little money behind them can be wrong or moved by a few large bets. Every page shows how much has been bet.</li>
    </ul>
    <h2>Open source</h2>
    <p>The full code, including the tests for every calculation, is on <a href="${REPO_URL}" target="_blank" rel="noopener">GitHub</a>.</p>
  </article>`;
}

/* ------------------------------------------------------------ alerts */

function signupSection(){
  const live = !!SIGNUP_ENDPOINT;
  return `<section class="section signup card">
    <div><h2>Get told when the crowd changes its mind</h2>
      <p class="muted">A short weekly email: which valuations moved, by how much, and why it might matter. Plus an instant alert when a company you follow jumps.</p></div>
    ${live ? `<form id="signup" class="signup-form"><input name="email" type="email" required placeholder="you@example.com" aria-label="Email"><button class="btn primary">Get alerts</button><p class="small muted" id="signup-msg"></p></form>`
           : `<div class="signup-form"><p class="small"><b>Alerts are launching soon.</b> Follow the project to hear first.</p><a class="btn" href="${REPO_URL}" target="_blank" rel="noopener">Follow on GitHub</a></div>`}
  </section>`;
}

function bindSignup(){
  const form = $("#signup");
  if(!form) return;
  form.addEventListener("submit", async e => {
    e.preventDefault();
    const msg = $("#signup-msg");
    try{
      const r = await fetch(SIGNUP_ENDPOINT, {method: "POST", body: new FormData(form), headers: {Accept: "application/json"}});
      msg.textContent = r.ok ? "You're on the list. Thank you." : "That didn't go through. Please try again.";
      if(r.ok) form.reset();
    }catch(err){ msg.textContent = "That didn't go through. Please try again."; }
  });
}

/* ------------------------------------------------------------ routing */

function notFound(){ view.innerHTML = `<section class="page-head"><h1>Not found</h1><p><a href="#/">Back to the board</a></p></section>`; }

async function route(scroll = true){
  const h = location.hash.replace(/^#/, "") || "/";
  const [, page, arg] = h.split("/");
  if(scroll) window.scrollTo(0, 0);
  document.querySelectorAll(".nav a").forEach(a => a.classList.toggle("active", a.getAttribute("href") === `#/${page || ""}`));
  if(!page) return home();
  if(page === "c") return company(arg);
  if(page === "equity") return equityPage();
  if(page === "search") return search(decodeURIComponent(arg || ""));
  if(page === "e") return eventPage(decodeURIComponent(arg || ""));
  if(page === "method") return method();
  return notFound();
}

window.addEventListener("hashchange", () => route());
bindSearch($("#nav-search"));
renderStatus();
route();

/* Keep the numbers live while the tab is open. */
setInterval(() => {
  if(document.visibilityState !== "visible") return;
  const page = (location.hash.split("/")[1] || "");
  if(page === "" || page === "c"){ loading = null; refresh().then(() => { if(!document.activeElement?.closest?.("form")) route(false); }); }
}, 60_000);
