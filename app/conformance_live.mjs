/* Rehearse a publish from the browser, without a wallet.

   This does exactly what a visitor's page does when they press publish: fetch
   the prediction markets live, recompute each mark with the browser's own
   model, and build the commitment that would be signed. It then writes that
   result out so the keeper's Python can recompute the same commitment and
   confirm the two agree.

   Without this, a mismatch would only show up as a mark that nobody can
   verify, on chain, after it was published.
*/
import {readFileSync, writeFileSync} from "fs";
import {webcrypto} from "crypto";
if(!globalThis.crypto) globalThis.crypto = webcrypto;

import {readLive} from "./site/live.js";
import {hashMaterial} from "./site/commit.js";

const desk = JSON.parse(readFileSync("site/desk.json", "utf8"));
const live = await readLive(desk, s => console.log("  " + s));
if(live.failed.length) live.failed.forEach(f => console.log("  could not read " + f));
if(!Object.keys(live.tokens).length){ console.log("no market answered, nothing to check"); process.exit(1); }

const out = {read_at: live.read_at, snapshot_at: live.snapshot_at, tokens: {}, material: {}};
for(const [symbol, card] of Object.entries(live.tokens)){
  out.tokens[symbol] = card;
  out.material[symbol] = hashMaterial(symbol, card, live.read_at, live.snapshot_at);
}
writeFileSync(process.argv[2], JSON.stringify(out, null, 1));

const age = live.read_at - live.snapshot_at;
console.log(`  read ${Object.keys(live.tokens).length} marks live, ` +
            `${Math.round(age / 60)} minutes newer than the shipped snapshot`);
for(const [symbol, card] of Object.entries(live.tokens)){
  const was = desk.tokens[symbol].crowd_value, now = card.crowd_value;
  const moved = was && now ? ((now / was - 1) * 100).toFixed(2) + "%" : "n/a";
  console.log(`  ${symbol.padEnd(10)} crowd value moved ${moved} since the snapshot`);
}
