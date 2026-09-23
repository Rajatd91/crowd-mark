/* Crowd Mark terminal.

   Four screens, because the question only has four parts. What are people
   betting right now, what does that make the company worth, what would it cost
   you to act on it, and can you check any of it.

   Nothing on the live screen is precomputed. The order books, the fills and
   the prices arrive from Polymarket in this browser, and the company's implied
   valuation is rebuilt from them on every tick, by the same model the keeper
   runs. So the number at the top of the screen is not a claim, it is the
   arithmetic happening in front of you.
*/
import * as M from "./model.js";
import * as P from "./poly.js";
import {headlines} from "./news.js";
import {PROGRAM_ID as PROGRAM} from "./commit.js";
import {watchPrices} from "./prices.js";

const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];

/* ------------------------------------------------------------------- state */
const S = {
  desk: null,        // the shipped snapshot: tokens, costs, issuer powers
  lp: null,          // the liquidity study
  news: null,        // headlines shipped with the page
  chain: null,       // marks read back from Solana
  sym: "ANTHROPIC",
  view: "buy",
  ev: null,          // the Polymarket event for the selected company
  pick: 0,           // which bracket is showing its book
  book: null,
  trades: [],
  history: null,     // the company's implied valuation over the past week
  wallet: null,
  live: null,        // this browser's own reading, once taken
  ticks: 0,          // updates seen since the page opened
  state: "starting",
  amount: "100",     // what the visitor is thinking of spending
  slippage: null,    // what this token's transfer fee forces it to be
  quote: null,       // a real Jupiter quote for that amount
  pricedAt: null,    // when this browser last got a token price of its own
  snapshotAge: null, // how old the shipped figures are
};
const tape = new P.Tape();

