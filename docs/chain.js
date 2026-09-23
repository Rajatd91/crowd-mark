/* Reading Solana from the browser, with no library.

   The account address is derived here the way the program derives it, the
   bytes are decoded here field by field, and the hash is recomputed here from
   the numbers. Nothing in this file asks you to trust a server, which is the
   only reason publishing a mark on a chain is worth doing at all.
*/
import {hashMaterial, PROGRAM_ID} from "./commit.js";

const DEVNET = "https://api.devnet.solana.com";
const MAINNET = "https://api.mainnet-beta.solana.com";
const TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb";

async function rpc(method, params, url = DEVNET){
  const r = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({jsonrpc: "2.0", id: 1, method, params})});
  const j = await r.json();
  if(j.error) throw new Error(j.error.message);
  return j.result;
}

function b64ToBytes(b64){
  const bin = atob(b64), out = new Uint8Array(bin.length);
  for(let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

const B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
function bs58decode(s){
  let n = 0n;
  for(const c of s) n = n * 58n + BigInt(B58.indexOf(c));
  const out = new Uint8Array(32);
  for(let i = 31; i >= 0; i--){ out[i] = Number(n & 255n); n >>= 8n; }
  return out;
}
function bs58encode(bytes){
  let n = 0n;
  for(const b of bytes) n = (n << 8n) + BigInt(b);
  let s = "";
  while(n > 0n){ s = B58[Number(n % 58n)] + s; n /= 58n; }
  for(const b of bytes){ if(b === 0) s = "1" + s; else break; }
  return s;
}

/* An address is only usable as an account if it is NOT a point on the curve,
   which is what makes it something no private key can sign for. */
function modPow(b, e, m){ let r = 1n; b %= m; while(e > 0n){ if(e & 1n) r = r*b%m; b = b*b%m; e >>= 1n; } return r; }
function modInv(a, m){ return modPow(((a % m) + m) % m, m - 2n, m); }
function onCurve(bytes){
  const p = (1n << 255n) - 19n;
  const d = -121665n * modInv(121666n, p) % p;
  let y = 0n;
  for(let i = 31; i >= 0; i--) y = (y << 8n) + BigInt(bytes[i]);
  const sign = y >> 255n; y &= (1n << 255n) - 1n;
  if(y >= p) return false;
  const y2 = y*y % p, u = (y2 - 1n + p) % p, v = (d*y2 + 1n) % p;
  const x2 = u * modInv(v, p) % p;
  let x = modPow(x2, (p + 3n)/8n, p);
  if((x*x - x2) % p !== 0n){
    x = x * modPow(2n, (p - 1n)/4n, p) % p;
    if((x*x - x2 + p*p) % p !== 0n) return false;
  }
  return !(x === 0n && sign);
}

export async function markAddress(symbol){
  const enc = new TextEncoder();
  const seeds = [enc.encode("mark.v2"), enc.encode(symbol)];
  const prog = bs58decode(PROGRAM_ID);
  for(let bump = 255; bump >= 0; bump--){
    const parts = [...seeds, new Uint8Array([bump]), prog, enc.encode("ProgramDerivedAddress")];
    const buf = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
    let i = 0;
    for(const p of parts){ buf.set(p, i); i += p.length; }
    const h = new Uint8Array(await crypto.subtle.digest("SHA-256", buf));
    if(!onCurve(h)) return bs58encode(h);
  }
}

/* The Mark account, in the order the program declares its fields. */
export function decodeMark(bytes){
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let o = 8;                                    // Anchor's discriminator
  const str = () => { const n = dv.getUint32(o, true); o += 4;
    const v = new TextDecoder().decode(bytes.subarray(o, o + n)); o += n; return v; };
  const u64 = () => { const v = dv.getBigUint64(o, true); o += 8; return Number(v); };
  const i64 = () => { const v = dv.getBigInt64(o, true); o += 8; return Number(v); };
  const u16 = () => { const v = dv.getUint16(o, true); o += 2; return v; };

  const symbol = str(), company = str();
  const kind = dv.getUint8(o); o += 1;
  const token_price = u64()/1e6, token_implied = u64()/1e2, crowd = u64()/1e2;
  const low = u64()/1e2, high = u64()/1e2, per_token = u64()/1e6;
  const p_event = u16()/1e4, open_top = u16()/1e4;
  const deadline = i64(), deadline_p = u16()/1e4;
  const read_at = i64(), published_at = i64(), slot = u64();
  const hash = [...bytes.subarray(o, o + 32)].map(b => b.toString(16).padStart(2, "0")).join("");
  o += 32;
  const last_publisher = bs58encode(bytes.subarray(o, o + 32)); o += 32;
  const publish_count = dv.getUint32(o, true);
  return {symbol, company, kind, token_price, token_implied, crowd, low, high, per_token,
          p_event, open_top, deadline, deadline_p, read_at, published_at, slot, hash,
          last_publisher, publish_count};
}

export async function readMarks(symbols){
  const addresses = {};
  for(const s of symbols) addresses[s] = await markAddress(s);
  const res = await rpc("getMultipleAccounts",
    [Object.values(addresses), {encoding: "base64", commitment: "confirmed"}]);
  const out = {};
  Object.keys(addresses).forEach((s, i) => {
    const acc = res.value[i];
    if(acc) out[s] = {...decodeMark(b64ToBytes(acc.data[0])), account: addresses[s]};
  });
  return out;
}

/* Rebuild the committed inputs from the numbers and compare with the account.

   Which reading to rebuild from is decided by the account itself: it stores
   the moment its inputs were read, and only a reading taken at that same
   moment can possibly match.
*/
export async function verifyMark(sym, S, out, F, esc){
  out.innerHTML = `<div class="row"><span class="k">Deriving the address the way the program
    does…</span><span></span></div>`;
  try{
    const addr = await markAddress(sym);
    const acc = await rpc("getAccountInfo", [addr, {encoding: "base64", commitment: "confirmed"}]);
    if(!acc?.value) throw new Error("this company has no account on devnet yet");
    const bytes = b64ToBytes(acc.value.data[0]);
    const m = decodeMark(bytes);

    const snapAt = Math.floor(Date.parse(S.desk.read_at)/1000);
    const options = [];
    if(S.live?.tokens?.[sym]) options.push(["the reading you took in this browser",
      S.live.tokens[sym], S.live.read_at, S.live.snapshot_at]);
    options.push(["the snapshot this page shipped with", S.desk.tokens[sym], snapAt, snapAt]);
    const [label, token, readAt, snapshotAt] =
      options.find(o => o[2] === m.read_at) || options[options.length - 1];

    const material = hashMaterial(sym, token, readAt, snapshotAt);
    const hex = [...new Uint8Array(await crypto.subtle.digest(
      "SHA-256", new TextEncoder().encode(material)))]
      .map(b => b.toString(16).padStart(2, "0")).join("");
    const match = hex === m.hash;
    const sameTime = readAt === m.read_at;
    const when = t => new Date(t*1000).toISOString().slice(0,16).replace("T", " ") + "Z";

    const row = (k, v, c = "") => `<div class="row"><span class="k">${k}</span>
      <span class="v ${c}">${v}</span></div>`;
    out.innerHTML =
      row("Account, derived here from the symbol",
          `<a href="https://explorer.solana.com/address/${addr}?cluster=devnet"
              target="_blank" rel="noopener">${F.short(addr)}</a>`) +
      row("Owned by the program", F.short(acc.value.owner)) +
      row("Raw account", bytes.length + " bytes") +
      row("Decoded company", esc(m.company)) +
      row("Value it holds", F.big(m.crowd)) +
      row("Per token", F.usd(m.per_token)) +
      row("Published in slot", m.slot.toLocaleString()) +
      row("Times refreshed", m.publish_count) +
      row("Rebuilt from", esc(label)) +
      row("Inputs read at", when(readAt)) +
      row("Account says inputs read at", when(m.read_at), sameTime ? "" : "warn") +
      row("Hash recomputed here", hex.slice(0, 24) + "…") +
      row("Hash stored on chain", m.hash.slice(0, 24) + "…") +
      row("Do they match", match ? "yes" : "no", match ? "up" : "down") +
      `<p class="cap">${match
        ? "So this account was built from those exact numbers, by whoever signed it, and has not been edited since."
        : sameTime
          ? "Same reading time but a different hash. That is a real disagreement and worth reporting."
          : "The account holds a reading taken at a different moment from the one rebuilt here, so these are not expected to match. Read the markets on the left and verify again."}</p>`;
  }catch(e){
    out.innerHTML = `<p class="cap down">Could not read that account. ${esc(e.message)}</p>`;
  }
}

/* What one wallet holds of these eight tokens, and what it is worth on each
   of the three readings. */
export async function showPosition(addr, S, out, F, esc){
  if(!/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(addr)){
    out.innerHTML = `<p class="cap down">That does not look like a Solana address.</p>`;
    return;
  }
  out.innerHTML = `<p class="cap">Reading the chain…</p>`;
  try{
    /* Not over RPC. Listing an owner's token accounts is an indexed query and
       every free endpoint answers it with 403, which is what a visitor met the
       moment they connected a wallet. */
    const {balancesOf} = await import("./balances.js");
    const all = await balancesOf(addr);
    const bySym = {};
    Object.values(S.desk.tokens).forEach(t => bySym[t.mint] = t.symbol);
    const held = {}, frozen = {};
    for(const [mint, v] of Object.entries(all)){
      const sym = bySym[mint];
      if(!sym || !(v.amount > 0)) continue;
      held[sym] = v.amount;
      frozen[sym] = v.frozen;
    }
    const syms = Object.keys(held);
    if(!syms.length){
      out.innerHTML = `<p class="cap">${F.short(addr)} holds none of the eight tokens.</p>`;
      return;
    }
    out.innerHTML = syms.map(s => {
      const t = S.desk.tokens[s], amt = held[s];
      const fee = t.powers?.transfer_fee_bps, rt = (t.round_trip || [])[1];
      return `<div class="row"><span class="k"><b>${esc(t.company)}</b> · ${F.num(amt, 2)} tokens${
          frozen[s] ? ` <span class="down">· this account is frozen</span>` : ""}</span>
          <span class="v">${F.usd(amt * t.token_price)}</span></div>` +
        (t.crowd_per_token ? `<div class="row"><span class="k">at the crowd's value</span>
          <span class="v up">${F.usd(amt * t.crowd_per_token)}</span></div>` : "") +
        (fee != null ? `<div class="row"><span class="k">fee to move it once</span>
          <span class="v warn">−${F.usd(amt * t.token_price * fee / 1e4)}</span></div>` : "") +
        (rt?.cost != null ? `<div class="row"><span class="k">cost to exit at this size</span>
          <span class="v warn">${F.pct(rt.cost, false, 2)}</span></div>` : "");
    }).join("");
  }catch(e){
    out.innerHTML = `<p class="cap down">Solana did not answer just then.</p>`;
  }
}
