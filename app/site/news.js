/* Headlines about the companies these markets price.

   A number that moves should be explainable. When Anthropic's bracket
   reprices, the reason is usually in the news that day, so the terminal puts
   the two beside each other and lets the reader judge.

   Articles come from GDELT, which indexes news worldwide and answers browser
   requests directly. It asks for no more than one query every five seconds, so
   queries are queued and spaced, and answers are kept for a while rather than
   asked for again.

   Nothing here is summarised or rewritten. A headline, its publisher and its
   time, linking out to the original.
*/
const GDELT = "https://api.gdeltproject.org/api/v2/doc/doc";
const GAP_MS = 6000;          // their limit is one every five seconds
const TRIES = 3;              // a busy answer is retried, not surfaced as an error
const KEEP_MS = 10 * 60_000;  // an answer stays good for ten minutes

/* Narrow the query to the company as a business story, otherwise a search for
   Anthropic returns every article that mentions artificial intelligence. */
const QUERY = {
  ANTHROPIC: '"Anthropic" (IPO OR valuation OR funding OR "public offering")',
  OPENAI: '"OpenAI" (IPO OR valuation OR funding OR "public offering")',
  ANDURIL: '"Anduril" (valuation OR funding OR contract OR IPO)',
  NEURALINK: '"Neuralink" (valuation OR funding OR trial OR IPO)',
  SPACEX: '"SpaceX" (valuation OR funding OR IPO OR Starlink)',
  POLYMARKET: '"Polymarket" (valuation OR funding OR regulation)',
  FIGUREAI: '"Figure AI" (valuation OR funding OR robot)',
  XAI: '"xAI" (valuation OR funding OR Grok)',
};

/* The name a headline has to carry for the story to be about this company. */
const NAME = {
  ANTHROPIC: "Anthropic", OPENAI: "OpenAI", ANDURIL: "Anduril",
  NEURALINK: "Neuralink", SPACEX: "SpaceX", POLYMARKET: "Polymarket",
  FIGUREAI: "Figure", XAI: "xAI",
};

const cache = new Map();      // symbol -> {at, articles}
let queue = Promise.resolve(), lastCall = 0;

/* One at a time, never faster than their limit allows. */
function spaced(fn){
  queue = queue.then(async () => {
    const wait = Math.max(0, GAP_MS - (Date.now() - lastCall));
    if(wait) await new Promise(r => setTimeout(r, wait));
    lastCall = Date.now();
    return fn();
  }).catch(() => null);
  return queue;
}

function tidy(articles, name){
  const seen = new Set();
  const named = new RegExp(name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i");
  return (articles || []).filter(a => {
    /* GDELT returns the same story from every site that syndicated it, so one
       per headline. And an article that merely mentions the company somewhere
       is not news about it: the headline has to name it. */
    const key = (a.title || "").slice(0, 60).toLowerCase();
    if(!a.title || !a.url || seen.has(key) || !named.test(a.title)) return false;
    seen.add(key);
    return true;
  }).map(a => ({
    title: a.title.replace(/\s+/g, " ").trim(),
    url: a.url,
    domain: a.domain,
    image: a.socialimage || null,
    at: parse(a.seendate),
  })).sort((x, y) => y.at - x.at);
}

/* GDELT stamps articles as 20260922T233000Z. */
function parse(s){
  if(!s || s.length < 15) return Date.now();
  const iso = `${s.slice(0,4)}-${s.slice(4,6)}-${s.slice(6,8)}T` +
              `${s.slice(9,11)}:${s.slice(11,13)}:${s.slice(13,15)}Z`;
  const t = Date.parse(iso);
  return isNaN(t) ? Date.now() : t;
}

export async function headlines(symbol, max = 8){
  const q = QUERY[symbol];
  if(!q) return [];
  const hit = cache.get(symbol);
  if(hit && Date.now() - hit.at < KEEP_MS) return hit.articles.slice(0, max);

  const name = NAME[symbol] || symbol;
  const articles = await spaced(async () => {
    const url = `${GDELT}?query=${encodeURIComponent(q)}&mode=artlist` +
                `&maxrecords=60&format=json&sort=datedesc&timespan=7d`;
    /* Their limit is per address, so a visitor who opens several companies at
       once can be turned away. That is a wait, not a failure. */
    for(let attempt = 0; attempt < TRIES; attempt++){
      const r = await fetch(url, {cache: "no-store"});
      const text = r.ok ? await r.text() : "";
      if(text.trim().startsWith("{")) return tidy(JSON.parse(text).articles, name);
      await new Promise(res => setTimeout(res, GAP_MS * (attempt + 1)));
    }
    throw new Error("news service stayed busy");
  });

  if(!articles) return hit ? hit.articles.slice(0, max) : [];
  cache.set(symbol, {at: Date.now(), articles});
  return articles.slice(0, max);
}