/* --------------------------------------------------------------- formatting */
const F = {
  big(x){
    if(x == null || !isFinite(x)) return "—";
    const a = Math.abs(x);
    if(a >= 1e12) return "$" + (x/1e12).toFixed(2) + "T";
    if(a >= 1e9) return "$" + (x/1e9).toFixed(1) + "B";
    if(a >= 1e6) return "$" + (x/1e6).toFixed(1) + "M";
    if(a >= 1e3) return "$" + (x/1e3).toFixed(1) + "k";
    return "$" + x.toFixed(0);
  },
  usd(x, d = 2){ return x == null || !isFinite(x) ? "—" :
    "$" + x.toLocaleString(undefined, {minimumFractionDigits:d, maximumFractionDigits:d}); },
  pct(x, sign = true, d = 1){ return x == null || !isFinite(x) ? "—" :
    (sign && x > 0 ? "+" : "") + (x*100).toFixed(d) + "%"; },
  odds(x){ return x == null ? "—" : (x*100).toFixed(1) + "%"; },
  cents(x){ return x == null ? "—" : (x*100).toFixed(1) + "¢"; },
  num(x, d = 0){ return x == null || !isFinite(x) ? "—" :
    x.toLocaleString(undefined, {maximumFractionDigits:d}); },
  short(a){ return a ? a.slice(0,4) + "…" + a.slice(-4) : "—"; },
  clock(ms){ return new Date(ms).toISOString().slice(11,19); },
  ago(ms){
    const s = (Date.now() - ms)/1000;
    if(s < 90) return Math.max(0, Math.round(s)) + "s ago";
    if(s < 5400) return Math.round(s/60) + "m ago";
    if(s < 172800) return Math.round(s/3600) + "h ago";
    return Math.round(s/86400) + "d ago";
  },
};
const cls = x => x == null ? "" : x > 0 ? "up" : x < 0 ? "down" : "";
const esc = s => String(s ?? "").replace(/[&<>"]/g, c =>
  ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

function toast(msg){
  const t = $("#toast");
  t.textContent = msg; t.classList.add("on");
  clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("on"), 2800);
}

/* ------------------------------------------------------------ the live model

   The crowd's valuation, recomputed from whatever the brackets are quoting at
   this instant. The model is the same one the keeper publishes from, so the
   number moving on screen is the number that would be signed.
*/
function liveCard(){
  if(!S.ev) return null;
  const t = S.desk.tokens[S.sym];
  if(!t?.covered) return null;

  /* The model chooses between the several markets a company can have. Only one
     is open in this browser, so it is offered under whichever role it fills
     and the others are left out, rather than fed a stale copy. */
  const roles = Object.fromEntries(
    Object.entries(t.sources || {}).filter(([, slug]) => slug === S.ev.slug));
  if(!Object.keys(roles).length) return null;

  return M.buildCard({[S.ev.slug]: S.ev}, S.sym,
    {company: t.company, kind: t.kind, polymarket: roles},
    {token_price: t.token_price, mark_price: t.mark_price, shares: t.shares});
}

/* Push a live price into the event, in the shape the model already reads. */
function setPrice(market, price){
  if(!(price > 0) || !(price < 1)) return false;
  const before = market.yes;
  market.yes = price;
  market.outcomePrices = [String(price), String(1 - price)];
  return before !== price;
}

/* ------------------------------------------------------------------ loading */
async function openCompany(sym){
  S.sym = sym; S.pick = 0; S.ev = null; S.book = null; S.trades = []; S.history = null;
  render();

  const t = S.desk.tokens[sym];
  if(!t?.covered){ setState("no market"); loadOther(t.company); return; }

  /* The company's own market: the one the model chose when the page was built,
     falling back to whatever it lists. */
  const slug = t.cap_source || Object.values(t.sources || {})[0];
  if(!slug){ setState("no market"); return; }

  try{
    setState("loading");
    S.ev = await P.loadEvent(slug);
    render();
    const ids = S.ev.markets.map(m => m.yesId).filter(Boolean);
    tape.watch(ids);
    loadBracket(0);
    loadNews(sym);
    valuationHistory().then(h => { S.history = h; if(S.view === "why") paintHistory(); });
  }catch(e){
    setState("market unavailable");
    toast("Polymarket did not answer. " + e.message);
  }
}

async function loadBracket(i){
  S.pick = i;
  const m = S.ev?.markets[i];
  if(!m?.yesId) return;
  render();
  try{
    const [book, trades] = await Promise.all([
      P.loadBook(m.yesId),
      P.loadTrades(m.conditionId, 40).catch(() => []),
    ]);
    S.book = book; S.trades = trades;
    if(S.view === "why"){ paintBook(); paintTrades(); }
  }catch(e){ /* the ladder simply stays as it was */ }
}

/* The company's implied valuation over the past week.

   Each bracket's own price history is fetched, the prices are carried forward
   so every bracket has a value at every instant, and the model is run at each
   one. The result is not a price anybody quoted: it is what the crowd's whole
   distribution implied, hour by hour.
*/
async function valuationHistory(){
  const ev = S.ev, t = S.desk.tokens[S.sym];
  if(!ev || !t?.shares) return null;
  const live = ev.markets.filter(m => m.yesId);
  let series;
  try{
    series = await Promise.all(live.map(m =>
      P.loadHistory(m.yesId, "1w", 60).catch(() => [])));
  }catch(e){ return null; }
  if(!series.some(s => s.length > 2)) return null;

  const stamps = [...new Set(series.flat().map(p => p.t))].sort((a, b) => a - b);
  const at = series.map(() => 0), last = series.map(() => null);
  const shim = {markets: live.map(m => ({...m}))};
  const out = [];
  for(const ts of stamps){
    series.forEach((s, i) => {
      while(at[i] < s.length && s[at[i]].t <= ts){ last[i] = s[at[i]].p; at[i]++; }
    });
    if(last.some(v => v == null)) continue;
    shim.markets.forEach((m, i) => { m.outcomePrices = [String(last[i]), String(1 - last[i])]; });
    const {brackets} = M.capBrackets(shim);
    const [cap] = M.expectedCap(brackets);
    if(cap) out.push({t: ts, cap, per: cap / t.shares});
  }
  return out.length > 3 ? out : null;
}

async function loadNews(sym){
  const shipped = S.news?.by_symbol?.[sym] || [];
  /* The news index turns away a second query within a few seconds. When that
     happened while the snapshot was built, there is no headline to show, and
     saying "no news about this company" would be a claim we never checked. */
  const wasRefused = (S.news?.refused || []).includes(sym);
  paintNews(shipped, S.news?.read_at ?? null, false, wasRefused);
  try{
    /* Merged, not replaced. The live query is one narrow ask and can come back
       with less than the snapshot already holds, and dropping headlines the
       reader could see a second ago is worse than showing nothing new. */
    const fresh = await headlines(sym, 10);
    if(!fresh.length) return;
    const seen = new Set(fresh.map(a => a.title.slice(0, 60).toLowerCase()));
    const merged = fresh.concat(shipped.filter(a =>
      !seen.has((a.title || "").slice(0, 60).toLowerCase())));
    merged.sort((a, b) => asMs(b.at) - asMs(a.at));
    paintNews(merged.slice(0, 12), Date.now(), true);
  }catch(e){ /* the shipped ones stay */ }
}

/* The rail carries a gap per company, so a new price changes it. */
function repaintRail(){
  $$("#rail button").forEach(b => {
    const t = S.desk.tokens[b.dataset.sym];
    const tick = b.querySelector(".tick");
    if(t && tick){ tick.textContent = railTick(t); tick.className = "tick " + railClass(t); }
  });
}

/* Say plainly how old each part of the screen is. A terminal that shows a
   figure without its age is asking to be trusted, which is the thing this one
   is meant not to do. */
function paintAges(){
  const el = $("#ages");
  if(!el) return;
  const snap = S.desk?.read_at ? Date.parse(S.desk.read_at) : null;
  const hrs = snap ? (Date.now() - snap)/3600000 : null;
  el.innerHTML =
    `<span class="${S.pricedAt ? "up" : "warn"}">prices ${
      S.pricedAt ? F.ago(S.pricedAt) : "from the snapshot"}</span>` +
    ` · <span class="${hrs > 12 ? "warn" : ""}">costs and issuer data ${
      snap ? F.ago(snap) : "unknown"}</span>`;
}

function setState(s){
  S.state = s;
  const led = $("#led"), txt = $("#stateTxt");
  if(!led) return;
  led.className = "led" + (s === "live" ? "" : s === "reconnecting" || s === "loading" ? " wait" : " off");
  txt.textContent = s === "live" ? "streaming" : s;
}

/* ================================================================= rendering */
/* What the rail says beside each company. A company whose market is a ladder
   has no gap to quote but is not without a market, and saying so would be
   wrong. */
function railTick(t){
  if(t.gap != null) return F.pct(t.gap, true, 0);
  if(t.covered && t.crowd_odds_at_token_price != null)
    return F.odds(t.crowd_odds_at_token_price) + " odds";
  if(t.covered) return "market open";
  return "no market";
}
function railClass(t){
  if(t.gap != null) return cls(t.gap);
  return t.covered ? "mid" : "dim";
}

function shell(){
  const tabs = [["buy","Buy"],["yours","Yours"],["why","Why"],["chain","Chain"]];
  const toks = Object.values(S.desk.tokens);
  return `
  <header class="top">
    <div class="toprow">
      <div class="brand"><span class="led" id="led"></span> Crowd Mark</div>
      <span class="state"><b id="stateTxt">starting</b> · <span id="tickCount">0</span> updates</span>
      <span class="state" id="ages"></span>
      <span class="grow"></span>
      <button class="btn" id="tourBtn">Show me how it works</button>
      <button class="btn key" id="connectBtn">${S.wallet ? F.short(S.wallet) : "Connect wallet"}</button>
    </div>
    <div class="rail" id="rail">
      ${toks.map(t => `<button data-sym="${t.symbol}" aria-selected="${t.symbol===S.sym}">
        ${esc(t.company)}<span class="tick ${railClass(t)}">${railTick(t)}</span>
      </button>`).join("")}
    </div>
    <div class="tabs" id="tabs">
      ${tabs.map(([k,l]) => `<button data-view="${k}" aria-selected="${k===S.view}">${l}</button>`).join("")}
    </div>
  </header>
  <main id="main"></main>
  <footer class="foot">
    <p>Order books, fills and prices read from Polymarket by your browser as you watch. Token prices
      and costs from PreStocks and Jupiter. Transfer fees, pause flags, delegates and multipliers read
      from Solana. Headlines from the GDELT news index. Marks published to a Solana program and read
      back here.</p>
    <p><b>Information, not advice.</b> The crowd prices the company. A token is exposure to that
      company through an issuer's holding entity, and what it pays on a listing depends on conversion
      terms no market prices. Anthropic states that any transfer of its stock it has not approved is
      void, and that tokenised exposure may have no value.</p>
  </footer>
  <div class="toast" id="toast"></div>`;
}

function render(){
  if(!$("#main")){
    document.body.innerHTML = shell();
    wireShell();
  }
  $$("#rail button").forEach(b => b.setAttribute("aria-selected", b.dataset.sym === S.sym));
  $$("#tabs button").forEach(b => b.setAttribute("aria-selected", b.dataset.view === S.view));
  $("#main").innerHTML = VIEWS[S.view]();
  WIRE[S.view]?.();
  setState(S.state);
  paintAges();
}

function wireShell(){
  $("#rail").onclick = e => {
    const b = e.target.closest("button[data-sym]");
    if(b){ openCompany(b.dataset.sym); syncHash(); }
  };
  $("#tabs").onclick = e => {
    const b = e.target.closest("button[data-view]");
    if(b){ S.view = b.dataset.view; syncHash(); render(); }
  };
  $("#connectBtn").onclick = connect;
  $("#tourBtn").onclick = startTour;
  document.addEventListener("keydown", e => {
    if(e.target.matches("input,select,textarea")) return;
    const keys = {1:"buy",2:"yours",3:"why",4:"chain"};
    if(keys[e.key]){ S.view = keys[e.key]; syncHash(); render(); }
  });
}

/* ==================================================================== live == */
function viewLive(){
  const t = S.desk.tokens[S.sym];
  if(!t.covered) return uncovered(t);
  if(!S.ev) return `<div class="card"><h2>${esc(t.company)}</h2>
    <div class="pad"><p class="mid">Opening the market…</p></div></div>`;

  const card = liveCard();
  /* Keep each market's real position, so clicking a row opens that row. */
  const live = S.ev.markets.map((m, idx) => ({m, idx})).filter(x => x.m.yesId);
  /* Two different kinds of market end up here and they must not be drawn the
     same way. A set of brackets is a distribution: the odds share out one whole
     and are shown as shares of it. A ladder asks whether the valuation REACHES
     each level, so its rows are separate questions whose odds do not add up to
     anything, and normalising them would turn a near certainty into a fifth.
     Only the upward rungs feed the model, so the downward ones are marked. */
  const ladder = t.kind === "valuation";
  const isNo = x => ladder ? /^\u2193/.test(x.m.title) : /^no ipo/i.test(x.m.title);
  const bars = live.filter(x => !isNo(x));
  const none = ladder ? null : live.find(isNo);
  const ignored = ladder ? live.filter(isNo) : [];
  /* Gamma reports no 24 hour figure at all for some markets, and printing an
     absent number as zero said "nobody is betting" about a market holding tens
     of thousands of dollars. Fall back to what it does report. */
  const has24 = live.some(x => x.m.volume24 != null);
  const traded = has24 ? live.reduce((s, x) => s + (x.m.volume24 || 0), 0) : null;
  const staked = live.reduce((s, x) => s + (parseFloat(x.m.volumeNum) || 0), 0);
  /* Same trap as the volume above: if no market reports its resting size,
     that is an absent figure, not an empty book. */
  const hasLiq = live.some(x => x.m.liquidity != null);
  const resting = hasLiq ? live.reduce((s, x) => s + (x.m.liquidity || 0), 0) : null;
  const gap = card?.crowd_per_token ? card.crowd_per_token / t.token_price - 1 : null;

  /* A company whose market is a ladder of touch odds has no expected value to
     quote, so the hero says what that market does price instead of printing a
     dash where a number should be. */
  const odds = card?.crowd_odds_at_token_price ?? t.crowd_odds_at_token_price;
  const third = card?.crowd_per_token
    ? `<div class="fig"><span class="k">Crowd says it is worth</span>
        <span class="v ${cls(gap)}" id="heroCrowd">${F.usd(card.crowd_per_token)}</span>
        <span class="s">per token, right now</span></div>
       <div class="fig"><span class="k">Difference</span>
        <span class="v ${cls(gap)}" id="heroGap">${F.pct(gap, true, 1)}</span>
        <span class="s">${gap > 0 ? "token looks cheap" : "token looks dear"}</span></div>`
    : `<div class="fig"><span class="k">Company value this token implies</span>
        <span class="v">${F.big(t.token_implied_value)}</span>
        <span class="s">price times the shares behind it</span></div>
       <div class="fig"><span class="k">Crowd's odds it gets there</span>
        <span class="v ${odds != null && odds < 0.5 ? "down" : "up"}">${F.odds(odds)}</span>
        <span class="s">by 31 December</span></div>`;

  const money = has24
    ? `<b>${F.big(traded)}</b> has been staked on them in the last day`
    : `<b>${F.big(staked)}</b> has been staked on them in total, and this market does not report
       a daily figure`;
  const line = card?.crowd_per_token
    ? `<b>${live.length} outcomes</b> are open and ${money}.`
    : `This market prices whether the valuation <b>reaches</b> a level by a date, so it is a
       ladder of odds rather than a distribution, and there is no expected value to quote.
       ${money}.`;

  return `
  <div class="card" id="tour-hero">
    <div class="hero">
      <div class="name">${esc(t.company)}<small>${esc(S.ev.title || "")}</small></div>
      <div class="fig"><span class="k">Token costs</span>
        <span class="v">${F.usd(t.token_price)}</span>
        <span class="s">on PreStocks</span></div>
      ${third}
      <div class="fig"><span class="k">${has24 ? "Bet in 24 hours" : "Staked in total"}</span>
        <span class="v">${F.big(has24 ? traded : staked)}</span>
        <span class="s">across ${live.length} outcomes</span></div>
      <div class="fig"><span class="k">Resting on the book</span>
        <span class="v">${hasLiq ? F.big(resting) : "not reported"}</span>
        <span class="s">orders you could hit now</span></div>
    </div>
    <p class="answer">Every figure above is built from the bets below, in this browser, as they
      change. ${esc(t.company)} has no share price, so the only independent read on it is what
      people will stake money on. ${line}</p>
  </div>

  <div class="grid g-hero" style="margin-top:14px">
    <div class="card" id="tour-dist">
      <h2>${ladder
        ? `The crowd's odds ${esc(t.company)} reaches each level`
        : `What the crowd thinks ${esc(t.company)} will be worth`}
        <span class="r" id="distStamp">live</span></h2>
      <div class="dist" id="dist">${distRows(bars, ladder)}</div>
      ${ignored.length ? `<div class="row" style="border-top:1px solid var(--line)">
        <span class="k">${ignored.length} more rungs ask whether it falls to a level instead,
          which is a different question, so they are not used above</span>
        <span class="v dim">${ignored.length}</span></div>` : ""}
      ${none ? `<div class="row" style="border-top:1px solid var(--line)">
        <span class="k">The crowd also prices no listing at all, which is left out of the
          value above rather than counted as zero</span>
        <span class="v warn">${F.odds(none.m.yes)}</span></div>` : ""}
      <p class="cap">Each row is a real market you can trade. ${ladder
        ? `The bar is the crowd's own probability that the valuation reaches that level by 31
           December. These are separate questions, not shares of one whole, so they do not add
           to a hundred.`
        : `The bar is the crowd's probability, shown as a share of all the brackets together.`}
        The middle column is the best bid and offer, and the last is the move in the past hour.
        Click a row to see its order book.</p>
    </div>

    <div class="card" id="tour-news">
      <h2>Why it might be moving <span class="r" id="newsStamp"></span></h2>
      <div class="news" id="news"><p class="cap">Looking for headlines…</p></div>
    </div>
  </div>

  <div class="grid g-2" style="margin-top:14px">
    <div class="card" id="tour-book">
      <h2>Order book <span class="r" id="bookTitle">${esc(live[S.pick]?.title || "")}</span></h2>
      <div class="book" id="book"><p class="cap">Reading the book…</p></div>
    </div>
    <div class="card" id="tour-tape">
      <h2>Fills and quote changes <span class="r">newest first</span></h2>
      <div class="tape" id="tape"><p class="cap">Waiting for the next trade…</p></div>
    </div>
  </div>

  <div class="card" style="margin-top:14px" id="tour-hist">
    <h2>What the crowd has said ${esc(t.company)} is worth, this past week</h2>
    <div id="hist"><p class="cap">Building it from every bracket's history…</p></div>
  </div>`;
}

function distRows(bars, ladder){
  /* A ladder's rows are read as they are. Brackets are read as shares of the
     whole, which is what the model does with them. */
  const total = ladder ? 1 : (bars.reduce((s, x) => s + (x.m.yes || 0), 0) || 1);
  const top = ladder ? 1 : (Math.max(...bars.map(x => x.m.yes || 0)) || 1);
  return bars.map(({m, idx}, i) => `
    <div class="brow ${idx===S.pick?"on":""}" data-i="${idx}" id="b${i}">
      <span class="lab">${esc(m.title)}</span>
      <span class="bar"><i style="width:${((m.yes||0)/top*100).toFixed(1)}%"></i></span>
      <span class="p" id="bp${i}">${F.odds((m.yes||0)/total)}</span>
      <span class="q" id="bq${i}">${F.cents(m.bestBid)} / ${F.cents(m.bestAsk)}</span>
      <span class="c ${cls(m.hourChange)}" id="bc${i}">${m.hourChange!=null?F.pct(m.hourChange,true,1):"—"}</span>
    </div>`).join("");
}

function wireLive(){
  const d = $("#dist");
  if(d) d.onclick = e => {
    const row = e.target.closest(".brow");
    if(row) loadBracket(+row.dataset.i);
  };
  paintBook(); paintTrades(); paintHistory();
  if(S.news) loadNews(S.sym);
}

function paintBook(){
  const el = $("#book");
  if(!el) return;
  const m = S.ev?.markets[S.pick];
  const b = (m && tape.books.get(m.yesId)) || S.book;
  if(!b){ el.innerHTML = `<p class="cap">No resting orders on this one.</p>`; return; }
  const asks = b.asks.slice(0, 8).reverse(), bids = b.bids.slice(0, 8);
  const most = Math.max(...[...asks, ...bids].map(r => r.size), 1);
  const line = (r, side) => `<div class="lvl ${side}">
    <span class="depth" style="width:${(r.size/most*100).toFixed(0)}%"></span>
    <span class="px">${F.cents(r.price)}</span>
    <span>${F.num(r.size, 0)}</span>
    <span>${F.usd(r.price*r.size, 0)}</span></div>`;
  const spread = b.asks[0] && b.bids[0] ? b.asks[0].price - b.bids[0].price : null;
  el.innerHTML =
    `<div class="lvl" style="color:var(--ink-3);font-size:10px;letter-spacing:.07em">
       <span class="px">PRICE</span><span>SHARES</span><span>VALUE</span></div>` +
    asks.map(r => line(r, "ask")).join("") +
    `<div class="mid-row"><span>spread <b>${spread!=null?F.cents(spread):"—"}</b></span>
      <span>${b.bids.length} bids · ${b.asks.length} asks</span></div>` +
    bids.map(r => line(r, "bid")).join("");
  const title = $("#bookTitle");
  if(title && m) title.textContent = m.title;
}

function paintTrades(){
  const el = $("#tape");
  if(!el) return;
  if(!S.trades.length){ el.innerHTML = `<p class="cap">No fills on this outcome yet.</p>`; return; }
  el.innerHTML = S.trades.slice(0, 40).map(t => `
    <div class="t">
      <span class="dim">${F.clock(t.at)}</span>
      <span class="${t.side==="BUY"?"buy":"sell"}">${t.side}</span>
      <span>${F.num(t.size,0)} @ ${F.cents(t.price)}</span>
      <span class="w">${F.short(t.wallet)}</span>
    </div>`).join("");
}

/* A quote change, straight from the socket, put at the top of the tape. */
function pushTick(ev){
  const el = $("#tape");
  if(!el || S.view !== "why") return;
  const m = S.ev?.markets.find(x => x.yesId === ev.asset);
  const row = document.createElement("div");
  /* Dimmer than a fill, and labelled, because this is an order appearing or
     leaving the book rather than money changing hands. */
  row.className = "t" + (ev.trade ? "" : " quote");
  row.innerHTML = `<span class="dim">${F.clock(ev.at)}</span>
    <span class="${ev.side==="BUY"?"buy":"sell"}">${ev.trade?(ev.side||"—"):"quote"}</span>
    <span>${F.num(ev.size,0)} @ ${F.cents(ev.price)}</span>
    <span class="w">${esc((m?.title||"").slice(0,12))}</span>`;
  if(el.firstElementChild?.tagName === "P") el.innerHTML = "";
  el.prepend(row);
  while(el.children.length > 60) el.lastElementChild.remove();
}

function paintHistory(){
  const el = $("#hist");
  if(!el) return;
  if(!S.history){ el.innerHTML = `<p class="cap">Not enough history on these brackets yet.</p>`; return; }
  const t = S.desk.tokens[S.sym];
  el.innerHTML = areaChart(S.history, t.token_price);
}

/* The one chart the terminal draws: the crowd's implied value per token over
   time, against what the token actually costs. Where the line sits above the
   dashes, the crowd is saying the token is cheap. */
function areaChart(series, tokenPrice){
  const W = 1000, H = 260, L = 64, R = 18, T = 18, B = 30;
  const xs = series.map(p => p.t), ys = series.map(p => p.per);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let lo = Math.min(...ys, tokenPrice), hi = Math.max(...ys, tokenPrice);
  const padv = (hi - lo) * 0.12 || hi * 0.1;
  lo -= padv; hi += padv;
  const X = v => L + (v - x0) / ((x1 - x0) || 1) * (W - L - R);
  const Y = v => T + (hi - v) / ((hi - lo) || 1) * (H - T - B);
  const line = series.map((p, i) => `${i?"L":"M"}${X(p.t).toFixed(1)},${Y(p.per).toFixed(1)}`).join("");
  const area = `${line}L${X(x1).toFixed(1)},${Y(lo).toFixed(1)}L${X(x0).toFixed(1)},${Y(lo).toFixed(1)}Z`;
  const ticks = [0, .25, .5, .75, 1].map(f => {
    const t = x0 + (x1 - x0) * f;
    return `<text class="ax" x="${X(t).toFixed(0)}" y="${H-10}" text-anchor="${f===0?"start":f===1?"end":"middle"}">${
      new Date(t).toUTCString().slice(5,11)}</text>`;
  }).join("");
  const grid = [lo, (lo+hi)/2, hi].map(v =>
    `<line class="gl" x1="${L}" y1="${Y(v).toFixed(1)}" x2="${W-R}" y2="${Y(v).toFixed(1)}"/>
     <text class="ax" x="${L-8}" y="${(Y(v)+3).toFixed(1)}" text-anchor="end">${F.usd(v,0)}</text>`).join("");
  const now = series[series.length-1];
  return `<svg viewBox="0 0 ${W} ${H}" role="img"
      aria-label="The crowd's implied value per token over the past week, against the token's price">
    <defs><linearGradient id="fade" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0%" stop-color="#4d9dff" stop-opacity=".30"/>
      <stop offset="100%" stop-color="#4d9dff" stop-opacity="0"/></linearGradient></defs>
    ${grid}
    <path class="ar" d="${area}"/>
    <path class="ln" d="${line}"/>
    <line class="mk" x1="${L}" y1="${Y(tokenPrice).toFixed(1)}" x2="${W-R}" y2="${Y(tokenPrice).toFixed(1)}"/>
    <text class="mkl" x="${L+6}" y="${(Y(tokenPrice)-6).toFixed(1)}">token costs ${F.usd(tokenPrice,0)}</text>
    <circle cx="${X(now.t).toFixed(1)}" cy="${Y(now.per).toFixed(1)}" r="4" fill="#4d9dff"/>
    ${ticks}
  </svg>
  <p class="cap">Built here from every bracket's own price history, run through the same model the
    keeper publishes. This is not a price anyone quoted: it is what the crowd's whole distribution
    implied, hour by hour.</p>`;
}

/* The shipped snapshot stamps seconds, the live feed stamps milliseconds.
   Reading one as the other reported headlines as decades old. */
const asMs = t => t == null ? null : t > 1e12 ? t : t * 1000;

function paintNews(articles, at, fresh, refused){
  const el = $("#news"), stamp = $("#newsStamp");
  if(!el) return;
  if(stamp) stamp.textContent = at ? (fresh ? "just now" : F.ago(asMs(at))) : "";
  if(!articles.length){
    el.innerHTML = refused
      ? `<p class="cap">The news index turned this query away when the snapshot was built, so
         there is nothing to show yet rather than nothing to find. Your browser is asking it
         again now.</p>`
      : `<p class="cap">No headline in the past week names this company alongside its funding,
         valuation or a listing. Stories that merely mention it are left out.</p>`;
    return;
  }
  el.innerHTML = articles.map(a => `
    <a class="na" href="${esc(a.url)}" target="_blank" rel="noopener noreferrer">
      ${a.image ? `<img src="${esc(a.image)}" alt="" loading="lazy"
         onerror="this.remove()">` : ""}
      <span class="b"><span class="h">${esc(a.title)}</span>
        <span class="m">${esc(a.domain||"")} · ${a.at?F.ago(asMs(a.at)):""}</span></span>
    </a>`).join("");
}

function uncovered(t){
  return `<div class="card">
    <div class="hero">
      <div class="name">${esc(t.company)}<small>no prediction market</small></div>
      <div class="fig"><span class="k">Token costs</span>
        <span class="v">${F.usd(t.token_price)}</span></div>
      <div class="fig"><span class="k">Issuer's own mark</span>
        <span class="v">${F.usd(t.mark_price)}</span></div>
      <div class="fig"><span class="k">Premium to that mark</span>
        <span class="v ${cls(t.premium_to_mark)}">${F.pct(t.premium_to_mark)}</span></div>
    </div>
    <p class="answer">Nobody runs a market on what ${esc(t.company)} is worth, so this terminal
      has no second opinion to offer on the price. The only figure available is the issuer's own,
      and the issuer is the party selling the token. The <b>Cost</b> screen still applies: what it
      costs to trade and what the issuer can do to your balance are measured from the chain.</p>
  </div>

  <div class="card" style="margin-top:14px">
    <h2>What the crowd does bet on ${esc(t.company)} <span class="r" id="othStamp"></span></h2>
    <div id="other"><p class="cap">Looking…</p></div>
    <p class="cap">This terminal only prices a company when a market asks what it will be worth.
      These ask other questions, so none of them can be turned into a value per token. Judge that
      for yourself from the titles.</p>
  </div>`;
}

/* Fill in the markets that exist but do not price a valuation. */
async function loadOther(company){
  const el = $("#other");
  if(!el) return;
  try{
    const {searchMarkets} = await import("./poly.js");
    const found = await searchMarkets(company);
    const stamp = $("#othStamp");
    if(stamp) stamp.textContent = found.length ? `${found.length} open` : "";
    el.innerHTML = found.length
      ? `<div class="rows">${found.map(m => `<div class="row">
          <span class="k"><a href="https://polymarket.com/event/${esc(m.slug)}"
            target="_blank" rel="noopener">${esc(m.title)}</a></span>
          <span class="v">${F.big(m.volume)}</span></div>`).join("")}</div>`
      : `<p class="cap">No open market mentions ${esc(company)} at all.</p>`;
  }catch(e){
    el.innerHTML = `<p class="cap">Could not reach Polymarket just then.</p>`;
  }
}

/* A small deterministic generator, so the simulation below gives the same
   answer every time the screen is drawn rather than jittering. */
function seeded(seed){
  let x = seed >>> 0;
  return () => {
    x ^= x << 13; x >>>= 0;
    x ^= x >> 17;
    x ^= x << 5; x >>>= 0;
    return x / 4294967296;
  };
}

/* What the distribution actually pays, rather than what it averages.

   An expected value is one number from a whole distribution, and for a set of
   brackets skewed to the right it sits above most of the outcomes in it. So
   the brackets are sampled directly: pick one with its own probability, take a
   value inside it, and see what the token would be worth. The median and the
   chance of landing below today's price are what a holder actually faces.
*/
function payoff(brackets, shares, price, draws = 20000){
  if(!brackets.length || !shares) return null;
  const total = brackets.reduce((s, b) => s + b.p, 0) || 1;
  const cum = [];
  let acc = 0;
  for(const b of brackets){ acc += b.p / total; cum.push(acc); }
  const rnd = seeded(20260923);
  const out = new Float64Array(draws);
  for(let i = 0; i < draws; i++){
    const u = rnd();
    let k = cum.findIndex(c => u <= c);
    if(k < 0) k = brackets.length - 1;
    const b = brackets[k];
    out[i] = (b.low + rnd() * (b.high - b.low)) / shares;
  }
  out.sort();
  const at = q => out[Math.min(draws - 1, Math.floor(q * draws))];
  let below = 0;
  for(let i = 0; i < draws; i++) if(out[i] < price) below++;
  return {median: at(0.5), p10: at(0.10), p90: at(0.90),
          mean: out.reduce((a, b) => a + b, 0) / draws,
          below: below / draws, draws};
}


/* ===================================================================== buy ==

   The one screen this app is for. A verdict, what it would cost, and a button.
   Everything that justifies the verdict lives one tab away, because a person
   deciding whether to spend a hundred dollars needs an answer first and the
   working afterwards.
*/

/* The verdict, and the reasons it might be wrong, in the same breath.

   A headline on its own would be a recommendation, which this is not entitled
   to give: the gap is real but so is the cost of reaching it, and so is what
   the issuer can do to a holder afterwards. So the catches are part of the
   verdict rather than a footnote under it.
*/
function verdict(t){
  const trip = (t.round_trip || []).find(r => r.cost != null) || null;
  const exit = trip?.cost ?? null;
  const catches = [];

  if(trip){
    catches.push(`Buying <b>${F.usd(trip.size, 0)}</b> and selling straight back costs
      <b>${F.pct(exit, false, 2)}</b>, so the gap has to beat that before it is worth anything to
      you. Larger amounts cost more, and the Yours tab has the rest.`);
  }
  const card = liveCard();
  const brackets = card?.brackets?.length ? card.brackets : (t.brackets || []);
  const sim = brackets.length && t.shares ? payoff(brackets, t.shares, t.token_price) : null;
  if(sim){
    catches.push(`Sampling the crowd's own odds, it ends below what you would pay today
      <b>${F.odds(sim.below)}</b> of the time. The average is above, the outcomes are spread.`);
  }
  const fee = t.powers?.transfer_fee_bps;
  const issuer = [];
  if(fee) issuer.push(`takes ${(fee/100).toFixed(2)}% every time the token moves`);
  if(t.powers?.freeze_authority) issuer.push("can freeze your account");
  if(t.powers?.permanent_delegate) issuer.push("can move your tokens without asking");
  if(issuer.length) catches.push(`The issuer ${issuer.join(", ")}.`);

  /* The one company in this set that has already listed, and what its token
     actually pays. This is the only realised evidence anybody has about what
     conversion is worth, so it is not a footnote. */
  const px = S.desk.spacex;
  const listed = t.symbol === "SPACEX";

  if(listed && px){
    return {
      word: px.discount > 0.05 ? "Trades below the real thing" : "Trades near the real thing",
      tone: px.discount > 0.05 ? "down" : "mid",
      gap: -px.discount, net: -px.discount, sim, exit, precedent: px,
      line: `${esc(t.company)} has already listed, so this one needs no prediction market. Its
        listed stock token trades at <b>${F.usd(px.listed_token_usd)}</b> and this PreStocks token
        at <b>${F.usd(px.prestocks_token_usd)}</b>, a discount of
        <b class="down">${F.pct(px.discount, false, 1)}</b>. That gap is what conversion has
        actually been worth, on the only case anyone can check.`,
      catches};
  }

  const gap = t.gap;
  if(!t.covered || gap == null){
    const prem = t.premium_to_mark;
    return {word: "No independent price", tone: "warn", gap: null, sim, exit, precedent: px,
      line: `Nobody runs a market on what ${esc(t.company)} is worth, so the only figure anyone can
        quote is the issuer's own mark of <b>${F.usd(t.mark_price)}</b>, and the issuer is the
        party selling you the token. This trades
        <b class="${cls(prem)}">${F.pct(prem, true, 1)}</b> against that mark.`,
      catches};
  }

  const net = exit != null ? gap - exit : gap;
  /* What the crowd's value becomes if conversion pays what it has paid on the
     one company that listed. */
  const adjusted = px && t.crowd_per_token ? t.crowd_per_token * (1 - px.discount) : null;
  const afterPrecedent = adjusted ? adjusted / t.token_price - 1 : null;

  let word, tone;
  if(afterPrecedent != null && net > 0.10 && afterPrecedent < 0){
    word = "Cheap on the crowd, dear on the precedent";
    tone = "warn";
  } else if(afterPrecedent != null && afterPrecedent > 0.10){
    word = "Cheap either way";
    tone = "up";
  } else {
    word = net > 0.10 ? "Looks cheap" : net < -0.10 ? "Looks dear" : "Looks about right";
    tone = net > 0.10 ? "up" : net < -0.10 ? "down" : "mid";
  }

  const line = `The token costs <b>${F.usd(t.token_price)}</b>. People betting real money on
    ${esc(t.company)}'s listing price it at <b>${F.usd(t.crowd_per_token)}</b> a token, which is
    <b class="${cls(gap)}">${F.pct(gap, true, 1)}</b> away. After what it costs to get in and out
    that is <b class="${cls(net)}">${F.pct(net, true, 1)}</b>.`;

  if(px && adjusted){
    catches.unshift(`<b>The only company here that has already listed still trades
      ${F.pct(px.discount, false, 1)} below its listed stock.</b> Conversion has not paid what the
      crowd expected. Apply that same discount here and
      ${F.usd(t.crowd_per_token)} becomes <b>${F.usd(adjusted)}</b>, which is
      <b class="${cls(afterPrecedent)}">${F.pct(afterPrecedent, true, 1)}</b> against what you
      would pay today.`);
  }
  return {word, tone, gap, net, sim, exit, precedent: px, adjusted, afterPrecedent, line, catches};
}

function viewBuy(){
  const t = S.desk.tokens[S.sym];
  const v = verdict(t);
  const q = S.quote;

  return `
  <div class="card verdict ${v.tone}" id="tour-verdict">
    <div class="vhead">
      <div>
        <div class="vco">${esc(t.company)}</div>
        <div class="vword ${v.tone}">${v.word}</div>
      </div>
      <div class="vnums">
        <div class="fig"><span class="k">You would pay</span>
          <span class="v">${F.usd(t.token_price)}</span>
          <span class="s">a token, right now</span></div>
        ${t.crowd_per_token ? `<div class="fig"><span class="k">The crowd says</span>
          <span class="v ${cls(v.gap)}">${F.usd(t.crowd_per_token)}</span>
          <span class="s">rebuilt live from their bets</span></div>` : ""}
        ${v.adjusted ? `<div class="fig"><span class="k">If conversion pays what it has</span>
          <span class="v ${cls(v.afterPrecedent)}">${F.usd(v.adjusted)}</span>
          <span class="s">on the one that listed</span></div>` : ""}
        ${!t.covered && t.symbol !== "SPACEX" ? `<div class="fig"><span class="k">Issuer's own mark</span>
          <span class="v">${F.usd(t.mark_price)}</span>
          <span class="s">the only figure available</span></div>` : ""}
      </div>
    </div>
    <p class="vline">${v.line}</p>
    ${v.catches.length ? `<div class="catches">
      <div class="clab">Before you do</div>
      ${v.catches.map(c => `<p>${c}</p>`).join("")}
    </div>` : ""}
    <p class="cap">Every figure here is read in this browser as you look at it.
      <a href="#${S.sym.toLowerCase()}/why" id="whyLink">Show me where they come from</a>.</p>
  </div>

  <div class="card" style="margin-top:14px" id="tour-buy">
    <h2>Buy it <span class="r">on Solana, with your own wallet</span></h2>
    <div class="buybox">
      <div class="amt">
        <label for="amt">Amount in USDC</label>
        <input id="amt" inputmode="decimal" value="${S.amount}">
        <div class="quick">${[25, 100, 500].map(a =>
          `<button class="btn sm" data-amt="${a}">$${a}</button>`).join("")}</div>
      </div>
      <div class="gets" id="gets">
        ${q ? `
          <div class="row"><span class="k">You get</span>
            <span class="v">${F.num(q.tokens, 6)} ${esc(S.sym)}</span></div>
          <div class="row"><span class="k">Price you pay per token</span>
            <span class="v">${F.usd(q.perToken)}</span></div>
          <div class="row"><span class="k">Pool impact at this size</span>
            <span class="v ${q.impact > 0.01 ? "warn" : ""}">${F.pct(q.impact, false, 3)}</span></div>
          ${q.slippageBps ? `<div class="row"><span class="k">Slippage allowed</span>
            <span class="v">${(q.slippageBps / 100).toFixed(2)}%</span></div>` : ""}
          <div class="row"><span class="k">Route</span>
            <span class="v" style="font-size:11px">${esc(q.route.join(" then ") || "direct")}</span></div>
          ${t.crowd_per_token ? `<div class="row"><span class="k">Worth at the crowd's number</span>
            <span class="v ${cls(v.gap)}">${F.usd(q.tokens * t.crowd_per_token)}</span></div>` : ""}
        ` : `<p class="cap">Enter an amount to get a real quote.</p>`}
      </div>
    </div>
    <div class="field two">
      <button class="btn big" id="dryBtn" ${q ? "" : "disabled"}>Dry run, costs nothing</button>
      <button class="btn key big" id="buyBtn" ${S.wallet && q ? "" : "disabled"}>
        ${!S.wallet ? "Connect a wallet to buy"
          : q ? `Buy ${F.usd(q.dollars, 0)} of ${esc(t.company)}` : "Enter an amount"}</button>
    </div>
    <div id="buyOut" class="cap"></div>
    ${t.powers?.transfer_fee_bps ? `<p class="note"><b>Why the slippage is set where it is.</b>
      The issuer takes ${(t.powers.transfer_fee_bps / 100).toFixed(2)}% as the tokens move, so less
      arrives than the route promises. We measured it: a one percent limit is refused every time
      and three percent goes through every time, on a trade whose pool impact is about a tenth of a
      percent. A limit below the transfer fee reverts however deep the pool is, which is not
      something any swap screen tells you.</p>` : ""}
    <p class="cap">These tokens only exist on mainnet, so there is no test network to try this on.
      <b>Dry run builds the real transaction and runs it against the chain as it stands right
      now</b>, without signing, sending or spending anything, so you can see it would go through
      before deciding to. Buying for real routes through Jupiter and your own wallet signs it.
      Nothing here touches your keys or your balance, and nobody takes a fee.</p>
  </div>`;
}

function wireBuy(){
  const amt = $("#amt");
  if(!amt) return;
  const requote = () => {
    const dollars = parseFloat(amt.value);
    if(!(dollars > 0)){ S.quote = null; render(); return; }
    S.amount = amt.value;
    getQuote(dollars);
  };
  amt.addEventListener("change", requote);
  amt.addEventListener("keydown", e => { if(e.key === "Enter") requote(); });
  $$("button[data-amt]").forEach(b => b.onclick = () => {
    amt.value = b.dataset.amt; S.amount = b.dataset.amt; getQuote(+b.dataset.amt);
  });
  const link = $("#whyLink");
  if(link) link.onclick = e => { e.preventDefault(); S.view = "why"; syncHash(); render(); };

  const btn = $("#buyBtn");
  if(btn && S.wallet && S.quote) btn.onclick = doBuy;
  const dry = $("#dryBtn");
  if(dry && S.quote) dry.onclick = doDryRun;
  if(!S.quote && parseFloat(S.amount) > 0) getQuote(parseFloat(S.amount));
}

/* A real quote, not an estimate from the shipped price. */
async function getQuote(dollars){
  const t = S.desk.tokens[S.sym];
  const box = $("#gets");
  if(box) box.innerHTML = `<p class="cap">Asking Jupiter for a route…</p>`;
  try{
    const {quote, slippageFor} = await import("./swap.js");
    const bps = slippageFor(t.powers?.transfer_fee_bps);
    S.slippage = bps;
    const q = await quote(t.mint, dollars, bps);
    const tokens = q.outRaw / 10 ** 9;          // these mints carry nine decimals
    S.quote = {dollars: q.inDollars, tokens, perToken: q.inDollars / tokens,
               impact: q.impact, route: q.route, raw: q.raw, slippageBps: bps};
    if(S.view === "buy") render();
  }catch(e){
    S.quote = null;
    if(box) box.innerHTML = `<p class="cap down">${esc(e.message)}</p>`;
  }
}

/* Prove the trade works, for nothing.

   A judge or a stranger should not have to spend money to find out whether
   this is real. The transaction built here is the same one the buy button
   sends; it is simply handed to the chain to run rather than to sign.
*/
async function doDryRun(){
  const t = S.desk.tokens[S.sym], out = $("#buyOut"), btn = $("#dryBtn");
  btn.disabled = true;
  const step = m => out.innerHTML = `<span class="mid">${esc(m)}…</span>`;
  try{
    const {dryRun} = await import("./swap.js");
    /* Any address works for a rehearsal, so nobody needs a wallet to try it. */
    const owner = S.wallet || "2sujbbTjp2r5ugbjfHgUNDSwtdVfYpTiCSKPgT84CvD7";
    const r = await dryRun(t.mint, S.quote.dollars, owner, step, S.quote.slippageBps);
    out.innerHTML = r.ok
      ? `<b class="up">It would go through.</b> The real transaction was built
         (${r.bytes} bytes) and run against Solana as it stands now, using
         ${F.num(r.units)} compute units, without being signed or sent.
         ${S.wallet ? "" : "It was rehearsed against a sample wallet, since you have not connected one."}`
      : `<b class="warn">The chain would reject it.</b>
         <span class="dim">${esc(JSON.stringify(r.err).slice(0, 120))}</span>
         That is usually the sample wallet holding no USDC, which is exactly what this is for.`;
    btn.disabled = false;
  }catch(e){
    out.innerHTML = `<span class="down">${esc(e.message || e)}</span>`;
    btn.disabled = false;
  }
}

async function doBuy(){
  const t = S.desk.tokens[S.sym], out = $("#buyOut"), btn = $("#buyBtn");
  btn.disabled = true;
  const step = m => out.innerHTML = `<span class="mid">${esc(m)}…</span>`;
  try{
    const {buy, usdcBalance} = await import("./swap.js");
    step("Checking your balance");
    const have = await usdcBalance(S.wallet);
    if(have < S.quote.dollars){
      throw new Error(`This wallet holds ${F.usd(have)} of USDC and the trade needs ` +
                      `${F.usd(S.quote.dollars)}.`);
    }
    const {signature} = await buy(t.mint, S.quote.dollars, providerOf(), step,
                                 S.quote.slippageBps);
    out.innerHTML = `<b class="up">Done.</b> You now hold
      ${F.num(S.quote.tokens, 6)} ${esc(S.sym)}.
      <a href="https://explorer.solana.com/tx/${signature}" target="_blank"
         rel="noopener">See the transaction</a>.`;
    toast("Bought on Solana");
    S.quote = null;
  }catch(e){
    out.innerHTML = `<span class="down">${esc(e.message || e)}</span>`;
    btn.disabled = false;
  }
}

/* =================================================================== yours == */
function viewYours(){
  const t = S.desk.tokens[S.sym];
  const rt = t.round_trip || [];
  const pw = t.powers || {};
  const pools = (S.lp?.pools || []).filter(p =>
    p.symbol === S.sym && p.corroborated && !p.never_traded);

  return `
  <div class="card">
    <h2>What a wallet holds</h2>
    <div class="field">
      <input id="addr" placeholder="Paste any Solana address" value="${S.wallet || ""}">
      <button class="btn" id="goBtn">Look</button>
    </div>
    <div id="posOut" class="rows"></div>
    ${S.wallet ? "" : `<p class="cap">Connect a wallet above and this fills in by itself.</p>`}
  </div>

  <div class="grid g-2" style="margin-top:14px">
    <div class="card">
      <h2>What it costs to get out of ${esc(t.company)}</h2>
      <div class="rows">
        ${rt.map(r => `<div class="row"><span class="k">In and straight back out at ${F.usd(r.size, 0)}</span>
          <span class="v ${r.cost > 0.03 ? "down" : "warn"}">${
            r.cost != null ? F.pct(r.cost, false, 2) : "no route"}</span></div>`).join("")}
        <div class="row"><span class="k">Liquidity behind it</span>
          <span class="v">${F.big(t.depth?.liquidity)}</span></div>
        <div class="row"><span class="k">Traded in 24 hours</span>
          <span class="v">${F.big(t.depth?.volume24h)}</span></div>
        <div class="row"><span class="k">People holding it</span>
          <span class="v">${F.num(t.depth?.holders)}</span></div>
      </div>
      <p class="cap">Real quotes from Jupiter in both directions, including the pool's own price
        impact and the issuer's transfer fee. Not a modelled spread.</p>
    </div>

    <div class="card">
      <h2>What the issuer can do to your balance</h2>
      <div class="chips">
        <span class="chip ${pw.transfer_fee_bps ? "hot" : "ok"}">transfer fee ${
          pw.transfer_fee_bps != null ? (pw.transfer_fee_bps / 100).toFixed(2) + "%" : "none"}</span>
        <span class="chip ${pw.freeze_authority ? "hot" : "ok"}">${
          pw.freeze_authority ? "can freeze your account" : "cannot freeze"}</span>
        <span class="chip ${pw.permanent_delegate ? "hot" : "ok"}">${
          pw.permanent_delegate ? "can move your tokens" : "no delegate"}</span>
        <span class="chip ${pw.paused ? "hot" : "ok"}">${
          pw.paused ? "transfers paused" : "not paused"}</span>
      </div>
      ${(S.desk.fee_history || []).length > 1 ? `<div class="rows" style="border-top:1px solid var(--line)">
        ${S.desk.fee_history.map(f => `<div class="row">
          <span class="k">${new Date(f.at).toUTCString().slice(5, 16)}</span>
          <span class="v ${f.bps > 50 ? "down" : ""}">${(f.bps / 100).toFixed(2)}%</span></div>`).join("")}
      </div>
      <p class="cap">Not theoretical. This desk was watching when the fee changed, and recorded
        it.</p>` : `<p class="cap">Read from the mint on Solana, not from the issuer's website.</p>`}
    </div>
  </div>

  ${pools.length ? `<div class="card" style="margin-top:14px">
    <h2>Or provide liquidity instead <span class="r">${S.lp.window_hours} hourly readings</span></h2>
    <div class="rows">
      ${pools.slice(0, 3).map(p => `
        <div class="row"><span class="k">${esc(p.pool)} at ${(p.base_fee_pct || 0).toFixed(2)}%
          in ${p.bin_step} step bins earns</span>
          <span class="v up">${F.pct(p.fee_yield_day, false, 3)} a day</span></div>
        <div class="row"><span class="k">but loses to arbitrage</span>
          <span class="v down">${F.pct(p.lvr_day_cpmm, false, 4)} a day</span></div>
        <div class="row"><span class="k">so stay wider than</span>
          <span class="v">${p.breakeven_half_width
            ? "±" + (p.breakeven_half_width * 100).toFixed(2) + "%" : "no width works"}</span></div>
      `).join("")}
    </div>
    <p class="cap">Fee income and volatility measured from our own hourly readings. The arbitrage
      loss is the rate Milionis, Moallemi, Roughgarden and Zhang give for a constant product pool,
      raised for a concentrated position by the closed form in the same paper.</p>
  </div>` : ""}

  <div class="card" style="margin-top:14px">
    <h2>Every token on the board</h2>
    <div class="scroll"><table>
      <colgroup><col style="width:17%"><col style="width:12%"><col style="width:12%"><col style="width:12%">
        <col style="width:11%"><col style="width:12%"><col style="width:12%"><col style="width:12%"></colgroup>
      <thead><tr><th>Token</th><th class="num">Price</th><th class="num">Issuer mark</th>
        <th class="num">Crowd</th><th class="num">Gap</th><th class="num">Liquidity</th>
        <th class="num">Exit $10k</th><th class="num">Fee</th></tr></thead>
      <tbody>${Object.values(S.desk.tokens).map(x => `
        <tr data-pick data-sym="${x.symbol}" class="${x.symbol === S.sym ? "on" : ""}">
          <td>${esc(x.company)}</td>
          <td class="num">${F.usd(x.token_price)}</td>
          <td class="num">${F.usd(x.mark_price)}</td>
          <td class="num">${x.crowd_per_token ? F.usd(x.crowd_per_token) : "—"}</td>
          <td class="num ${cls(x.gap)}">${x.gap != null ? F.pct(x.gap) : "—"}</td>
          <td class="num">${F.big(x.depth?.liquidity)}</td>
          <td class="num warn">${x.round_trip?.[1]?.cost != null
            ? F.pct(x.round_trip[1].cost, false, 2) : "—"}</td>
          <td class="num ${x.powers?.transfer_fee_bps ? "warn" : ""}">${
            x.powers?.transfer_fee_bps != null
              ? (x.powers.transfer_fee_bps / 100).toFixed(2) + "%" : "—"}</td>
        </tr>`).join("")}</tbody>
    </table></div>
  </div>`;
}

function wireYours(){
  $$("tr[data-sym]").forEach(r => r.onclick = () => { openCompany(r.dataset.sym); syncHash(); });
  const go = $("#goBtn");
  if(go) go.onclick = () => position($("#addr").value.trim());
  const addr = $("#addr");
  if(addr) addr.addEventListener("keydown", e => {
    if(e.key === "Enter") position(e.target.value.trim());
  });
  if(S.wallet) position(S.wallet);
}

/* ===================================================================== why == */
function viewWhy(){
  return viewLive() + viewValue();
}

/* =================================================================== value == */
function viewValue(){
  const t = S.desk.tokens[S.sym];
  if(!t.covered) return uncovered(t);
  const card = liveCard() || t;
  const shares = t.shares;

  const brackets = (card.brackets?.length ? card.brackets : t.brackets || []);
  const rows = brackets.map(b => `<tr>
    <td>${F.big(b.low)} to ${F.big(b.high)}</td>
    <td class="num">${F.odds(b.p)}</td>
    <td class="num">${F.big((b.low + b.high)/2)}</td>
    <td class="num">${F.big((b.low + b.high)/2 * b.p)}</td>
  </tr>`).join("");

  return `
  <div class="grid g-2">
    <div class="card">
      <h2>How the number is built <span class="r">live</span></h2>
      <div class="scroll"><table>
        <colgroup><col style="width:34%"><col style="width:20%"><col style="width:23%"><col style="width:23%"></colgroup>
        <thead><tr><th>If it lists at</th><th class="num">Crowd's odds</th>
          <th class="num">Midpoint</th><th class="num">Contribution</th></tr></thead>
        <tbody>${rows || `<tr><td colspan="4" class="mid">This company's market is a ladder of
          touch odds, not a distribution, so there is no expected value to build.</td></tr>`}</tbody>
      </table></div>
      ${brackets.length ? `<div class="rows" style="border-top:1px solid var(--line)">
        <div class="row"><span class="k">Expected value on listing day</span>
          <span class="v">${F.big(card.crowd_value)}</span></div>
        <div class="row"><span class="k">Shares the token implies</span>
          <span class="v">${F.num(shares)}</span></div>
        <div class="row"><span class="k">So the crowd's value per token</span>
          <span class="v up">${F.usd(card.crowd_per_token)}</span></div>
        <div class="row"><span class="k">And the token costs</span>
          <span class="v">${F.usd(t.token_price)}</span></div>
      </div>` : ""}
      <p class="cap">Each bracket contributes its midpoint weighted by its odds. The odds are
        renormalised over the brackets alone, so the chance of no listing at all is excluded rather
        than valued at zero.</p>
    </div>

    <div class="card">
      <h2>What it would actually pay <span class="r">${brackets.length?"20,000 draws":""}</span></h2>
      ${(() => {
        const sim = payoff(brackets, shares, t.token_price);
        if(!sim) return `<p class="cap">No distribution to sample for this company.</p>`;
        const skew = sim.median < sim.mean
          ? `Here the middle outcome sits <b>below</b> the average, which happens when a few very
             large outcomes pull the average up past most of the distribution.`
          : sim.median > sim.mean
          ? `Here the middle outcome sits <b>above</b> the average, which happens when a small
             chance of a very low outcome drags the average down below most of the distribution.`
          : `Here the two are level.`;
        return `<div class="rows">
          <div class="row"><span class="k">Average outcome</span>
            <span class="v">${F.usd(sim.mean)}</span></div>
          <div class="row"><span class="k">Middle outcome</span>
            <span class="v ${sim.median < t.token_price ? "down" : "up"}">${F.usd(sim.median)}</span></div>
          <div class="row"><span class="k">Bad case, one in ten</span>
            <span class="v down">${F.usd(sim.p10)}</span></div>
          <div class="row"><span class="k">Good case, one in ten</span>
            <span class="v up">${F.usd(sim.p90)}</span></div>
          <div class="row"><span class="k">Chance it lands below today's price</span>
            <span class="v ${sim.below > 0.5 ? "down" : "up"}">${F.odds(sim.below)}</span></div>
        </div>
        <p class="cap">The average is the number on the front screen, and the sampler reproducing
          it to the cent is the check that this is the same distribution. ${skew}
          ${sim.below > 0.5 ? `<b>On these odds the token would be worth less than it costs today
          more often than not, even though the average is above it.</b>` : ""}
          Sampled from the brackets themselves, conditional on a listing happening, so the chance
          of no listing is excluded here too.</p>`;
      })()}
    </div>
  </div>

  <div class="grid g-2" style="margin-top:14px">
    <div class="card">
      <h2>What has to be assumed</h2>
      <div class="rows">
        ${(card.assumptions?.length ? card.assumptions : t.assumptions || []).map(a =>
          `<div class="row"><span class="k" style="white-space:normal">${esc(a)}</span><span></span></div>`).join("")
          || `<div class="row"><span class="k">Nothing beyond the market's own prices.</span><span></span></div>`}
      </div>
      <p class="cap">The top bracket has no upper bound in the market, so a value has to be put on
        it. That is the only number here this terminal chooses, and the range it would produce at
        1.1 and 1.5 times the floor is shown above rather than hidden.</p>
    </div>
    <div class="card">
      <h2>When the crowd expects it to happen</h2>
      <div class="rows">
        ${(card.timing?.length ? card.timing : t.timing || []).slice().reverse().map(([label, p]) => `
          <div class="row"><span class="k">${esc(label)}</span>
            <span class="v">${F.odds(p)}</span></div>`).join("")
          || `<div class="row"><span class="k">No timing market open.</span><span></span></div>`}
      </div>
    </div>
  </div>

  <div style="margin-top:14px">
    <div class="card">
      <h2>Three readings of the same company</h2>
      <div class="rows">
        <div class="row"><span class="k">What the token costs</span>
          <span class="v">${F.usd(t.token_price)}</span></div>
        <div class="row"><span class="k">The issuer's own mark</span>
          <span class="v">${F.usd(t.mark_price)}</span></div>
        <div class="row"><span class="k">The crowd, right now</span>
          <span class="v up">${F.usd(card.crowd_per_token)}</span></div>
        <div class="row"><span class="k">Company value the token implies</span>
          <span class="v">${F.big(t.token_implied_value)}</span></div>
        <div class="row"><span class="k">Company value the crowd implies</span>
          <span class="v">${F.big(card.crowd_value)}</span></div>
      </div>
      <p class="cap">The issuer marks its own book. The crowd has money at stake and no relationship
        with the issuer. Where the two disagree, only one of them is being paid for the answer.</p>
    </div>
  </div>`;
}

/* ==================================================================== cost == */
function viewCost(){
  const t = S.desk.tokens[S.sym];
  const rt = t.round_trip || [];
  const pw = t.powers || {};
  const pools = (S.lp?.pools || []).filter(p =>
    p.symbol === S.sym && p.corroborated && !p.never_traded);

  return `
  <div class="grid g-3">
    <div class="card">
      <h2>Getting in and out</h2>
      <div class="rows">
        ${rt.map(r => `<div class="row"><span class="k">Round trip at ${F.usd(r.size,0)}</span>
          <span class="v ${r.cost>0.03?"down":"warn"}">${r.cost!=null?F.pct(r.cost,false,2):"no route"}</span>
        </div>`).join("")}
        <div class="row"><span class="k">Liquidity in the pools</span>
          <span class="v">${F.big(t.depth?.liquidity)}</span></div>
        <div class="row"><span class="k">Traded in 24 hours</span>
          <span class="v">${F.big(t.depth?.volume24h)}</span></div>
        <div class="row"><span class="k">Holders</span>
          <span class="v">${F.num(t.depth?.holders)}</span></div>
      </div>
      <p class="cap">Real quotes from Jupiter, both directions, including the pool's own price
        impact and the issuer's transfer fee. This is what a round trip actually costs, not a
        modelled spread.</p>
    </div>

    <div class="card">
      <h2>What the issuer can do to your balance</h2>
      <div class="chips">
        <span class="chip ${pw.transfer_fee_bps?"hot":"ok"}">transfer fee
          ${pw.transfer_fee_bps!=null?(pw.transfer_fee_bps/100).toFixed(2)+"%":"none"}</span>
        <span class="chip ${pw.freeze_authority?"hot":"ok"}">${pw.freeze_authority?"can freeze your account":"cannot freeze"}</span>
        <span class="chip ${pw.permanent_delegate?"hot":"ok"}">${pw.permanent_delegate?"permanent delegate set":"no delegate"}</span>
        <span class="chip ${pw.paused?"hot":"ok"}">${pw.paused?"transfers paused":"not paused"}</span>
        ${pw.ui_multiplier&&pw.ui_multiplier!==1?`<span class="chip hot">balance multiplier ${pw.ui_multiplier}x</span>`:""}
      </div>
      ${(S.desk.fee_history||[]).length>1?`<div class="rows" style="border-top:1px solid var(--line)">
        ${S.desk.fee_history.map(f => `<div class="row">
          <span class="k">${new Date(f.at).toUTCString().slice(5,16)}</span>
          <span class="v ${f.bps>50?"down":""}">${(f.bps/100).toFixed(2)}%</span></div>`).join("")}
      </div>
      <p class="cap">Not theoretical. This desk was watching when the fee changed, and recorded
        it.</p>`:`<p class="cap">A permanent delegate can move your tokens without asking. A freeze
        authority can stop you selling. These are properties of the mint, read from Solana.</p>`}
    </div>

    <div class="card">
      <h2>If you provide liquidity instead</h2>
      ${pools.length ? `<div class="rows">
        ${pools.slice(0,3).map(p => `
          <div class="row"><span class="k">${esc(p.pool)} at ${(p.base_fee_pct||0).toFixed(2)}%
            in ${p.bin_step} step bins earns</span>
            <span class="v up">${F.pct(p.fee_yield_day,false,3)} a day</span></div>
          <div class="row"><span class="k">but loses to arbitrage</span>
            <span class="v down">${F.pct(p.lvr_day_cpmm,false,4)} a day</span></div>
          <div class="row"><span class="k">so stay wider than</span>
            <span class="v">${p.breakeven_half_width?"±"+(p.breakeven_half_width*100).toFixed(2)+"%":"no width works"}</span></div>
          <div class="row"><span class="k">entry and exit fee paid back in</span>
            <span class="v warn">${p.days_to_recover_entry?p.days_to_recover_entry.toFixed(1)+" days":"—"}</span></div>
        `).join("")}
      </div>
      <p class="cap">Fee income and volatility measured over ${S.lp.window_hours} hourly readings
        this desk took itself. The arbitrage loss is the rate Milionis, Moallemi, Roughgarden and
        Zhang give for a constant product pool, raised for a concentrated position by the closed
        form in the same paper.</p>`
      : `<p class="cap">No pool for this token has enough readings yet.</p>`}
    </div>
  </div>

  <div class="card" style="margin-top:14px">
    <h2>Every token on the board</h2>
    <div class="scroll"><table>
      <colgroup><col style="width:15%"><col style="width:11%"><col style="width:11%"><col style="width:11%">
        <col style="width:13%"><col style="width:13%"><col style="width:13%"><col style="width:13%"></colgroup>
      <thead><tr><th>Token</th><th class="num">Price</th><th class="num">Issuer mark</th>
        <th class="num">Crowd</th><th class="num">Gap</th><th class="num">Liquidity</th>
        <th class="num">Exit $10k</th><th class="num">Fee</th></tr></thead>
      <tbody>${Object.values(S.desk.tokens).map(x => `
        <tr data-pick data-sym="${x.symbol}" class="${x.symbol===S.sym?"on":""}">
          <td>${esc(x.company)}</td>
          <td class="num">${F.usd(x.token_price)}</td>
          <td class="num">${F.usd(x.mark_price)}</td>
          <td class="num">${x.crowd_per_token?F.usd(x.crowd_per_token):"—"}</td>
          <td class="num ${cls(x.gap)}">${x.gap!=null?F.pct(x.gap):"—"}</td>
          <td class="num">${F.big(x.depth?.liquidity)}</td>
          <td class="num warn">${x.round_trip?.[1]?.cost!=null?F.pct(x.round_trip[1].cost,false,2):"—"}</td>
          <td class="num ${x.powers?.transfer_fee_bps?"warn":""}">${
            x.powers?.transfer_fee_bps!=null?(x.powers.transfer_fee_bps/100).toFixed(2)+"%":"—"}</td>
        </tr>`).join("")}</tbody>
    </table></div>
  </div>`;
}

function wireCost(){
  $$("tr[data-sym]").forEach(r => r.onclick = () => openCompany(r.dataset.sym));
}

/* =================================================================== proof == */
function viewProof(){
  const t = S.desk.tokens[S.sym];
  const m = S.chain?.[S.sym];
  const mine = S.live?.tokens?.[S.sym];
  const newer = mine && m ? S.live.read_at - m.published_at : null;

  return `
  <div class="grid g-2">
    <div class="card" id="tour-publish">
      <h2>Refresh the feed yourself</h2>
      <p class="cap" style="padding-bottom:0">The mark on Solana is open. Anyone may republish it,
        and the program records who did. Your browser reads the markets, computes the value here,
        and your key signs it.</p>
      <div class="rows">
        <div class="row"><span class="k">On chain now</span>
          <span class="v">${m?F.big(m.crowd):"nothing yet"}</span></div>
        <div class="row"><span class="k">Published</span>
          <span class="v">${m?F.ago(m.published_at*1000):"—"}</span></div>
        <div class="row"><span class="k">Times refreshed</span>
          <span class="v">${m?.publish_count ?? "—"}</span></div>
        <div class="row"><span class="k">Last publisher</span>
          <span class="v">${m?.last_publisher?F.short(m.last_publisher):"—"}</span></div>
        ${mine?`<div class="row"><span class="k">Your reading, taken just now</span>
          <span class="v up">${F.big(mine.crowd_value)}</span></div>
        <div class="row"><span class="k">Newer than the stored one by</span>
          <span class="v ${newer>0?"up":"down"}">${newer>0?Math.round(newer/60)+" min":"not newer"}</span></div>`:""}
      </div>
      <div class="field">
        <button class="btn" id="readBtn">${mine?"Read the markets again":"1 · Read the markets"}</button>
        <button class="btn key" id="pubBtn" ${S.wallet&&mine&&newer>0?"":"disabled"}>
          ${!S.wallet?"Connect a wallet":mine?(newer>0?"2 · Sign and publish":"Already this fresh"):"Read first"}</button>
      </div>
      <div id="pubOut" class="cap"></div>
    </div>

    <div class="card" id="tour-verify">
      <h2>Check it yourself</h2>
      <p class="cap" style="padding-bottom:0">Your browser derives the account address the way the
        program does, fetches it from Solana, decodes the bytes, and recomputes the hash of the
        inputs to see whether it matches what is stored.</p>
      <div class="field">
        <select id="vSym">${Object.keys(S.desk.tokens).filter(s=>S.desk.tokens[s].covered)
          .map(s=>`<option ${s===S.sym?"selected":""}>${s}</option>`).join("")}</select>
        <button class="btn" id="vRun">Verify</button>
      </div>
      <div id="vOut" class="rows"></div>
    </div>
  </div>

  <div class="grid g-2" style="margin-top:14px">
    <div class="card">
      <h2>What the program refuses</h2>
      <p class="cap" style="padding-bottom:0">The feed is open, so the rules have to be in the
        program rather than in whoever runs it. These are enforced on chain, for every publisher,
        including the keeper.</p>
      <div class="rows">
        <div class="row"><span class="k">A symbol that is not plain capitals</span>
          <span class="v dim">rejected</span></div>
        <div class="row"><span class="k">A probability above one, or a negative price</span>
          <span class="v dim">rejected</span></div>
        <div class="row"><span class="k">A listing value outside the range published with it</span>
          <span class="v dim">rejected</span></div>
        <div class="row"><span class="k">A company name longer than 24 characters</span>
          <span class="v dim">rejected</span></div>
        <div class="row"><span class="k">A reading stamped in the future</span>
          <span class="v dim">rejected beyond 2 minutes</span></div>
        <div class="row"><span class="k">A reading older than an hour</span>
          <span class="v dim">rejected</span></div>
        <div class="row"><span class="k">A reading older than the one already stored</span>
          <span class="v dim">rejected</span></div>
        <div class="row"><span class="k">A mark nobody refreshes</span>
          <span class="v warn">reports itself stale after 6 hours</span></div>
      </div>
      <p class="cap">So a mark cannot be rolled back, cannot be stuffed with an impossible number,
        and cannot quietly go stale without saying so.</p>
    </div>

    <div class="card">
      <h2>The addresses</h2>
      <div class="rows">
        <div class="row"><span class="k">Program</span>
          <span class="v"><a href="https://explorer.solana.com/address/${PROGRAM}?cluster=devnet"
            target="_blank" rel="noopener">${F.short(PROGRAM)}</a></span></div>
        <div class="row"><span class="k">Network</span><span class="v">Solana devnet</span></div>
        <div class="row"><span class="k">Account for each company</span>
          <span class="v dim">derived from its symbol</span></div>
        ${m?.account?`<div class="row"><span class="k">${esc(t.company)}'s account</span>
          <span class="v"><a href="https://explorer.solana.com/address/${m.account}?cluster=devnet"
            target="_blank" rel="noopener">${F.short(m.account)}</a></span></div>`:""}
        <div class="row"><span class="k">Companies with a mark</span>
          <span class="v">${S.chain?Object.keys(S.chain).length:"—"}</span></div>
      </div>
      <p class="cap">Every account address is worked out from the company's symbol, so there is no
        registry to trust and nothing for anyone to point somewhere else. Your browser derives the
        same address the program does, which is what the check on the left is doing.</p>
    </div>
  </div>

  <div class="card" style="margin-top:14px">
    <h2>What a wallet holds</h2>
    <div class="field">
      <input id="addr" placeholder="Paste any Solana address" value="${S.wallet||""}">
      <button class="btn" id="goBtn">Look</button>
    </div>
    <div id="posOut" class="rows"></div>
  </div>`;
}

const VIEWS = {buy: viewBuy, yours: viewYours, why: viewWhy, chain: viewProof};
const WIRE = {buy: wireBuy, yours: wireYours, why: wireLive, chain: wireProof};

/* ==================================================================== tour == */
const TOUR = [
  ["live", "#tour-hero", "The answer, first",
   "This company is private, so it has no share price. The token costs one thing; the people betting real money on its IPO say it is worth another. That difference is the whole product."],
  ["live", "#tour-dist", "Where the number comes from",
   "Each row is a live Polymarket outcome. Your browser is reading these, not us. The valuation above is rebuilt from these bars every time one of them moves."],
  ["live", "#tour-book", "The actual orders",
   "Real resting bids and offers, with the money behind each one. Click any bracket to load its book. This is the proof that the odds above are somebody's position, not an opinion."],
  ["live", "#tour-tape", "Money changing hands",
   "Fills and quote changes, streaming over a websocket. When this ticks, the number at the top of the screen moves with it."],
  ["live", "#tour-news", "Why it moved",
   "Headlines that name this company, from a global news index, so a price move has something to be read against."],
  ["live", "#tour-hist", "The week behind it",
   "Each bracket's own price history, run through the same model, hour by hour. Where the line is above the dashes, the crowd says the token is cheap."],
  ["value", "#main", "The arithmetic, in the open",
   "Every bracket, its odds, its midpoint and what it contributes. Nothing is hidden in a formula: the expected value is the column on the right, added up."],
  ["value", "#main", "And what it would actually pay",
   "An average is one number out of a whole distribution. Sampling the brackets directly shows the middle outcome, which is usually lower, and how often the token lands below what it costs today."],
  ["cost", "#main", "What acting on it would cost",
   "A gap is only worth something if you can reach it. Real round trip quotes, the issuer's transfer fee, what it can do to your balance, and what a liquidity provider earns against what arbitrage takes."],
  ["proof", "#main", "And none of it asks to be believed",
   "The mark sits in a Solana account anyone can refresh and anyone can check. Your browser derives the address, decodes the bytes and recomputes the hash in front of you."],
];
let tourAt = -1;

function startTour(){
  if(S.view !== "live"){ S.view = "live"; render(); }
  tourAt = -1;
  if(!$("#spot")){
    const spot = document.createElement("div");
    spot.className = "spot"; spot.id = "spot";
    const box = document.createElement("div");
    box.className = "tourbox"; box.id = "tourbox";
    document.body.append(spot, box);
  }
  nextTour();
}

function nextTour(){
  tourAt++;
  const step = TOUR[tourAt];
  if(!step){ endTour(); return; }
  const [view, sel, title, body] = step;
  /* Changing screen redraws everything, so the spotlight waits for the new
     layout rather than lighting up where the old panel used to be. */
  const switched = S.view !== view;
  if(switched){ S.view = view; syncHash(); render(); }
  const el = $(sel);
  if(!el){ nextTour(); return; }
  el.scrollIntoView({behavior: "smooth", block: switched ? "start" : "center"});
  setTimeout(() => {
    const r = el.getBoundingClientRect();
    const pad = 8;
    if(!$("#spot")) return;
    $("#spot").style.clipPath =
      `polygon(0 0, 100% 0, 100% 100%, 0 100%, 0 0,
        ${r.left-pad}px ${r.top-pad}px,
        ${r.left-pad}px ${r.bottom+pad}px,
        ${r.right+pad}px ${r.bottom+pad}px,
        ${r.right+pad}px ${r.top-pad}px,
        ${r.left-pad}px ${r.top-pad}px)`;
    const box = $("#tourbox");
    box.innerHTML = `<h3>${esc(title)}</h3><p>${esc(body)}</p>
      <div class="nav"><button class="btn key" id="tNext">
        ${tourAt === TOUR.length-1 ? "Done" : "Next"}</button>
        <button class="btn" id="tEnd">Close</button>
        <span class="step">${tourAt+1} of ${TOUR.length}</span></div>`;
    const below = r.bottom + 190 < window.innerHeight;
    box.style.top = (below ? r.bottom + 14 : Math.max(14, r.top - 180)) + "px";
    box.style.left = Math.min(Math.max(14, r.left), window.innerWidth - 390) + "px";
    $("#tNext").onclick = nextTour;
    $("#tEnd").onclick = endTour;
  }, switched ? 620 : 420);
}

function endTour(){
  $("#spot")?.remove();
  $("#tourbox")?.remove();
  tourAt = -1;
}

/* ================================================================== wallet == */
function providerOf(){
  return window.phantom?.solana?.isPhantom ? window.phantom.solana
    : window.solflare?.isSolflare ? window.solflare : window.solana || null;
}

async function connect(){
  const p = providerOf();
  if(!p){ toast("No Solana wallet found in this browser."); return; }
  try{
    const r = await p.connect();
    S.wallet = (r?.publicKey || p.publicKey).toString();
    $("#connectBtn").textContent = F.short(S.wallet);
    toast("Connected. You can publish to the feed.");
    if(S.view === "proof") render();
  }catch(e){ toast("Connection cancelled"); }
}

function wireProof(){
  $("#readBtn").onclick = async () => {
    const out = $("#pubOut");
    $("#readBtn").disabled = true;
    try{
      const {readLive} = await import("./live.js");
      out.textContent = "Reading every market…";
      S.live = await readLive(S.desk, m => out.textContent = m);
      S.live.at = Date.now();
      render();
      toast(`Read ${Object.keys(S.live.tokens).length} marks from source`);
    }catch(e){
      out.innerHTML = `<span class="down">${esc(e.message||e)}</span>`;
      $("#readBtn").disabled = false;
    }
  };

  $("#pubBtn").onclick = async () => {
    const out = $("#pubOut"), t = S.live?.tokens[S.sym];
    if(!t) return;
    $("#pubBtn").disabled = true;
    try{
      const {publishFromWallet} = await import("./publish.js");
      const {sig, mark} = await publishFromWallet(
        S.sym, t, S.live.read_at, S.live.snapshot_at, providerOf(),
        m => out.textContent = m + "…");
      out.innerHTML = `<b class="up">Published.</b>
        <a href="https://explorer.solana.com/tx/${sig}?cluster=devnet" target="_blank"
           rel="noopener">transaction</a> ·
        <a href="https://explorer.solana.com/address/${mark}?cluster=devnet" target="_blank"
           rel="noopener">the account it changed</a>`;
      toast("Published on devnet");
      loadChain();
    }catch(e){
      out.innerHTML = `<span class="down">${esc(e.message||e)}</span>`;
      $("#pubBtn").disabled = false;
    }
  };

  $("#vRun").onclick = () => verify($("#vSym").value);
  $("#goBtn").onclick = () => position($("#addr").value.trim());
  $("#addr").addEventListener("keydown", e => { if(e.key === "Enter") position(e.target.value.trim()); });
}

/* ==================================================================== boot == */
/* The address bar carries the company and the screen, so any view of this
   terminal can be linked to directly. */
function syncHash(){
  const want = `#${S.sym.toLowerCase()}/${S.view}`;
  if(location.hash !== want) history.replaceState(null, "", want);
}
function readHash(){
  const m = /^#([a-z]+)\/?(buy|yours|why|chain)?$/i.exec(location.hash || "");
  if(!m) return;
  const sym = m[1].toUpperCase();
  if(S.desk.tokens[sym]) S.sym = sym;
  if(m[2]) S.view = m[2];
}

