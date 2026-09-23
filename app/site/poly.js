/* The live wire to Polymarket.

   The valuation on this terminal is only worth something if you can see the
   bets it is made of. So nothing here is precomputed: the order books, the
   fills and the prices are read from Polymarket by the visitor's own browser,
   and the book keeps streaming afterwards.

   Four public endpoints, all of which allow browser requests directly, so
   there is no server in between that could be editing anything.

     gamma      the markets, their brackets, volume and last trade
     clob       the order book and the price history
     data-api   every fill, with the wallet that made it
     websocket  the book as it changes, pushed rather than polled
*/
const GAMMA = "https://gamma-api.polymarket.com";
const CLOB = "https://clob.polymarket.com";
const DATA = "https://data-api.polymarket.com";
const WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market";

async function json(url, opts){
  const r = await fetch(url, {cache: "no-store", ...opts});
  if(!r.ok) throw new Error(`${new URL(url).hostname} answered ${r.status}`);
  return r.json();
}

/* One event, with its brackets already unpacked.

   Polymarket ships a few fields as JSON inside strings, so they are parsed
   here once rather than at every place that reads them. */
export async function loadEvent(slug){
  const body = await json(`${GAMMA}/events?slug=${encodeURIComponent(slug)}`);
  if(!Array.isArray(body) || !body.length) throw new Error(`no market called ${slug}`);
  const ev = body[0];
  ev.markets = (ev.markets || []).map(m => {
    let prices = m.outcomePrices, ids = m.clobTokenIds;
    try{ if(typeof prices === "string") prices = JSON.parse(prices); }catch(e){ prices = null; }
    try{ if(typeof ids === "string") ids = JSON.parse(ids); }catch(e){ ids = null; }
    return {
      ...m,
      title: (m.groupItemTitle || "").trim(),
      yes: prices ? parseFloat(prices[0]) : null,
      yesId: ids ? ids[0] : null,
      noId: ids ? ids[1] : null,
      bestBid: m.bestBid != null ? parseFloat(m.bestBid) : null,
      bestAsk: m.bestAsk != null ? parseFloat(m.bestAsk) : null,
      spread: m.spread != null ? parseFloat(m.spread) : null,
      lastTrade: m.lastTradePrice != null ? parseFloat(m.lastTradePrice) : null,
      hourChange: m.oneHourPriceChange != null ? parseFloat(m.oneHourPriceChange) : null,
      dayChange: m.oneDayPriceChange != null ? parseFloat(m.oneDayPriceChange) : null,
      volume24: m.volume24hr != null ? parseFloat(m.volume24hr) : null,
      liquidity: m.liquidityNum != null ? parseFloat(m.liquidityNum) : null,
    };
  });
  return ev;
}

/* The resting orders on one side of one bracket, best price first. */
export async function loadBook(tokenId){
  const b = await json(`${CLOB}/book?token_id=${tokenId}`);
  const side = rows => (rows || [])
    .map(r => ({price: parseFloat(r.price), size: parseFloat(r.size)}))
    .filter(r => r.price > 0 && r.size > 0);
  const bids = side(b.bids).sort((x, y) => y.price - x.price);
  const asks = side(b.asks).sort((x, y) => x.price - y.price);
  return {bids, asks, tokenId,
          bestBid: bids[0]?.price ?? null, bestAsk: asks[0]?.price ?? null};
}

/* Recent fills on a market. Each one is somebody's money, with the wallet
   that spent it, which is the point of showing them. */
export async function loadTrades(conditionId, limit = 30){
  const rows = await json(`${DATA}/trades?market=${conditionId}&limit=${limit}`);
  return (rows || []).map(t => ({
    wallet: t.proxyWallet, side: t.side,
    price: parseFloat(t.price), size: parseFloat(t.size),
    outcome: t.outcome, at: t.timestamp * 1000, asset: t.asset,
    title: t.title || "", slug: t.slug || "",
  })).sort((a, b) => b.at - a.at);
}

/* What this bracket has traded at, over time. */
export async function loadHistory(tokenId, interval = "1w", fidelity = 60){
  const h = await json(`${CLOB}/prices-history?market=${tokenId}&interval=${interval}&fidelity=${fidelity}`);
  return (h.history || []).map(p => ({t: p.t * 1000, p: p.p}));
}

/* Who is holding this bracket, largest first. */
export async function loadHolders(conditionId, limit = 10){
  const rows = await json(`${DATA}/holders?market=${conditionId}&limit=${limit}`);
  const first = Array.isArray(rows) ? rows[0] : rows;
  return (first?.holders || []).map(h => ({
    wallet: h.proxyWallet, name: h.name || h.pseudonym || null,
    amount: parseFloat(h.amount), outcome: h.outcomeIndex,
  }));
}

