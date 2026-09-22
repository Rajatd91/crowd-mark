/* Prove the browser's model agrees with the keeper's, field by field.

   Two languages compute the same mark: Python on the keeper, JavaScript in the
   visitor's browser. If they ever drift apart, the chain would hold one answer
   while the page showed another, and the hash would stop matching for no
   visible reason. So both are run over the same stored snapshot here and every
   number is compared.

   Run with: node conformance_model.mjs      (after model_expected.py writes the
   Python side to a temporary file)
*/
import {readFileSync} from "fs";
import * as M from "./site/model.js";

const snap = JSON.parse(readFileSync(process.argv[2], "utf8"));
const expected = JSON.parse(readFileSync(process.argv[3], "utf8"));

const NUMERIC = ["token_price", "mark_price", "premium_to_mark", "shares",
                 "token_implied_value", "crowd_value", "crowd_per_token",
                 "p_listing", "open_top_mass", "crowd_low", "crowd_high",
                 "crowd_odds_at_token_price"];

/* Floating point is allowed to differ in the last bits, but nothing more: the
   published figures are rounded to cents long before they reach the chain. */
const close = (a, b) => (a == null && b == null) ||
  (a != null && b != null && Math.abs(a - b) <= Math.max(1e-9, Math.abs(b) * 1e-12));

let failures = 0;
for(const [symbol, want] of Object.entries(expected.tokens)){
  const got = M.buildCard(snap.polymarket, symbol, expected.config[symbol], {
    token_price: want.token_price, mark_price: want.mark_price, shares: want.shares,
  });
  const bad = [];
  for(const k of NUMERIC) if(!close(got[k], want[k])) bad.push(`${k}: js ${got[k]} vs python ${want[k]}`);
  if(got.cap_source !== want.cap_source) bad.push(`cap_source: ${got.cap_source} vs ${want.cap_source}`);

  if(got.brackets.length !== want.brackets.length){
    bad.push(`brackets: ${got.brackets.length} vs ${want.brackets.length}`);
  } else {
    got.brackets.forEach((b, i) => {
      const w = want.brackets[i];
      if(!close(b.low, w.low) || !close(b.high, w.high) || !close(b.p, w.p)){
        bad.push(`bracket ${i}: js ${b.low}/${b.high}/${b.p} vs python ${w.low}/${w.high}/${w.p}`);
      }
    });
  }
  for(const key of ["timing", "ladder"]){
    if(got[key].length !== want[key].length){ bad.push(`${key}: ${got[key].length} vs ${want[key].length}`); continue; }
    got[key].forEach((row, i) => {
      const w = want[key][i];
      if(String(row[0]) !== String(w[0]) || !close(row[1], w[1])){
        bad.push(`${key} ${i}: js ${row} vs python ${w}`);
      }
    });
  }
  console.log(`  ${symbol.padEnd(10)} ${bad.length ? "MISMATCH" : "agrees"}`);
  bad.forEach(b => console.log(`     ${b}`));
  failures += bad.length;
}
console.log(failures ? `FAILED with ${failures} mismatches` : "both models agree on every field");
process.exit(failures ? 1 : 0);
