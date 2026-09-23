/* What a wallet holds, read without an RPC key.

   Solana's public endpoint refuses this. Listing the token accounts of an
   owner is an indexed query, and every free endpoint answers it with 403
   Access forbidden, which is what a visitor saw the moment they connected a
   wallet. Paying for an endpoint would mean putting a key in this file, where
   anyone could take it.

   Jupiter answers the same question over plain HTTP, allows browser requests,
   and needs no key. It also reports whether each account is frozen, which
   matters here more than usual: these mints keep a freeze authority, and a
   holder ought to be told their own account has been frozen rather than only
   that it could be.
*/
const BALANCES = "https://lite-api.jup.ag/ultra/v1/balances/";

/* Every balance the wallet holds, keyed by mint, with SOL under "SOL". */
export async function balancesOf(owner){
  const r = await fetch(BALANCES + owner, {cache: "no-store"});
  if(!r.ok) throw new Error(`Could not read that wallet (${r.status}).`);
  const body = await r.json();
  const out = {};
  for(const [mint, v] of Object.entries(body || {})){
    if(!v || typeof v.uiAmount !== "number") continue;
    out[mint] = {amount: v.uiAmount, frozen: !!v.isFrozen, slot: v.slot};
  }
  return out;
}

/* How much of one mint, which is all the buy screen needs to know. */
export async function balanceOf(owner, mint){
  const all = await balancesOf(owner);
  return all[mint]?.amount ?? 0;
}
