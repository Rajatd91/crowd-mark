/* Token prices, read live in the browser.

   The page ships a snapshot so it has something to draw at once, but a price is
   the one thing that must never be old: the whole terminal is a comparison
   between what a token costs and what the crowd says it is worth, and a stale
   price makes that comparison wrong rather than merely late. One reading of
   this showed a token 12 percent away from the figure the page was shipping.

   Jupiter quotes these mints and allows browser requests, so the terminal asks
   it directly and keeps asking. Anything that cannot be fetched this way stays
   on the snapshot and is labelled with its age, rather than being passed off as
   current.
*/
const JUP = "https://lite-api.jup.ag/price/v3?ids=";
const EVERY_MS = 45_000;

/* Ask Jupiter for every mint at once, and report only what it actually quoted.
   A mint it does not know keeps the snapshot price rather than becoming zero. */
export async function readPrices(mints){
  const r = await fetch(JUP + mints.join(","), {cache: "no-store"});
  if(!r.ok) throw new Error(`Jupiter answered ${r.status}`);
  const body = await r.json();
  const out = {};
  for(const mint of mints){
    const px = body?.[mint]?.usdPrice;
    if(typeof px === "number" && px > 0) out[mint] = px;
  }
  return out;
}

/* Keep asking, and hand each answer back. Stops nothing on a failure: a missed
   reading just leaves the last good one in place, with its age still shown. */
export function watchPrices(mints, onPrices){
  let stop = false;
  const tick = async () => {
    if(stop) return;
    try{ onPrices(await readPrices(mints), Date.now()); }
    catch(e){ /* the age indicator tells the reader it did not refresh */ }
    if(!stop) setTimeout(tick, EVERY_MS);
  };
  tick();
  return () => { stop = true; };
}