/* Open markets that mention a company.

   Used where this terminal has no valuation to offer. Saying only "no market"
   leaves the reader wondering whether anyone looked, so the markets that do
   exist are listed and the reader can see for themselves that none of them
   asks what the company is worth.
*/
export async function searchMarkets(name, limit = 8){
  const r = await json(`${GAMMA}/public-search?q=${encodeURIComponent(name)}&limit_per_type=20`);
  return ((r && r.events) || [])
    .filter(e => !e.closed && !e.archived)
    .map(e => ({title: e.title, slug: e.slug, volume: parseFloat(e.volume) || 0}))
    .sort((a, b) => b.volume - a.volume)
    .slice(0, limit);
}

/* ------------------------------------------------------------------ stream */

/* The order book as it changes, pushed by Polymarket.

   Reconnects with a widening delay, because a terminal that goes quiet and
   stays quiet is worse than one that says it is reconnecting. Every message
   is handed on with the bracket it belongs to already resolved, so the view
   never has to know about asset ids.
*/
export class Tape {
  constructor(){
    this.ws = null;
    this.assets = [];
    this.handlers = {book: [], price: [], status: []};
    this.books = new Map();          // asset id -> {bids, asks}
    this.retry = 0;
    this.closed = false;
    this.keepalive = null;
  }

  on(what, fn){ this.handlers[what].push(fn); return this; }
  emit(what, payload){ this.handlers[what].forEach(fn => { try{ fn(payload); }catch(e){} }); }

  /* Watch this set of brackets. Called again with a new set when the visitor
     switches company, which reopens the socket rather than piling up. */
  watch(assetIds){
    this.assets = assetIds.filter(Boolean);
    this.books.clear();
    this.reopen();
  }

  reopen(){
    if(this.ws){ try{ this.ws.onclose = null; this.ws.close(); }catch(e){} }
    if(!this.assets.length) return;
    this.emit("status", {state: "connecting"});
    let ws;
    try{ ws = new WebSocket(WS); }
    catch(e){ return this.later(); }
    this.ws = ws;

    ws.onopen = () => {
      this.retry = 0;
      ws.send(JSON.stringify({assets_ids: this.assets, type: "market"}));
      this.emit("status", {state: "live"});
      /* Polymarket drops a socket that says nothing. */
      clearInterval(this.keepalive);
      this.keepalive = setInterval(() => {
        if(ws.readyState === 1) ws.send("PING");
      }, 10000);
    };

    ws.onmessage = e => {
      if(!e.data || e.data === "PONG") return;
      let msgs;
      try{ msgs = JSON.parse(e.data); }catch(err){ return; }
      if(!Array.isArray(msgs)) msgs = [msgs];
      for(const m of msgs) this.handle(m);
    };

    ws.onclose = () => { clearInterval(this.keepalive); if(!this.closed) this.later(); };
    ws.onerror = () => { try{ ws.close(); }catch(e){} };
  }

  later(){
    this.retry = Math.min(this.retry + 1, 6);
    const wait = 500 * 2 ** this.retry;
    this.emit("status", {state: "reconnecting", in: wait});
    setTimeout(() => { if(!this.closed) this.reopen(); }, wait);
  }

  handle(m){
    if(m.event_type === "book"){
      const book = {
        bids: (m.bids || []).map(r => ({price: +r.price, size: +r.size}))
                .sort((a, b) => b.price - a.price),
        asks: (m.asks || []).map(r => ({price: +r.price, size: +r.size}))
                .sort((a, b) => a.price - b.price),
      };
      this.books.set(m.asset_id, book);
      this.emit("book", {asset: m.asset_id, book});
    }
    else if(m.event_type === "price_change"){
      for(const c of (m.price_changes || [])){
        this.apply(c);
        this.emit("price", {
          asset: c.asset_id, price: +c.price, size: +c.size, side: c.side,
          bestBid: c.best_bid != null ? +c.best_bid : null,
          bestAsk: c.best_ask != null ? +c.best_ask : null,
          at: Date.now(),
        });
      }
    }
    else if(m.event_type === "last_trade_price"){
      this.emit("price", {asset: m.asset_id, price: +m.price, size: +m.size,
                          side: m.side, trade: true, at: Date.now()});
    }
  }

  /* Keep the local book in step with the changes coming down the wire, so the
     depth ladder does not need a fresh snapshot on every tick. */
  apply(c){
    const book = this.books.get(c.asset_id);
    if(!book) return;
    const rows = c.side === "BUY" ? book.bids : book.asks;
    const price = +c.price, size = +c.size;
    const i = rows.findIndex(r => r.price === price);
    if(size === 0){ if(i >= 0) rows.splice(i, 1); }
    else if(i >= 0) rows[i].size = size;
    else {
      rows.push({price, size});
      rows.sort((a, b) => c.side === "BUY" ? b.price - a.price : a.price - b.price);
    }
  }

  close(){ this.closed = true; clearInterval(this.keepalive);
           try{ this.ws?.close(); }catch(e){} }
}
