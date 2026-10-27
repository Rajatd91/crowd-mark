/* Reading the markets.

   The visitor's own browser asks Polymarket for the current prices, so the
   numbers on the page are never older than the page load. If Polymarket
   cannot be reached, the page falls back to a stored snapshot and says how
   old it is, rather than showing stale numbers as if they were live.
*/
const GAMMA = "https://gamma-api.polymarket.com";

const num = v => (v == null || v === "" || !isFinite(+v)) ? null : +v;

/* Polymarket ships some fields as JSON inside strings. Unpack once, here. */
export function normalizeEvent(raw){
  const markets = (raw.markets || []).map(m => {
    let prices = m.outcomePrices;
    try{ if(typeof prices === "string") prices = JSON.parse(prices); }catch(e){ prices = null; }
    return {
      title: (m.groupItemTitle || m.question || "").trim(),
      question: m.question || "",
      slug: m.slug || "",
      yes: prices ? num(prices[0]) : null,
      closed: !!m.closed,
      dayChange: num(m.oneDayPriceChange),
      weekChange: num(m.oneWeekPriceChange),
      volume: num(m.volumeNum ?? m.volume),
      liquidity: num(m.liquidityNum ?? m.liquidity),
    };
  });
  return {
    slug: raw.slug, title: raw.title || raw.slug,
    volume: num(raw.volume), liquidity: num(raw.liquidity),
    endDate: raw.endDate || null, closed: !!raw.closed,
    image: raw.image || raw.icon || null,
    markets,
  };
}

async function getJson(url, timeout = 9000){
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeout);
  try{
    const r = await fetch(url, {cache: "no-store", signal: ctl.signal});
    if(!r.ok) throw new Error(`${r.status}`);
    return await r.json();
  } finally { clearTimeout(timer); }
}

export async function fetchEvent(slug){
  const body = await getJson(`${GAMMA}/events?slug=${encodeURIComponent(slug)}`);
  if(!Array.isArray(body) || !body.length) throw new Error(`no event ${slug}`);
  return normalizeEvent(body[0]);
}

let snapshotPromise = null;
export function loadSnapshot(){
  if(!snapshotPromise){
    snapshotPromise = fetch("snapshot.json", {cache: "no-cache"})
      .then(r => r.ok ? r.json() : {events: {}, as_of: null})
      .catch(() => ({events: {}, as_of: null}));
  }
  return snapshotPromise;
}

/* Every slug, live where possible. Reports where each number came from. */
export async function loadEvents(slugs){
  const snap = await loadSnapshot();
  const events = {}, from = {};
  await Promise.all(slugs.map(async slug => {
    try{
      events[slug] = await fetchEvent(slug);
      from[slug] = "live";
    }catch(e){
      if(snap.events[slug]){ events[slug] = snap.events[slug]; from[slug] = "snapshot"; }
      else from[slug] = "missing";
    }
  }));
  const kinds = new Set(Object.values(from).filter(k => k !== "missing"));
  const source = kinds.size === 0 ? "none" : kinds.size > 1 ? "mixed" : [...kinds][0];
  return {events, from, source, asOf: snap.as_of};
}

/* Open events that mention a name, with their markets, newest money first. */
export async function searchEvents(query, limit = 6){
  const r = await getJson(`${GAMMA}/public-search?q=${encodeURIComponent(query)}&limit_per_type=20`);
  const hits = ((r && r.events) || [])
    .filter(e => !e.closed && !e.archived)
    .sort((a, b) => (+b.volume || 0) - (+a.volume || 0))
    .slice(0, limit);
  const full = await Promise.all(hits.map(h =>
    h.markets && h.markets.length ? normalizeEvent(h) : fetchEvent(h.slug).catch(() => null)));
  return full.filter(Boolean);
}

export const polymarketUrl = slug => `https://polymarket.com/event/${encodeURIComponent(slug)}`;