async function boot(){
  try{
    S.desk = await (await fetch("desk.json?" + Date.now())).json();
  }catch(e){
    document.body.innerHTML = `<main style="padding:40px;font-family:system-ui">
      <h1>The desk did not load</h1><p>${esc(e.message)}</p></main>`;
    return;
  }
  readHash();
  render();

  /* Everything below is extra. A failure changes a panel, never the page. */
  fetch("liquidity.json?" + Date.now()).then(r => r.ok ? r.json() : null)
    .then(j => { S.lp = j; if(S.view === "cost") render(); }).catch(() => {});
  fetch("news.json?" + Date.now()).then(r => r.ok ? r.json() : null)
    .then(j => { S.news = j; if(S.view === "why") loadNews(S.sym); }).catch(() => {});

  /* A price is the one figure that must not be old, so the browser refreshes
     it itself rather than serving whatever the snapshot was built with. */
  watchPrices(Object.values(S.desk.tokens).map(t => t.mint), (prices, at) => {
    let moved = false;
    for(const t of Object.values(S.desk.tokens)){
      const px = prices[t.mint];
      if(!px || px === t.token_price) continue;
      t.token_price = px;
      t.token_implied_value = px * t.shares;
      t.premium_to_mark = t.mark_price ? px / t.mark_price - 1 : null;
      if(t.crowd_per_token) t.gap = t.crowd_per_token / px - 1;
      t.price_live = true;
      moved = true;
    }
    S.pricedAt = at;
    if(moved){ repaintRail(); if(S.view !== "live") render(); else repaintDist(); }
    paintAges();
  });

  tape.on("status", s => setState(s.state));
  tape.on("book", () => { if(S.view === "why") paintBook(); });
  tape.on("price", ev => {
    S.ticks++;
    const c = $("#tickCount"); if(c) c.textContent = S.ticks;
    onTick(ev);
  });

  openCompany(S.sym);
  loadChain();

  const p = providerOf();
  if(p?.isConnected && p.publicKey){
    S.wallet = p.publicKey.toString();
    $("#connectBtn").textContent = F.short(S.wallet);
  }
}

