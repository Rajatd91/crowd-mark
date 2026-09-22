/* Publishing from the browser.

   The feed is open: anyone may refresh a mark, and the program records who
   did. This takes the mark the page just computed, builds the same instruction
   the keeper builds, hands it to the wallet to sign, and reports the
   signature. Nothing is custodial and nothing is spent beyond the network fee,
   which on devnet is a fraction of a cent.

   The bytes themselves are in commit.js, which has no network code, so what
   gets signed can be checked without a wallet.
*/
import {Connection, PublicKey, Transaction, TransactionInstruction, SystemProgram}
  from "https://esm.sh/@solana/web3.js@1.95.3";
import {PROGRAM_ID, publishData, hashMaterial} from "./commit.js";

const RPC = "https://api.devnet.solana.com";
const enc = new TextEncoder();
const program = () => new PublicKey(PROGRAM_ID);

export {hashMaterial};

export async function markAddress(symbol){
  const [mark] = await PublicKey.findProgramAddress(
    [enc.encode("mark.v2"), enc.encode(symbol)], program());
  return mark;
}

export async function buildPublishIx(symbol, t, readAt, snapshotAt, payer){
  const mark = await markAddress(symbol);
  const [config] = await PublicKey.findProgramAddress([enc.encode("config")], program());
  return {ix: new TransactionInstruction({
    programId: program(),
    keys: [
      {pubkey: payer, isSigner: true, isWritable: true},
      {pubkey: config, isSigner: false, isWritable: true},
      {pubkey: mark, isSigner: false, isWritable: true},
      {pubkey: SystemProgram.programId, isSigner: false, isWritable: false},
    ],
    data: await publishData(symbol, t, readAt, snapshotAt),
  }), mark};
}

/* Publish one mark, reporting each step so the page never looks frozen. */
export async function publishFromWallet(symbol, token, readAt, snapshotAt, provider, onStep){
  const conn = new Connection(RPC, "confirmed");
  const payer = provider.publicKey;

  onStep?.("Checking the wallet can pay the fee");
  const balance = await conn.getBalance(payer);
  if(balance === 0){
    onStep?.("This wallet has no devnet SOL, asking the faucet");
    try{
      await conn.requestAirdrop(payer, 1e8);
      await new Promise(r => setTimeout(r, 4000));
    }catch(e){
      throw new Error("No devnet SOL, and the faucet refused. Fund the wallet at " +
                      "faucet.solana.com and try again.");
    }
  }

  onStep?.("Building the instruction");
  const {ix, mark} = await buildPublishIx(symbol, token, readAt, snapshotAt, payer);
  const tx = new Transaction().add(ix);
  tx.feePayer = payer;
  tx.recentBlockhash = (await conn.getLatestBlockhash("confirmed")).blockhash;

  onStep?.("Waiting for you to approve it in your wallet");
  const signed = await provider.signTransaction(tx);
  onStep?.("Sending");
  const sig = await conn.sendRawTransaction(signed.serialize(), {skipPreflight: false});
  onStep?.("Confirming on devnet");
  await conn.confirmTransaction(sig, "confirmed");
  return {sig, mark: mark.toString()};
}
