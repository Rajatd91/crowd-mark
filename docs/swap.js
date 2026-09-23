/* Buying the token, from the browser, with the visitor's own wallet.

   The rest of this app exists to answer one question before this moment: is
   this worth what it costs. Having answered it, refusing to let anyone act
   would make the whole thing a dashboard again, so the trade happens here.

   Nothing is custodial. Jupiter is asked for a route and builds the
   transaction, the visitor's wallet signs and broadcasts it, and no key, no
   balance and no order ever passes through anything of ours.

   This is mainnet and it spends real money. Every figure the caller shows is
   taken from the quote below rather than estimated, and the transaction is
   only built once the visitor has asked for it.
*/
const JUP = "https://lite-api.jup.ag/swap/v1";
export const USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v";
export const USDC_DECIMALS = 6;
const MAINNET = "https://api.mainnet-beta.solana.com";

/* What a given number of dollars actually buys, including the pool's price
   impact and the route it would take. */
export async function quote(outputMint, dollars, slippageBps = 100){
  const amount = Math.round(dollars * 10 ** USDC_DECIMALS);
  const url = `${JUP}/quote?inputMint=${USDC}&outputMint=${outputMint}` +
              `&amount=${amount}&slippageBps=${slippageBps}&restrictIntermediateTokens=true`;
  const r = await fetch(url, {cache: "no-store"});
  if(!r.ok){
    const body = await r.text();
    throw new Error(body.includes("NO_ROUTE") || r.status === 404
      ? "No route to this token right now."
      : `Jupiter could not price that (${r.status}).`);
  }
  const q = await r.json();
  return {
    raw: q,
    inDollars: Number(q.inAmount) / 10 ** USDC_DECIMALS,
    outRaw: Number(q.outAmount),
    impact: parseFloat(q.priceImpactPct) || 0,
    slippageBps: q.slippageBps,
    route: (q.routePlan || []).map(p => p.swapInfo?.label).filter(Boolean),
  };
}

/* Ask Jupiter to build the transaction for this exact quote. */
async function build(quoteRaw, owner){
  const r = await fetch(`${JUP}/swap`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      quoteResponse: quoteRaw,
      userPublicKey: owner,
      wrapAndUnwrapSol: true,
      dynamicComputeUnitLimit: true,
      prioritizationFeeLamports: {
        priorityLevelWithMaxLamports: {maxLamports: 1_000_000, priorityLevel: "medium"},
      },
    }),
  });
  const body = await r.json();
  if(!body.swapTransaction) throw new Error(body.error || "Jupiter would not build that trade.");
  return body;
}

function bytesFrom(b64){
  const bin = atob(b64), out = new Uint8Array(bin.length);
  for(let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/* What the wallet holds of the token being spent, so the screen can say "you
   do not have enough" before anyone signs rather than after it fails. */
export async function usdcBalance(owner){
  const r = await fetch(MAINNET, {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({jsonrpc: "2.0", id: 1, method: "getTokenAccountsByOwner",
      params: [owner, {mint: USDC}, {encoding: "jsonParsed"}]}),
  });
  const j = await r.json();
  if(j.error) throw new Error(j.error.message);
  return (j.result?.value || []).reduce((sum, a) =>
    sum + parseFloat(a.account.data.parsed.info.tokenAmount.uiAmountString || "0"), 0);
}

/* Sign and send. The wallet broadcasts through its own connection where it
   can, which keeps us off the path entirely and avoids leaning on a public
   endpoint that rate limits. */
export async function buy(outputMint, dollars, provider, onStep, slippageBps = 100){
  const owner = provider.publicKey.toString();

  onStep?.("Pricing the trade");
  const q = await quote(outputMint, dollars, slippageBps);

  onStep?.("Building the transaction");
  const built = await build(q.raw, owner);
  const bytes = bytesFrom(built.swapTransaction);

  const {VersionedTransaction, Transaction, Connection} =
    await import("https://esm.sh/@solana/web3.js@1.95.3");
  let tx;
  try{ tx = VersionedTransaction.deserialize(bytes); }
  catch(e){ tx = Transaction.from(bytes); }

  onStep?.("Waiting for you to approve it");
  if(provider.signAndSendTransaction){
    const res = await provider.signAndSendTransaction(tx);
    const sig = res?.signature || res;
    onStep?.("Confirming on Solana");
    await confirm(sig, built.lastValidBlockHeight);
    return {signature: sig, quote: q};
  }

  const signed = await provider.signTransaction(tx);
  const conn = new Connection(MAINNET, "confirmed");
  onStep?.("Sending");
  const sig = await conn.sendRawTransaction(signed.serialize(), {maxRetries: 3});
  onStep?.("Confirming on Solana");
  await conn.confirmTransaction(sig, "confirmed");
  return {signature: sig, quote: q};
}

/* Poll for the result rather than hold a socket open. A trade that is still
   unconfirmed after its blockhash expires has not landed, and saying so is
   better than a spinner that never stops. */
async function confirm(signature, lastValidBlockHeight){
  const deadline = Date.now() + 90_000;
  while(Date.now() < deadline){
    const r = await fetch(MAINNET, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({jsonrpc: "2.0", id: 1, method: "getSignatureStatuses",
        params: [[signature], {searchTransactionHistory: false}]}),
    });
    const j = await r.json();
    const st = j.result?.value?.[0];
    if(st?.err) throw new Error("The trade was rejected on chain.");
    if(st?.confirmationStatus === "confirmed" || st?.confirmationStatus === "finalized") return;
    await new Promise(res => setTimeout(res, 1500));
  }
  throw new Error("Still unconfirmed after 90 seconds. Check the signature in the explorer.");
}
