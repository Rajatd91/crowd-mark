/* Render the terminal with no browser, in every state, and fail if it throws.

   The point is not that the markup is pretty. It is that a value which arrives
   missing, or a company with no market, or a wallet that is not connected, can
   never leave a blank screen or print the word undefined where a number should
   be. That is what happened before, and only a test catches it every time.

   Run with: node conformance_terminal.mjs
*/
import {readFileSync} from "fs";
import {webcrypto} from "crypto";
import vm from "vm";

const desk = JSON.parse(readFileSync("site/desk.json", "utf8"));
const chain = JSON.parse(readFileSync("site/onchain.json", "utf8"));
const lp = JSON.parse(readFileSync("site/liquidity.json", "utf8"));
let news = {by_symbol: {}, read_at: Math.floor(Date.now()/1000)};
try{ news = JSON.parse(readFileSync("site/news.json", "utf8")); }catch(e){}
const watch = JSON.parse(readFileSync("site/watch.json", "utf8"));

/* terminal.js is a module and imports others, so it is loaded as one, with a
   DOM thin enough to render into and rich enough not to lie about it. */
const el = () => new Proxy({
  style: {}, dataset: {}, classList: {add(){}, remove(){}, toggle(){}, contains: () => false},
  children: [], firstElementChild: null, lastElementChild: null,
  append(){}, prepend(){}, remove(){}, scrollIntoView(){},
  setAttribute(){}, getBoundingClientRect: () => ({top:0,left:0,right:100,bottom:100}),
  addEventListener(){}, textContent: "", innerHTML: "", value: "",
}, {
  get: (t, k) => k in t ? t[k] : (typeof k === "string" ? el() : undefined),
  set: (t, k, v) => (t[k] = v, true),
});

const sandbox = {
  document: {querySelector: () => el(), querySelectorAll: () => [],
             addEventListener(){}, createElement: () => el(), body: el()},
  window: {addEventListener(){}, innerWidth: 1400, innerHeight: 900},
  crypto: webcrypto, fetch: async () => { throw new Error("offline in this test"); },
  atob: s => Buffer.from(s, "base64").toString("binary"),
  setTimeout, clearTimeout, setInterval, clearInterval, console,
  TextEncoder, TextDecoder, DataView, URL, WebSocket: class { close(){} },
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

/* Pull the view functions out of the module without running its boot. */
const src = readFileSync("site/terminal.js", "utf8")
  .replace(/^import .*$/gm, "")
  .replace('document.addEventListener("DOMContentLoaded", boot);', "")
  + "\n;globalThis.__probe = {VIEWS, S, F};";
const model = readFileSync("site/model.js", "utf8").replace(/^export /gm, "");
const poly = "class FakeTape { constructor(){ this.books = new Map(); } on(){ return this; } watch(){} }\nconst P = {Tape: FakeTape};";
const news_ = "const headlines = async () => [];\nconst PROGRAM = '6jsqLJjNynJWc2g1kRNi65wiTCkoUkQ8V3p7MUiBgGgU';";
vm.runInContext(model + "\nconst M = {buildCard, capBrackets, expectedCap};\n" + poly +
                "\n" + news_ + "\n" + src, sandbox, {filename: "terminal.js"});

const {VIEWS, S} = sandbox.__probe;
S.desk = desk;
S.chain = Object.fromEntries(Object.entries(chain).filter(([k]) => k !== "_meta"));
S.lp = lp; S.news = news;
if(!desk.disclosures) throw new Error("desk.json carries no disclosures, the buy screen needs them");

/* A stand-in for a market that has loaded, built from the shipped snapshot so
   the shapes are real rather than invented. */
function fakeEvent(sym){
  const t = desk.tokens[sym];
  if(!t.covered || !(t.brackets || []).length) return null;
  return {
    slug: t.cap_source, title: t.company + " IPO valuation",
    markets: t.brackets.map((b, i) => ({
      title: `$${(b.low/1e12).toFixed(2)}–$${(b.high/1e12).toFixed(2)}T`,
      yes: b.p, yesId: "tok" + i, conditionId: "0xabc" + i,
      outcomePrices: [String(b.p), String(1 - b.p)],
      bestBid: Math.max(0.001, b.p - 0.01), bestAsk: b.p + 0.01,
      spread: 0.02, hourChange: i % 2 ? 0.004 : -0.003,
      volume24: 1000 * (i + 1), liquidity: 5000,
    })),
  };
}

const VIEWNAMES = ["watch", "buy", "yours", "why", "chain", "api", "limits"];
let failures = 0, done = 0;

for(const sym of Object.keys(desk.tokens)){
  S.sym = sym;
  for(const withEvent of [false, true]){
    S.ev = withEvent ? fakeEvent(sym) : null;
    S.pick = 0;
    for(const wallet of [null, "2sujbbTjp2r5ugbjfHgUNDSwtdVfYpTiCSKPgT84CvD7"]){
      S.wallet = wallet;
      for(const withLive of [false, true]){
        S.live = withLive ? {read_at: Math.floor(Date.now()/1000),
          snapshot_at: Math.floor(Date.parse(desk.read_at)/1000),
          tokens: Object.fromEntries(Object.entries(desk.tokens)
            .filter(([, t]) => t.covered))} : null;
        for(const withLp of [true, false]){
          S.lp = withLp ? lp : null;
          /* Before the mint state arrives and after, since watch is the first
             screen a visitor sees and it must not be blank either way. */
          S.watch = withLp ? watch : null;
          /* Before a quote comes back and after, since the buy button and the
             figures beside it both depend on one. */
          /* With a slippage figure and without, since a quote taken before
             that field existed must still render. */
          S.quote = withLp ? null : {dollars: 100, tokens: 0.0956,
            perToken: 1046.02, impact: 0.0003, route: ["Kipseli"], raw: {},
            slippageBps: wallet ? 250 : undefined};
          for(const view of VIEWNAMES){
            S.view = view;
            try{
              const html = VIEWS[view]();
              if(typeof html !== "string" || html.length < 60)
                throw new Error("rendered almost nothing");
              for(const bad of ["undefined", "NaN", "[object Object]", "$null"])
                if(html.includes(bad)) throw new Error(`printed ${bad}`);
              done++;
            }catch(e){
              failures++;
              console.log(`  ${view}/${sym}/${withEvent?"market":"no market"}/` +
                          `${wallet?"wallet":"no wallet"}/${withLive?"read":"unread"}/` +
                          `${withLp?"lp":"no lp"}: ${e.message}`);
            }
          }
        }
      }
    }
  }
}
console.log(failures ? `FAILED, ${failures} of ${done + failures} renders threw`
                     : `every screen renders, ${done} combinations checked`);
process.exit(failures ? 1 : 0);
