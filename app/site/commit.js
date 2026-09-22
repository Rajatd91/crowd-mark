/* What a published mark commits to, and how it is encoded.

   Kept apart from the wallet code on purpose. Nothing here touches the
   network, so the exact bytes that go on chain can be checked on their own,
   against the keeper's Python, without a browser or a signature. That test is
   conformance_live.mjs.
*/
export const PROGRAM_ID = "6jsqLJjNynJWc2g1kRNi65wiTCkoUkQ8V3p7MUiBgGgU";

const enc = new TextEncoder();
export async function sha256(bytes){
  return new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
}

/* Anchor tags each instruction with the first eight bytes of this hash. */
export async function discriminator(name){
  return (await sha256(enc.encode("global:" + name))).slice(0, 8);
}

export function u8(n){ return [n & 255]; }
export function u16(n){ return [n & 255, (n >> 8) & 255]; }
export function u32(n){ return [n & 255, (n >> 8) & 255, (n >> 16) & 255, (n >> 24) & 255]; }
export function u64(n){
  const b = []; let v = BigInt(Math.round(n));
  for(let i = 0; i < 8; i++){ b.push(Number(v & 255n)); v >>= 8n; }
  return b;
}
export function i64(n){
  let v = BigInt(Math.round(n));
  if(v < 0n) v += 1n << 64n;
  const b = [];
  for(let i = 0; i < 8; i++) b.push(Number((v >> BigInt(8 * i)) & 255n));
  return b;
}
export function str(s){ const b = enc.encode(s); return [...u32(b.length), ...b]; }

export const cents = d => Math.round((d || 0) * 100);
export const micro = d => Math.round((d || 0) * 1e6);
export const bps = f => Math.max(0, Math.min(10000, Math.round((f || 0) * 10000)));

/* The nearest deadline the crowd still prices, with its probability.

   Parsed as UTC, matching the keeper. A bare date string is local time in most
   engines, which would write a different number from Mumbai than from London
   for the same mark. */
export function nextDeadline(t){
  const live = (t.timing || []).filter(v => v[1] > 0.02 && v[1] < 0.98);
  if(!live.length) return [0, 0];
  const best = live.reduce((a, b) => b[1] > a[1] ? b : a);
  const ts = Date.parse(best[0] + " UTC");
  return [isNaN(ts) ? 0 : Math.floor(ts / 1000), bps(best[1])];
}

/* The exact bytes the published hash commits to.

   Must equal, byte for byte, what the keeper hashes in Python. Integers only,
   joined by separators, because the two languages print floats differently and
   order nested keys differently. Two times appear: `readAt` is when the crowd
   was read, `snapshotAt` when the issuer's own figures were, since a browser
   cannot fetch those and should not let a fresh timestamp cover a stale price.
*/
export function hashMaterial(symbol, t, readAt, snapshotAt){
  const micro = x => String(Math.round((x || 0) * 1e6));
  const cents = x => String(Math.round((x || 0) * 100));
  const bpsOf = x => String(Math.round((x || 0) * 1e4));
  const brackets = (t.brackets || [])
    .map(b => `${cents(b.low)}:${cents(b.high)}:${bpsOf(b.p)}`).join(",");
  const timing = (t.timing || []).map(([l, p]) => `${l}=${bpsOf(p)}`).join(",");
  const ladder = (t.ladder || []).map(([v, p]) => `${cents(v)}=${bpsOf(p)}`).join(",");
  return ["crowdmark.v3", symbol, String(readAt), String(snapshotAt), t.cap_source || "",
          micro(t.token_price), micro(t.mark_price), cents(t.crowd_value),
          brackets, timing, ladder].join("|");
}

/* The instruction body, identical to the one the keeper signs. */
export async function publishData(symbol, t, readAt, snapshotAt){
  const hash = await sha256(enc.encode(hashMaterial(symbol, t, readAt, snapshotAt)));
  const lo = t.crowd_low ?? t.crowd_value, hi = t.crowd_high ?? t.crowd_value;
  const deadline = nextDeadline(t);
  return new Uint8Array([
    ...(await discriminator("publish")),
    ...str(symbol),
    ...str(t.company),
    ...u8(t.kind === "ipo" ? 0 : 1),
    ...u64(micro(t.token_price)),
    ...u64(cents(t.token_implied_value)),
    ...u64(cents(t.crowd_value)),
    ...u64(cents(lo)),
    ...u64(cents(hi)),
    ...u64(micro(t.crowd_per_token)),
    ...u16(bps(t.p_listing)),
    ...u16(bps(t.open_top_mass)),
    ...i64(deadline[0]),
    ...u16(deadline[1]),
    ...i64(readAt),
    ...hash,
  ]);
}
