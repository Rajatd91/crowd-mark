/* Call every live endpoint the terminal depends on, and say what came back.

   The page reads Polymarket from the visitor's browser, so if one of those
   endpoints changes shape or stops allowing browser requests, the terminal
   goes quiet and nothing else would tell us. This calls each one for real.

   Run with: node conformance_poly.mjs
*/
import {loadEvent, loadBook, loadTrades, loadHistory, loadHolders} from "./site/poly.js";
import {headlines} from "./site/news.js";

const SLUG = "anthropic-ipo-closing-market-cap-higher-strikes";
let failed = 0;

async function step(label, fn){
  try{
    const out = await fn();
    console.log(`  ${label.padEnd(30)} ok    ${out}`);
  }catch(e){
    failed++;
    console.log(`  ${label.padEnd(30)} FAILED ${e.message}`);
  }
}

const ev = await loadEvent(SLUG);
const live = ev.markets.filter(m => m.yesId);
const m = live.find(x => x.yes > 0.02 && x.yes < 0.98) || live[0];

await step("event and its brackets", async () =>
  `${ev.markets.length} brackets, ${live.filter(x => x.bestBid != null).length} quoting`);
await step("best bid and ask", async () => {
  if(m.bestBid == null || m.bestAsk == null) throw new Error("no quote on " + m.title);
  return `${m.title} ${m.bestBid} / ${m.bestAsk}, spread ${m.spread}`;
});
await step("order book", async () => {
  const b = await loadBook(m.yesId);
  if(!b.bids.length && !b.asks.length) throw new Error("empty book");
  const depth = b.bids.reduce((s, r) => s + r.price * r.size, 0);
  return `${b.bids.length} bids, ${b.asks.length} asks, $${depth.toFixed(0)} resting on the bid`;
});
await step("recent fills", async () => {
  const t = await loadTrades(m.conditionId, 20);
  if(!t.length) throw new Error("no fills returned");
  const age = (Date.now() - t[0].at) / 60000;
  return `${t.length} fills, newest ${age.toFixed(0)} min old, ${t[0].side} ${t[0].size} at ${t[0].price}`;
});
await step("price history", async () => {
  const h = await loadHistory(m.yesId, "1w", 60);
  if(h.length < 5) throw new Error(`only ${h.length} points`);
  return `${h.length} points, ${h[0].p} then, ${h[h.length-1].p} now`;
});
await step("holders", async () => {
  const h = await loadHolders(m.conditionId, 10);
  return h.length ? `${h.length} listed, largest ${h[0].amount.toFixed(0)}` : "none listed";
});
await step("headlines", async () => {
  const n = await headlines("ANTHROPIC", 5);
  if(!n.length) throw new Error("no articles");
  const age = (Date.now() - n[0].at) / 3600000;
  return `${n.length} articles, newest ${age.toFixed(1)} h old, ${n[0].domain}`;
});

console.log(failed ? `FAILED, ${failed} endpoints are not usable`
                   : "every live endpoint answered the browser");
process.exit(failed ? 1 : 0);