/* One quote change: update the bracket it belongs to, repaint only what moved,
   and rebuild the company's valuation from the new set of prices. */
function onTick(ev){
  const m = S.ev?.markets.find(x => x.yesId === ev.asset);
  if(!m) return;
  if(ev.bestBid != null) m.bestBid = ev.bestBid;
  if(ev.bestAsk != null) m.bestAsk = ev.bestAsk;
  const mid = ev.bestBid != null && ev.bestAsk != null
    ? (ev.bestBid + ev.bestAsk)/2 : ev.price;
  const moved = setPrice(m, mid);
  pushTick(ev);
  if(S.view !== "why") return;
  if(m.yesId === S.ev.markets[S.pick]?.yesId) paintBook();
  if(moved) repaintDist();
}

/* Repaint the distribution in place rather than rebuilding it, so rows do not
   jump under the pointer and only the changed figures flash. */
function repaintDist(){
  const ladder = S.desk.tokens[S.sym].kind === "valuation";
  const skip = ladder ? /^\u2193/ : /^no ipo/i;
  const bars = S.ev.markets.filter(m => m.yesId && !skip.test(m.title));
  const total = ladder ? 1 : (bars.reduce((s, m) => s + (m.yes || 0), 0) || 1);
  const top = ladder ? 1 : (Math.max(...bars.map(m => m.yes || 0)) || 1);
  bars.forEach((m, i) => {
    const bar = $(`#b${i} .bar i`), p = $(`#bp${i}`), q = $(`#bq${i}`);
    if(!bar) return;
    bar.style.width = ((m.yes||0)/top*100).toFixed(1) + "%";
    const was = p.textContent, now = F.odds((m.yes||0)/total);
    if(was !== now){
      p.textContent = now;
      p.classList.remove("fl-up","fl-dn");
      void p.offsetWidth;                       // restart the animation
      p.classList.add(parseFloat(now) > parseFloat(was) ? "fl-up" : "fl-dn");
    }
    q.textContent = `${F.cents(m.bestBid)} / ${F.cents(m.bestAsk)}`;
  });

  const card = liveCard();
  if(!card?.crowd_per_token) return;
  const t = S.desk.tokens[S.sym];
  const gap = card.crowd_per_token / t.token_price - 1;
  const hc = $("#heroCrowd"), hg = $("#heroGap");
  if(hc){
    const now = F.usd(card.crowd_per_token);
    if(hc.textContent !== now){
      hc.classList.remove("fl-up","fl-dn"); void hc.offsetWidth;
      hc.classList.add(now > hc.textContent ? "fl-up" : "fl-dn");
      hc.textContent = now;
    }
    hc.className = hc.className.replace(/\b(up|down)\b/g, "") + " " + cls(gap);
    hg.textContent = F.pct(gap, true, 1);
    hg.className = "v " + cls(gap);
  }
}

document.addEventListener("DOMContentLoaded", boot);

/* The chain read, the verifier and the wallet view live in chain.js, which is
   loaded on demand so the live screen is not waiting on it. */
async function loadChain(){
  try{
    const {readMarks} = await import("./chain.js");
    S.chain = await readMarks(Object.keys(S.desk.tokens).filter(s => S.desk.tokens[s].covered));
    if(S.view === "proof") render();
  }catch(e){ /* the proof screen says so */ }
}
async function verify(sym){
  const {verifyMark} = await import("./chain.js");
  verifyMark(sym, S, $("#vOut"), F, esc);
}
async function position(addr){
  const {showPosition} = await import("./chain.js");
  showPosition(addr, S, $("#posOut"), F, esc);
}
