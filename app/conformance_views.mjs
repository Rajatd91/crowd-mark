/* Render every view, with no browser, and fail if any of them throws.

   The page once looked broken for a reason that had nothing to do with the
   markup: one view threw while building its HTML and the terminal stayed
   empty. This runs each view function over the real desk.json and the real
   decoded accounts, so that failure cannot reach the site unnoticed.

   Run with: node conformance_views.mjs
*/
import {readFileSync} from "fs";
import {webcrypto} from "crypto";
import vm from "vm";

const desk = JSON.parse(readFileSync("site/desk.json", "utf8"));
const chain = JSON.parse(readFileSync("site/onchain.json", "utf8"));
const lp = JSON.parse(readFileSync("site/liquidity.json", "utf8"));

/* Just enough of a browser for the view functions: they read from the DOM to
   find their controls, and the wiring is exercised separately. */
const element = () => new Proxy({style: {}, classList: {add(){}, remove(){}}, dataset: {}}, {
  get: (t, k) => k in t ? t[k] : (typeof k === "string" ? element() : undefined),
  set: (t, k, v) => (t[k] = v, true),
});
const sandbox = {
  document: {querySelector: () => element(), querySelectorAll: () => [],
             addEventListener(){}, body: element()},
  window: {addEventListener(){}},
  fetch: async () => ({ok: true, json: async () => ({})}),
  crypto: webcrypto,
  atob: s => Buffer.from(s, "base64").toString("binary"),
  setTimeout, clearTimeout, console, TextEncoder, TextDecoder, DataView, Date, Math, JSON,
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(readFileSync("site/desk.js", "utf8"), sandbox, {filename: "desk.js"});

/* The page's own state, as it is after a successful boot. These are `let`
   bindings inside the script, not properties of the global object, so they are
   set by running an assignment in the same context rather than by poking the
   sandbox. */
sandbox.__desk = desk;
sandbox.__chain = Object.fromEntries(Object.entries(chain).filter(([k]) => k !== "_meta"));
const setState = expr => vm.runInContext(expr, sandbox);
sandbox.__lp = lp;
setState("DESK = __desk; CHAIN = __chain; LP = __lp;");

const VIEWS = ["board", "valuation", "payoff", "execution", "liquidity", "issuer",
               "position", "publish", "verify"];
const WALLETS = [null, "2sujbbTjp2r5ugbjfHgUNDSwtdVfYpTiCSKPgT84CvD7"];

let failures = 0, rendered = 0;
for(const symbol of Object.keys(desk.tokens)){
  setState(`CUR = ${JSON.stringify(symbol)}`);
  for(const wallet of WALLETS){
    setState(`WALLET = ${JSON.stringify(wallet)}`);
    /* Both before and after the visitor has read the markets themselves. */
    for(const live of [null, {read_at: Math.floor(Date.now() / 1000),
                              snapshot_at: Math.floor(Date.parse(desk.read_at) / 1000),
                              failed: [], tokens: Object.fromEntries(
                                Object.entries(desk.tokens).filter(([, t]) => t.covered))}]){
      sandbox.__live = live;
      setState("LIVE = __live");
      /* The liquidity study loads after the desk, so both states are covered. */
      for(const withLp of [true, false]){
      setState(withLp ? "LP = __lp" : "LP = null");
      for(const view of VIEWS){
        try{
          const html = vm.runInContext(`VIEWS[${JSON.stringify(view)}]()`, sandbox);
          if(typeof html !== "string" || html.length < 40) throw new Error("rendered almost nothing");
          if(/undefined|\[object Object\]|NaN/.test(html)) throw new Error("a value did not format");
          rendered++;
        }catch(e){
          failures++;
          console.log(`  ${view} / ${symbol} / wallet ${wallet ? "connected" : "none"} / ` +
                      `${live ? "after reading" : "before reading"}: ${e.message}`);
        }
      }
      }
    }
  }
}
console.log(failures ? `FAILED, ${failures} of ${rendered + failures} renders threw`
                     : `every view renders, ${rendered} combinations checked`);
process.exit(failures ? 1 : 0);
