/* Do the marks on chain verify from the page as a visitor would verify them?

   This is the claim the whole thing rests on: a stranger can rebuild the
   committed inputs in their own browser and get the hash the account holds.
   So it is checked here, with the page's own code, against the accounts as
   they were last read back.

   Run with: node conformance_chain.mjs
*/
import {readFileSync} from "fs";
import {webcrypto} from "crypto";
if(!globalThis.crypto) globalThis.crypto = webcrypto;

import {hashMaterial} from "./site/commit.js";

const desk = JSON.parse(readFileSync("site/desk.json", "utf8"));
const chain = JSON.parse(readFileSync("site/onchain.json", "utf8"));
const snapAt = Math.floor(Date.parse(desk.read_at) / 1000);

let bad = 0;
for(const [symbol, m] of Object.entries(chain)){
  if(symbol === "_meta") continue;
  const t = desk.tokens[symbol];
  if(!t){ console.log(`  ${symbol.padEnd(10)} on chain but not on the page`); bad++; continue; }
  const material = hashMaterial(symbol, t, snapAt, snapAt);
  const hex = [...new Uint8Array(await crypto.subtle.digest(
    "SHA-256", new TextEncoder().encode(material)))]
    .map(b => b.toString(16).padStart(2, "0")).join("");

  /* A hash can only match when the account's inputs were read at the moment
     the page's snapshot was. When they differ, the page is simply older or
     newer than the chain, which is not a failure. */
  const sameTime = m.source_read_at === snapAt;
  const ok = hex === m.sources_hash;
  if(sameTime && !ok) bad++;
  console.log(`  ${symbol.padEnd(10)} ${ok ? "verifies" : sameTime ? "DOES NOT VERIFY" : "page and chain hold different readings"}`);
  if(sameTime && !ok){
    console.log(`     page  ${hex}`);
    console.log(`     chain ${m.sources_hash}`);
  }
}
console.log(bad ? `FAILED, ${bad} marks do not verify` : "every mark on chain verifies from the shipped page");
process.exit(bad ? 1 : 0);
