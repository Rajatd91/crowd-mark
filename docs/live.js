/* Read the prediction markets from the visitor's own browser.

   The page ships a snapshot so it has something to show instantly, but a
   snapshot is somebody else's reading. This fetches the same markets live, from
   here, and recomputes the mark with the model in model.js. That is what makes
   a publish meaningful: the reading is the visitor's own and is newer than
   whatever the chain already holds.

   Two inputs cannot be fetched this way. The issuer's mark price and the share
   count it implies come from prestocks.com, which does not allow browser
   requests, so they are carried in the snapshot and are labelled as snapshot
   figures wherever they appear. Everything the valuation actually turns on, the
   crowd's own distribution, is read here and now.
*/
import {buildCard} from "./model.js";

const EVENT = "https://gamma-api.polymarket.com/events?slug=";

async function fetchEvent(slug){
  const r = await fetch(EVENT + encodeURIComponent(slug), {cache: "no-store"});
  if(!r.ok) throw new Error(`Polymarket refused ${slug} with ${r.status}`);
  const body = await r.json();
  if(!Array.isArray(body) || !body.length) throw new Error(`Polymarket has no event ${slug}`);
  return body[0];
}

/* Every slug the covered tokens name, fetched once each even when shared. */
function slugsOf(desk){
  const slugs = new Set();
  for(const t of Object.values(desk.tokens)){
    for(const slug of Object.values(t.sources || {})) if(slug) slugs.add(slug);
  }
  return [...slugs];
}

/* Recompute every covered token from markets read just now.

   onStep reports progress so the page can show what it is doing rather than
   freezing. A market that fails to answer is reported and its token is left
   out: publishing a mark with a market missing would silently change what the
   number means.
*/
export async function readLive(desk, onStep){
  const slugs = slugsOf(desk);
  const polymarket = {}, failed = [];
  let done = 0;
  await Promise.all(slugs.map(async slug => {
    try{ polymarket[slug] = await fetchEvent(slug); }
    catch(e){ failed.push(`${slug}: ${e.message}`); }
    onStep?.(`Read ${++done} of ${slugs.length} markets`);
  }));

  const tokens = {};
  for(const [symbol, t] of Object.entries(desk.tokens)){
    if(!t.covered) continue;
    const needed = Object.values(t.sources || {}).filter(Boolean);
    if(!needed.some(s => polymarket[s])) continue;   // nothing of this one answered
    const card = buildCard(polymarket, symbol, {
      company: t.company, kind: t.kind, polymarket: t.sources,
    }, {token_price: t.token_price, mark_price: t.mark_price, shares: t.shares});
    if(t.kind === "ipo" && !card.crowd_per_token) continue;   // no value to publish
    tokens[symbol] = card;
  }

  return {
    read_at: Math.floor(Date.now() / 1000),   // the visitor's own reading time
    snapshot_at: Math.floor(Date.parse(desk.read_at) / 1000),
    tokens, failed,
  };
}

/* What changed between the shipped snapshot and the live reading.

   Shown before anything is signed, so the visitor publishes a number they have
   seen rather than one the page asserts.
*/
export function differences(desk, live){
  const rows = [];
  for(const [symbol, now] of Object.entries(live.tokens)){
    const was = desk.tokens[symbol];
    rows.push({
      symbol,
      field: "crowd value",
      was: was.crowd_value, now: now.crowd_value,
      moved: was.crowd_value ? now.crowd_value / was.crowd_value - 1 : null,
      source_was: was.cap_source, source_now: now.cap_source,
    });
  }
  return rows;
}
