const PROGRAM_ID = "6jsqLJjNynJWc2g1kRNi65wiTCkoUkQ8V3p7MUiBgGgU";
const DEVNET = "https://api.devnet.solana.com";
let CHAIN = null, CHAIN_SOURCE = "";

function b64ToBytes(b64){
  const bin = atob(b64); const out = new Uint8Array(bin.length);
  for(let i=0;i<bin.length;i++) out[i] = bin.charCodeAt(i);
  return out;
}

/* The Mark account, field by field, in the order the program declares them. */
function decodeMark(bytes){
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let o = 8;                                   // Anchor discriminator
  const str = () => { const n = dv.getUint32(o, true); o += 4;
    const v = new TextDecoder().decode(bytes.subarray(o, o+n)); o += n; return v; };
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
  const hash = [...bytes.subarray(o, o+32)].map(b=>b.toString(16).padStart(2,"0")).join("");
  o += 32;
  const last_publisher = bs58encode(bytes.subarray(o, o+32)); o += 32;
  const publish_count = dv.getUint32(o, true);
  return {symbol, company, kind, token_price, token_implied, crowd, low, high,
          per_token, p_event, open_top, deadline, deadline_p, read_at, published_at, slot, hash,
          last_publisher, publish_count};
}

async function markAddress(symbol){
  /* The account address is derived from the symbol, the same way the program does. */
  const enc = new TextEncoder();
  const seeds = [enc.encode("mark.v2"), enc.encode(symbol)];
  const prog = bs58decode(PROGRAM_ID);
  for(let bump = 255; bump >= 0; bump--){
    const parts = [...seeds, new Uint8Array([bump]), prog, enc.encode("ProgramDerivedAddress")];
    const len = parts.reduce((n,p)=>n+p.length, 0);
    const buf = new Uint8Array(len); let i = 0;
    for(const p of parts){ buf.set(p, i); i += p.length; }
    const hash = new Uint8Array(await crypto.subtle.digest("SHA-256", buf));
    if(!onCurve(hash)) return bs58encode(hash);
  }
}

const B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
function bs58decode(s){
  let n = 0n; for(const c of s) n = n*58n + BigInt(B58.indexOf(c));
  const out = new Uint8Array(32);
  for(let i = 31; i >= 0; i--){ out[i] = Number(n & 255n); n >>= 8n; }
  return out;
}
function bs58encode(bytes){
  let n = 0n; for(const b of bytes) n = (n<<8n) + BigInt(b);
  let s = ""; while(n > 0n){ s = B58[Number(n % 58n)] + s; n /= 58n; }
  for(const b of bytes){ if(b === 0) s = "1" + s; else break; }
  return s;
}
/* An address is only a valid account address if it is NOT on the ed25519 curve. */
function onCurve(bytes){
  const p = (1n<<255n) - 19n;
  const d = -121665n * modInv(121666n, p) % p;
  let y = 0n; for(let i = 31; i >= 0; i--) y = (y<<8n) + BigInt(bytes[i]);
  const sign = y >> 255n; y &= (1n<<255n) - 1n;
  if(y >= p) return false;
  const y2 = y*y % p, u = (y2 - 1n + p) % p, v = (d*y2 + 1n) % p;
  const x2 = u * modInv(v, p) % p;
  let x = modPow(x2, (p+3n)/8n, p);
  if((x*x - x2) % p !== 0n){
    x = x * modPow(2n, (p-1n)/4n, p) % p;
    if((x*x - x2 + p*p) % p !== 0n) return false;
  }
  if(x === 0n && sign) return false;
  return true;
}
function modPow(b,e,m){ let r=1n; b%=m; while(e>0n){ if(e&1n) r=r*b%m; b=b*b%m; e>>=1n; } return r; }
function modInv(a,m){ return modPow(((a%m)+m)%m, m-2n, m); }

async function loadChain(symbols){
  const addresses = {};
  for(const s of symbols) addresses[s] = await markAddress(s);
  const r = await fetch(DEVNET, {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({jsonrpc:"2.0", id:1, method:"getMultipleAccounts",
      params:[Object.values(addresses), {encoding:"base64", commitment:"confirmed"}]})});
  const j = await r.json();
  if(j.error) throw new Error(j.error.message);
  const out = {};
  Object.keys(addresses).forEach((s, i) => {
    const acc = j.result.value[i];
    if(!acc) return;
    out[s] = {...decodeMark(b64ToBytes(acc.data[0])), account: addresses[s]};
  });
  return out;
}


/* ===================================================================== */
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
let DESK=null, VIEW="board", CUR="ANTHROPIC", WALLET=null;
/* What this browser read from the markets itself, once the visitor asks it to. */
let LIVE=null;
const MAINNET = "https://api.mainnet-beta.solana.com";

const F = {
  big(x){ if(x==null) return "—";
    if(Math.abs(x)>=1e12) return "$"+(x/1e12).toFixed(2)+"T";
    if(Math.abs(x)>=1e9) return "$"+(x/1e9).toFixed(1)+"B";
    if(Math.abs(x)>=1e6) return "$"+(x/1e6).toFixed(1)+"M";
    if(Math.abs(x)>=1e3) return "$"+(x/1e3).toFixed(0)+"k";
    return "$"+Math.round(x); },
  usd(x,d=0){ return x==null?"—":"$"+x.toLocaleString(undefined,{minimumFractionDigits:d,maximumFractionDigits:d}); },
  pct(x,s=true,d=1){ return x==null?"—":(s&&x>0?"+":"")+(x*100).toFixed(d)+"%"; },
  odds(x){ return x==null?"—":Math.round(x*100)+"%"; },
  num(x,d=0){ return x==null?"—":x.toLocaleString(undefined,{maximumFractionDigits:d}); },
  short(a){ return a?a.slice(0,4)+"…"+a.slice(-4):""; },
  ago(ts){ const h=(Date.now()/1000-ts)/3600;
    return h<1?Math.max(1,Math.round(h*60))+" min":h.toFixed(1)+" h"; },
  dur(secs){ const s=Math.abs(secs);
    return s<90?Math.round(s)+" s":s<5400?Math.round(s/60)+" min":(s/3600).toFixed(1)+" h"; },
  date(t){ return (t||"").replace(/,?\s*20(\d\d)/,(m,y)=>" '"+y); }
};
const cls = x => x==null?"":x>0?"up":x<0?"down":"";
function toast(m){ const t=$("#toast"); t.textContent=m; t.classList.add("on"); setTimeout(()=>t.classList.remove("on"),2600); }

/* ------------------------------------------------------------- wallet --- */
function provider(){ return window.phantom?.solana?.isPhantom ? window.phantom.solana
  : window.solflare?.isSolflare ? window.solflare : window.solana || null; }
async function connect(){
  const p=provider();
  if(!p){ toast("No Solana wallet found. Paste an address instead."); return; }
  try{ const r=await p.connect(); WALLET=(r?.publicKey||p.publicKey).toString();
    $("#connectBtn").textContent=F.short(WALLET); $("#connectBtn").classList.remove("primary");
    toast("Connected. You can publish to the feed.");
    if(VIEW==="position"||VIEW==="publish") renderView();
  }catch(e){ toast("Connection cancelled"); }
}
async function rpc(method,params,url=MAINNET){
  const r=await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({jsonrpc:"2.0",id:1,method,params})});
  const j=await r.json(); if(j.error) throw new Error(j.error.message); return j.result;
}

/* ================================================================ views == */
function viewBoard(){
  const rows = Object.values(DESK.tokens).sort((a,b)=>(b.depth?.liquidity||0)-(a.depth?.liquidity||0));
  const head = ["Token","Price","Issuer mark","vs mark","Crowd value","vs crowd","Lists by",
                "Liquidity","24h volume","Holders","Exit $10k","Fee"];
  return `<div class="panel wide">
    <h2>Every PreStocks token, priced three ways</h2>
    <div class="tablewrap"><table class="board">
      <thead><tr>${head.map(h=>`<th>${h}</th>`).join("")}</tr></thead>
      <tbody>${rows.map(t=>{
        const rt = (t.round_trip||[])[1];
        const near = (t.timing||[]).filter(v=>v[1]>0.02&&v[1]<0.985).slice(-1)[0];
        return `<tr data-sym="${t.symbol}" class="${t.symbol===CUR?'on':''}">
          <td><b>${t.company}</b><div class="sub">${t.symbol}</div></td>
          <td class="num">${F.usd(t.token_price,2)}</td>
          <td class="num">${F.usd(t.mark_price,2)}</td>
          <td class="num ${cls(t.premium_to_mark)}">${F.pct(t.premium_to_mark)}</td>
          <td class="num">${t.crowd_per_token?F.usd(t.crowd_per_token):"<span class='muted'>no market</span>"}</td>
          <td class="num ${cls(t.gap)}">${F.pct(t.gap)}</td>
          <td class="num">${near?`${F.odds(near[1])}<div class="sub">${F.date(near[0])}</div>`:"—"}</td>
          <td class="num">${F.big(t.depth?.liquidity)}</td>
          <td class="num">${F.big(t.depth?.volume24h)}</td>
          <td class="num">${F.num(t.depth?.holders)}</td>
          <td class="num ${rt&&rt.cost>0.03?"down":""}">${rt&&rt.cost!=null?F.pct(rt.cost,false):"—"}</td>
          <td class="num ${t.powers?.transfer_fee_bps>=100?"warn":""}">${t.powers?.transfer_fee_bps!=null?(t.powers.transfer_fee_bps/100).toFixed(2)+"%":"—"}</td>
        </tr>`;}).join("")}</tbody>
    </table></div>
    <p class="cap">Sorted by liquidity. Exit cost is a real Jupiter quote in and straight back out at $10,000, so it includes the pool's own price impact. The fee column is charged by the mint on every transfer, in each direction.</p>
  </div>`;
}

function viewValuation(){
  const t=DESK.tokens[CUR];
  if(!t.covered) return `<div class="panel"><h2>${t.company}</h2>
    <p class="muted">No prediction market prices this company, so there is nothing to value it against.
    The board, execution and issuer views still cover it.</p></div>`;
  return `<div class="panel">
      <h2>What the crowd expects${t.kind==="ipo"?" on listing day":" by 31 December"}</h2>
      <div class="figrow" id="valFigs"></div>
      <figure><div id="valChart"></div><figcaption id="valCap"></figcaption></figure>
    </div>
    <div class="panel">
      <h2>Move the assumptions</h2>
      <div class="ctrls">
        <label>Conversion haircut <output id="hcOut"></output>
          <input type="range" id="hc" min="0" max="60" step="1"></label>
        <label>Months until it lists <output id="mnOut"></output>
          <input type="range" id="mn" min="1" max="36" step="1" value="3"></label>
        <label>Your required return a year <output id="rrOut"></output>
          <input type="range" id="rr" min="0" max="40" step="1" value="15"></label>
      </div>
      <div class="rows" id="valRows"></div>
      <p class="cap">The haircut starts where SpaceX actually trades against its listed stock today. Nothing here is a recommendation, it is arithmetic on numbers you can change.</p>
    </div>`;
}

function viewPayoff(){
  const t=DESK.tokens[CUR];
  if(!t.covered||!t.brackets?.length) return `<div class="panel"><h2>${t.company}</h2>
    <p class="muted">A payoff needs a distribution to draw from, and no market prices this company.</p></div>`;
  return `<div class="panel">
    <h2>What a token actually pays, simulated</h2>
    <p class="muted" style="margin-top:-6px">Ten thousand draws. Each one picks a listing value from the crowd's own distribution, a listing date from its timing odds, and a conversion haircut around what SpaceX has really paid, then discounts it back at your required return.</p>
    <div class="figrow" id="mcFigs"></div>
    <figure><div id="mcChart"></div><figcaption>Distribution of the value of one token today, after conversion and discounting. The line marks what it costs now.</figcaption></figure>
    <div class="rows" id="mcRows"></div>
  </div>`;
}

function viewExecution(){
  const rows=Object.values(DESK.tokens).filter(t=>t.round_trip?.length);
  return `<div class="panel wide">
    <h2>What it costs to get in and out</h2>
    <div class="tablewrap"><table class="board">
      <thead><tr><th>Token</th><th>$1,000</th><th>$10,000</th><th>$50,000</th><th>Transfer fee, both ways</th><th>Days of fee income to break even</th></tr></thead>
      <tbody>${rows.map(t=>{
        const c=Object.fromEntries((t.round_trip||[]).map(r=>[r.size,r.cost]));
        const fee=(t.powers?.transfer_fee_bps||0)/1e4*2;
        const worst=c[10000];
        return `<tr data-sym="${t.symbol}"><td><b>${t.company}</b></td>
          ${[1000,10000,50000].map(s=>`<td class="num ${c[s]>0.03?"down":""}">${c[s]!=null?F.pct(c[s],false,2):"—"}</td>`).join("")}
          <td class="num warn">${F.pct(fee,false,2)}</td>
          <td class="num">${worst!=null?Math.ceil((worst+fee)/0.0015):"—"}</td></tr>`;}).join("")}
      </tbody></table></div>
    <p class="cap">Round trip is a live Jupiter quote in and straight back out, so it carries the pool's real price impact at that size. The last column asks how many days of a typical 0.15% daily fee yield it would take to earn back the cost of the trip, which is the question a holder deciding whether to trade at all should ask.</p>
  </div>`;
}

function viewIssuer(){
  const rows=Object.values(DESK.tokens);
  return `<div class="panel wide">
    <h2>What each issuer can still do to your balance</h2>
    <div class="tablewrap"><table class="board">
      <thead><tr><th>Token</th><th>Transfer fee</th><th>Can pause</th><th>Permanent delegate</th><th>Freeze authority</th><th>Display multiplier</th></tr></thead>
      <tbody>${rows.map(t=>{const p=t.powers||{};return `<tr><td><b>${t.company}</b></td>
        <td class="num ${p.transfer_fee_bps>=100?"warn":""}">${p.transfer_fee_bps!=null?(p.transfer_fee_bps/100).toFixed(2)+"%":"—"}</td>
        <td>${p.paused===true?'<span class="down">paused now</span>':p.paused===false?"yes":"—"}</td>
        <td>${p.permanent_delegate?`<span class="warn">yes</span> <span class="sub">${F.short(p.permanent_delegate)}</span>`:"no"}</td>
        <td>${p.freeze_authority?`<span class="warn">yes</span>`:"no"}</td>
        <td class="num">${p.ui_multiplier&&p.ui_multiplier!==1?p.ui_multiplier+"×":"1×"}</td></tr>`;}).join("")}
      </tbody></table></div>
    <div class="note"><b>These powers get used.</b> ${DESK.fee_history.length>1
      ? `Our hourly snapshots caught the fee move from ${(DESK.fee_history[0].bps/100).toFixed(2)}% to
         ${(DESK.fee_history[DESK.fee_history.length-1].bps/100).toFixed(2)}% at the epoch
         ${DESK.fee_history[DESK.fee_history.length-1].epoch} boundary, on
         ${new Date(DESK.fee_history[DESK.fee_history.length-1].at).toUTCString().slice(5,17)}. No announcement was made.`
      : `The fee on every PreStocks token doubled on 20 September at an epoch boundary.`}</div>
    <p class="cap">A permanent delegate can move a balance without the holder signing. A freeze authority can stop one account. These are ordinary Token-2022 features, and they are listed here because a holder cannot see them in a wallet.</p>
  </div>`;
}

function viewVerify(){
  return `<div class="panel">
    <h2>Check the mark yourself</h2>
    <p class="muted" style="margin-top:-6px">Nothing here asks to be believed. Pick a company, and your
      browser will fetch its account from Solana, decode it in front of you, and recompute the hash of the
      inputs from the published sources to see whether it matches what the chain holds.</p>
    <div class="ctrls"><label>Company
      <select id="vSym">${Object.keys(DESK.tokens).filter(s=>DESK.tokens[s].covered).map(s=>`<option ${s===CUR?"selected":""}>${s}</option>`).join("")}</select></label>
      <button class="btn primary" id="vRun">Verify</button></div>
    <div id="vOut" class="verify"></div>
  </div>`;
}

function viewPosition(){
  return `<div class="panel">
    <h2>Your position</h2>
    <div id="walletBody">
      <p class="muted">Connect a wallet, or paste any address, and every holding is valued against the
        crowd, against what conversion has actually paid, and after the cost of getting out.</p>
      <div class="field"><input id="addr" placeholder="Paste a Solana address" spellcheck="false" aria-label="Solana address">
        <button class="btn" id="goBtn">Show</button></div>
      <p class="muted" style="margin-top:10px"><a href="#" id="demoLink">Use an example holder</a> · read only, nothing to sign</p>
    </div>
  </div>`;
}

/* ========================================================= interactions == */
function distChart(t, el){
  const W=720,H=250,m={t:30,r:14,b:34,l:14}, bs=t.brackets||[];
  if(!bs.length) return "";
  const lo=bs[0].low, hi=bs[bs.length-1].high, span=hi-lo||1;
  const x=v=>m.l+((v-lo)/span)*(W-m.l-m.r);
  const pmax=Math.max(...bs.map(b=>b.p)), y=p=>H-m.b-(p/pmax)*(H-m.t-m.b);
  let g="",bars="",ticks="";
  for(let i=0;i<=4;i++){const yy=m.t+(H-m.t-m.b)*i/4;
    g+=`<line class="grid-line" x1="${m.l}" y1="${yy}" x2="${W-m.r}" y2="${yy}"/>`;}
  bs.forEach(b=>{const x0=x(b.low)+1.4,x1=x(b.high)-1.4,yy=y(b.p);
    bars+=`<rect class="bar" x="${x0}" y="${yy}" width="${Math.max(1,x1-x0)}" height="${Math.max(1,H-m.b-yy)}" rx="3">
      <title>${(b.low/1e12).toFixed(2)}T to ${(b.high/1e12).toFixed(2)}T, ${Math.round(b.p*100)}%</title></rect>`;});
  const step=span>2.4e12?0.5e12:0.25e12;
  for(let v=Math.ceil(lo/step)*step;v<=hi;v+=step)
    ticks+=`<text class="axis" x="${x(v)}" y="${H-m.b+16}" text-anchor="middle">$${(v/1e12).toFixed(2)}T</text>`;
  let marks="";
  [[t.token_implied_value,"tok","token says"],[t.crowd_value,"","crowd average"]].forEach(([v,c,lab])=>{
    if(v==null||v<lo||v>hi) return; const xx=x(v), flip=xx>W*.6;
    marks+=`<line class="mark ${c}" x1="${xx}" y1="${m.t-10}" x2="${xx}" y2="${H-m.b}"/>
      <text class="mark-lab ${c}" x="${flip?xx-8:xx+8}" y="${m.t-14}" text-anchor="${flip?"end":"start"}">${lab} ${F.big(v)}</text>`;});
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Crowd probability by listing value">${g}${bars}${ticks}${marks}
    <line class="grid-line" x1="${m.l}" y1="${H-m.b}" x2="${W-m.r}" y2="${H-m.b}"/></svg>`;
}

function ladderChart(t){
  const W=720,H=230,m={t:26,r:14,b:34,l:14};
  const r=(t.ladder||[]).filter(v=>v[1]<0.995); if(!r.length) return "";
  const lo=Math.min(...r.map(v=>v[0]))*.93, hi=Math.max(...r.map(v=>v[0]))*1.05;
  const x=v=>m.l+((v-lo)/(hi-lo))*(W-m.l-m.r), y=p=>H-m.b-p*(H-m.t-m.b);
  let g="",path="",dots="",ticks="";
  for(let i=0;i<=4;i++){const yy=m.t+(H-m.t-m.b)*i/4;
    g+=`<line class="grid-line" x1="${m.l}" y1="${yy}" x2="${W-m.r}" y2="${yy}"/>
        <text class="axis" x="${m.l}" y="${yy-4}" opacity=".7">${100-i*25}%</text>`;}
  r.forEach((v,i)=>{path+=(i?" L":"M")+x(v[0])+" "+y(v[1]);
    dots+=`<circle cx="${x(v[0])}" cy="${y(v[1])}" r="4.5" fill="var(--accent)" stroke="var(--panel)" stroke-width="2"><title>${F.big(v[0])}, ${Math.round(v[1]*100)}%</title></circle>`;
    ticks+=`<text class="axis" x="${x(v[0])}" y="${H-m.b+16}" text-anchor="middle">${F.big(v[0])}</text>`;});
  let mark=""; const tv=t.token_implied_value;
  if(tv>=lo&&tv<=hi){const flip=x(tv)>W*.6;
    mark=`<line class="mark tok" x1="${x(tv)}" y1="${m.t-8}" x2="${x(tv)}" y2="${H-m.b}"/>
      <text class="mark-lab tok" x="${flip?x(tv)-8:x(tv)+8}" y="${m.t-12}" text-anchor="${flip?"end":"start"}">token says ${F.big(tv)}</text>`;}
  return `<svg viewBox="0 0 ${W} ${H}">${g}<path d="${path}" fill="none" stroke="var(--accent)" stroke-width="2"/>${dots}${ticks}${mark}
    <line class="grid-line" x1="${m.l}" y1="${H-m.b}" x2="${W-m.r}" y2="${H-m.b}"/></svg>`;
}

function wireValuation(){
  const t=DESK.tokens[CUR]; if(!t.covered) return;
  const base=Math.round((DESK.spacex?.discount||0.2)*100);
  const hc=$("#hc"), mn=$("#mn"), rr=$("#rr");
  hc.value=base;
  $("#valFigs").innerHTML = t.kind==="ipo" ? `
    <div class="fig"><div class="lab">Token price</div><div class="val num">${F.usd(t.token_price,2)}</div>
      <div class="sub">issuer's mark ${F.usd(t.mark_price)} <span class="num ${cls(t.premium_to_mark)}">${F.pct(t.premium_to_mark)}</span></div></div>
    <div class="fig hl"><div class="lab">Crowd value per token</div><div class="val num">${F.usd(t.crowd_per_token)}</div>
      <div class="sub"><span class="num ${cls(t.gap)}">${F.pct(t.gap)}</span> against the token</div></div>
    <div class="fig"><div class="lab">Odds it lists at all</div><div class="val num">${F.odds(t.p_listing)}</div>
      <div class="sub">inside the market's window</div></div>` : `
    <div class="fig"><div class="lab">Token price</div><div class="val num">${F.usd(t.token_price,2)}</div></div>
    <div class="fig hl"><div class="lab">Odds it reaches the token's value</div>
      <div class="val num">${F.odds(t.crowd_odds_at_token_price)}</div><div class="sub">by 31 December</div></div>`;
  $("#valChart").innerHTML = t.kind==="ipo" ? distChart(t) : ladderChart(t);
  $("#valCap").textContent = t.kind==="ipo"
    ? `Each bar is the crowd's probability that ${t.company} closes its first day inside that range. The blue line is what the token's own price implies.`
    : `Each point is the crowd's probability that ${t.company} reaches that valuation by 31 December.`;
  const recalc=()=>{
    const h=+hc.value/100, months=+mn.value, r=+rr.value/100;
    $("#hcOut").textContent=hc.value+"%"; $("#mnOut").textContent=months+" months";
    $("#rrOut").textContent=r*100+"%";
    const gross=(t.crowd_per_token||0)*(1-h);
    const disc=gross/Math.pow(1+r, months/12);
    const rows=[["Crowd value per token",t.crowd_per_token,""],
                [`After a ${hc.value}% conversion haircut`,gross,"w"],
                [`Discounted over ${months} months`,disc,"q"],
                ["Trading at today",t.token_price,""]];
    const max=Math.max(...rows.map(r=>r[1]||0));
    $("#valRows").innerHTML=rows.map(([k,v,c])=>`<div class="row"><div class="k">${k}</div>
      <div class="track"><i class="${c}" style="width:${Math.round((v||0)/max*100)}%"></i></div>
      <div class="v num">${F.usd(v,2)}</div></div>`).join("")
      + `<div class="row"><div class="k"><b>What that leaves</b></div><div class="track"></div>
         <div class="v num ${cls(disc-t.token_price)}"><b>${F.pct(disc/t.token_price-1)}</b></div></div>`;
  };
  [hc,mn,rr].forEach(el=>el.addEventListener("input",recalc)); recalc();
}

/* A payoff distribution, drawn from the crowd's own numbers. */
function monteCarlo(t, haircutMean, requiredReturn, draws=10000){
  const bs=t.brackets, cum=[]; let acc=0;
  for(const b of bs){ acc+=b.p; cum.push([acc,b]); }
  const timing=(t.timing||[]).filter(v=>v[1]>0.02&&v[1]<0.99)
    .map(([l,p])=>[Date.parse(l)/1000,p]).filter(v=>v[0]).sort((a,b)=>a[0]-b[0]);
  const now=Date.now()/1000;
  const out=[];
  for(let i=0;i<draws;i++){
    const u=Math.random();
    let bucket=bs[bs.length-1];
    for(const [c,b] of cum){ if(u<=c){ bucket=b; break; } }
    const value=bucket.low+Math.random()*(bucket.high-bucket.low);
    let when=now+90*86400;
    if(timing.length){
      const q=Math.random();
      let prev=[now,0];
      for(const pt of timing){ if(q<=pt[1]){ const span=pt[0]-prev[0];
          when=prev[0]+span*((q-prev[1])/Math.max(1e-9,(pt[1]-prev[1]))); break; } prev=pt; }
      if(q>timing[timing.length-1][1]) when=timing[timing.length-1][0]+365*86400;
    }
    const years=Math.max(0,(when-now)/(365*86400));
    /* Haircut varies. Centre it on what SpaceX actually pays, with real spread. */
    const hc=Math.min(0.95,Math.max(0,haircutMean+(Math.random()+Math.random()+Math.random()-1.5)*0.16));
    const perToken=(value/t.shares)*(1-hc);
    out.push(perToken/Math.pow(1+requiredReturn,years));
  }
  out.sort((a,b)=>a-b);
  const q=p=>out[Math.floor(p*(out.length-1))];
  return {mean:out.reduce((a,b)=>a+b,0)/out.length, p10:q(0.10), p25:q(0.25), p50:q(0.50),
          p75:q(0.75), p90:q(0.90), loss:out.filter(v=>v<t.token_price).length/out.length, all:out};
}

function wirePayoff(){
  const t=DESK.tokens[CUR]; if(!t.covered||!t.brackets?.length) return;
  const hcMean=DESK.spacex?.discount||0.2;
  const mc=monteCarlo(t,hcMean,0.15);
  $("#mcFigs").innerHTML=`
    <div class="fig hl"><div class="lab">Median outcome</div><div class="val num">${F.usd(mc.p50,2)}</div>
      <div class="sub"><span class="num ${cls(mc.p50/t.token_price-1)}">${F.pct(mc.p50/t.token_price-1)}</span> against today</div></div>
    <div class="fig"><div class="lab">Middle half lands between</div>
      <div class="val num" style="font-size:22px">${F.usd(mc.p25)} – ${F.usd(mc.p75)}</div></div>
    <div class="fig"><div class="lab">Chance it pays less than today's price</div>
      <div class="val num ${mc.loss>0.5?"down":""}">${F.odds(mc.loss)}</div></div>`;
  const W=720,H=210,m={t:16,r:14,b:30,l:14};
  const lo=mc.all[0], hi=mc.all[mc.all.length-1], bins=48, w=(hi-lo)/bins;
  const counts=new Array(bins).fill(0);
  mc.all.forEach(v=>counts[Math.min(bins-1,Math.floor((v-lo)/w))]++);
  const cmax=Math.max(...counts), x=v=>m.l+((v-lo)/(hi-lo))*(W-m.l-m.r);
  let bars=counts.map((c,i)=>{const x0=x(lo+i*w)+.8,x1=x(lo+(i+1)*w)-.8;
    const h=(c/cmax)*(H-m.t-m.b);
    return `<rect class="bar" x="${x0}" y="${H-m.b-h}" width="${Math.max(1,x1-x0)}" height="${h}" rx="2"/>`;}).join("");
  const tv=x(t.token_price);
  const marks=`<line class="mark tok" x1="${tv}" y1="${m.t}" x2="${tv}" y2="${H-m.b}"/>
    <text class="mark-lab tok" x="${tv+8}" y="${m.t+10}">costs ${F.usd(t.token_price)} today</text>`;
  let ticks=""; for(let i=0;i<=4;i++){const v=lo+(hi-lo)*i/4;
    ticks+=`<text class="axis" x="${x(v)}" y="${H-m.b+16}" text-anchor="middle">${F.usd(v)}</text>`;}
  $("#mcChart").innerHTML=`<svg viewBox="0 0 ${W} ${H}">${bars}${ticks}${marks}
    <line class="grid-line" x1="${m.l}" y1="${H-m.b}" x2="${W-m.r}" y2="${H-m.b}"/></svg>`;
  $("#mcRows").innerHTML=[["Worst tenth",mc.p10],["Lower quarter",mc.p25],["Median",mc.p50],
    ["Upper quarter",mc.p75],["Best tenth",mc.p90]].map(([k,v])=>`<div class="row">
      <div class="k">${k}</div><div class="track"><i style="width:${Math.round(v/mc.p90*100)}%"></i></div>
      <div class="v num">${F.usd(v,2)}</div></div>`).join("");
}

async function wireVerify(){
  $("#vRun").onclick = async () => {
    const sym=$("#vSym").value, out=$("#vOut");
    out.innerHTML=`<p class="muted">Deriving the account address the way the program does…</p>`;
    try{
      const addr=await markAddress(sym);
      const acc=await rpc("getAccountInfo",[addr,{encoding:"base64",commitment:"confirmed"}],
        "https://api.devnet.solana.com");
      if(!acc?.value) throw new Error("no account");
      const bytes=b64ToBytes(acc.value.data[0]);
      const m=decodeMark(bytes);
      /* Rebuild the committed material here from the numbers themselves,
         rather than hashing a string somebody else published. Which reading
         to rebuild from is decided by the account: it stores the time its
         inputs were read, so only a reading with that same timestamp can
         possibly match. */
      const {hashMaterial}=await import("./commit.js");
      const snapAt=Math.floor(Date.parse(DESK.read_at)/1000);
      const candidates=[];
      if(LIVE?.tokens[sym]) candidates.push(["the reading you took in this browser",
                                             LIVE.tokens[sym], LIVE.read_at, LIVE.snapshot_at]);
      candidates.push(["the snapshot this page shipped with", DESK.tokens[sym], snapAt, snapAt]);
      const pick=candidates.find(c=>c[2]===m.read_at) || candidates[candidates.length-1];
      const [label,token,readAt,snapshotAt]=pick;
      const material=hashMaterial(sym, token, readAt, snapshotAt);
      const digest=await crypto.subtle.digest("SHA-256", new TextEncoder().encode(material));
      const hex=[...new Uint8Array(digest)].map(b=>b.toString(16).padStart(2,"0")).join("");
      const match=hex===m.hash;
      const sameTime=readAt===m.read_at;
      const hashLine=`
        <div class="kv"><span>Rebuilt from</span><span>${label}</span></div>
        <div class="kv"><span>Inputs read at</span><span class="num">${new Date(readAt*1000).toISOString().slice(0,16).replace("T"," ")}Z</span></div>
        <div class="kv"><span>Account says inputs read at</span><span class="num ${sameTime?"":"warn"}">${new Date(m.read_at*1000).toISOString().slice(0,16).replace("T"," ")}Z</span></div>
        <div class="kv"><span>Hash recomputed here</span><span class="num">${hex.slice(0,24)}…</span></div>
        <div class="kv"><span>Hash stored on chain</span><span class="num">${m.hash.slice(0,24)}…</span></div>
        <div class="kv"><span>Do they match</span><span class="${match?'up':'down'}"><b>${match?"yes":"no"}</b></span></div>
        ${match?`<p class="cap">So this account was built from those exact numbers, by whoever signed
          it, and not edited afterwards.</p>`
        :sameTime?`<p class="cap">Same reading time but a different hash. That is a real
          disagreement and worth reporting.</p>`
        :`<p class="cap">The account holds a reading taken at a different moment from the one
          rebuilt here, so the hashes are not expected to match. Read the markets on the publish
          tab and verify again, or compare against the mark published at that time.</p>`}`;
      out.innerHTML=`
        <div class="kv"><span>Account derived from the symbol</span>
          <span class="num"><a href="https://explorer.solana.com/address/${addr}?cluster=devnet" target="_blank" rel="noopener">${F.short(addr)}</a></span></div>
        <div class="kv"><span>Owned by program</span><span class="num">${F.short(acc.value.owner)}</span></div>
        <div class="kv"><span>Raw account</span><span class="num">${bytes.length} bytes</span></div>
        <pre class="bytes">${[...bytes.slice(0,64)].map(b=>b.toString(16).padStart(2,"0")).join(" ")} …</pre>
        <div class="kv"><span>Decoded company</span><span>${m.company}</span></div>
        <div class="kv"><span>Crowd value</span><span class="num">${F.big(m.crowd)}</span></div>
        <div class="kv"><span>Per token</span><span class="num">${F.usd(m.per_token,2)}</span></div>
        <div class="kv"><span>Published in slot</span><span class="num">${m.slot.toLocaleString()}</span></div>
        <div class="kv"><span>Age</span><span class="num">${F.ago(m.published_at)}</span></div>
        ${hashLine}`;
    }catch(e){ out.innerHTML=`<p class="down">Could not read that account. ${e.message}</p>`; }
  };
}

/* Read the markets from this browser and recompute every mark.

   The page ships a snapshot so it has something to show at once, but a
   snapshot is somebody else's reading, and the program will refuse a mark that
   is not newer than the one already stored. So publishing starts here: the
   visitor's own browser fetches the markets and runs the model over them.
*/
async function wireRead(){
  const btn=$("#readBtn"); if(!btn) return;
  btn.onclick = async () => {
    const out=$("#readOut");
    btn.disabled = true;
    out.innerHTML = `<p class="muted">Asking Polymarket…</p>`;
    try{
      const {readLive} = await import("./live.js");
      LIVE = await readLive(DESK, m => out.innerHTML = `<p class="muted">${m}</p>`);
      LIVE.at = Date.now();
      renderView();
      toast(`Read ${Object.keys(LIVE.tokens).length} marks from source`);
    }catch(e){
      out.innerHTML = `<p class="down">${e.message||e}</p>`;
      btn.disabled = false;
    }
  };
}

async function wirePublish(){
  wireRead();
  const btn=$("#pubBtn"); if(!btn||!WALLET||!LIVE?.tokens[CUR]) return;
  btn.onclick = async () => {
    const out=$("#pubOut"), t=LIVE.tokens[CUR];
    btn.disabled = true;
    const step = m => out.innerHTML = `<p class="muted">${m}…</p>`;
    try{
      const {publishFromWallet} = await import("./publish.js");
      const {sig, mark} = await publishFromWallet(
        CUR, t, LIVE.read_at, LIVE.snapshot_at, provider(), step);
      out.innerHTML = `<div class="kv"><span>Published by</span><span class="num">${F.short(WALLET)}</span></div>
        <div class="kv"><span>Transaction</span><span class="num">
          <a href="https://explorer.solana.com/tx/${sig}?cluster=devnet" target="_blank" rel="noopener">${sig.slice(0,10)}…</a></span></div>
        <div class="kv"><span>Account updated</span><span class="num">
          <a href="https://explorer.solana.com/address/${mark}?cluster=devnet" target="_blank" rel="noopener">${F.short(mark)}</a></span></div>`;
      toast("Published on devnet");
      CHAIN = await loadChain(Object.keys(DESK.tokens).filter(s=>DESK.tokens[s].covered));
      setTimeout(()=>renderView(), 1200);
    }catch(e){
      out.innerHTML = `<p class="down">${e.message||e}</p>`;
      btn.disabled = false;
    }
  };
}

async function showPosition(addr){
  const body=$("#walletBody");
  if(!/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(addr)){ toast("That does not look like a Solana address"); return; }
  body.innerHTML=`<p class="muted">Reading the chain…</p>`;
  try{
    const res=await rpc("getTokenAccountsByOwner",[addr,
      {programId:"TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"},{encoding:"jsonParsed"}]);
    const byMint={}; Object.values(DESK.tokens).forEach(t=>byMint[t.mint]=t.symbol);
    const held={};
    for(const a of res.value){const i=a.account.data.parsed.info,s=byMint[i.mint];
      if(!s) continue; const ui=parseFloat(i.tokenAmount.uiAmountString||"0"); if(ui>0) held[s]=(held[s]||0)+ui;}
    const syms=Object.keys(held);
    let html=`<p class="muted">${F.short(addr)} · <a href="#" id="clearBtn">clear</a></p>`;
    if(!syms.length) html+=`<p class="muted" style="margin-top:10px">This wallet holds none of the eight tokens.</p>`;
    else html+=syms.map(s=>{
      const t=DESK.tokens[s],amt=held[s],fee=t.powers?.transfer_fee_bps,rt=(t.round_trip||[])[1];
      let r=`<div class="kv"><span>Worth today</span><span class="num">${F.usd(amt*t.token_price,2)}</span></div>`;
      if(t.crowd_per_token) r+=`<div class="kv"><span>At the crowd's value</span><span class="num ${cls(t.gap)}">${F.usd(amt*t.crowd_per_token,2)}</span></div>`;
      if(t.spacex_scenario) r+=`<div class="kv"><span>If conversion pays like SpaceX's has</span><span class="num warn">${F.usd(amt*t.spacex_scenario,2)}</span></div>`;
      if(fee!=null) r+=`<div class="kv"><span>Fee to move it once</span><span class="num warn">−${F.usd(amt*t.token_price*fee/1e4,2)}</span></div>`;
      if(rt?.cost!=null) r+=`<div class="kv"><span>Cost to exit at this size</span><span class="num warn">${F.pct(rt.cost,false,2)}</span></div>`;
      return `<div class="holding"><div class="name">${t.company} · <span class="num">${F.num(amt,2)}</span></div>${r}</div>`;
    }).join("");
    body.innerHTML=html;
    $("#clearBtn").onclick=e=>{e.preventDefault();WALLET=null;renderView();};
  }catch(e){ body.innerHTML=`<p class="muted">Solana did not answer just then.</p>`; }
}

/* ------------------------------------------------------------- routing -- */
function viewPublish(){
  const t=DESK.tokens[CUR], m=CHAIN&&CHAIN[CUR], mine=LIVE?.tokens[CUR];
  if(!t.covered) return `<div class="panel"><h2>${t.company}</h2>
    <p class="muted">Only companies the crowd prices can be published.</p></div>`;
  const age = m ? (Date.now()/1000 - m.published_at)/3600 : null;

  /* Step one. Nothing can be signed until the visitor has read the markets
     from their own browser, because the program refuses a reading that is not
     newer than the one already stored. */
  const readPanel = `<div class="panel">
    <h2>1 · Read the markets yourself</h2>
    <p class="muted" style="margin-top:-6px">This page ships a snapshot so it has something to show
      at once. That snapshot is somebody else's reading. Press this and your browser fetches the
      same prediction markets directly and runs the model over them here.</p>
    <button class="btn ${mine?"":"primary"}" id="readBtn">
      ${mine?"Read again":"Read the markets now"}</button>
    <div id="readOut" style="margin-top:12px">${mine?"":""}</div>
    ${LIVE?.failed?.length?`<p class="note">${LIVE.failed.length} market${LIVE.failed.length>1?"s":""}
      did not answer, so anything priced off ${LIVE.failed.length>1?"them":"it"} is left out rather
      than guessed.</p>`:""}
  </div>`;

  if(!mine) return readPanel + `<div class="panel">
    <h2>2 · Publish what you read</h2>
    <p class="muted">Available once you have read the markets above.</p></div>`;

  const moved = t.crowd_value ? mine.crowd_value / t.crowd_value - 1 : null;
  const newer = LIVE.read_at - (m ? m.published_at : LIVE.snapshot_at);
  const rows = [
    ["Shipped snapshot", F.big(t.crowd_value), F.ago(LIVE.snapshot_at), ""],
    ["On chain now", m?F.big(m.crowd):"—", m?F.ago(m.published_at):"—", age>6?"warn":""],
    ["Your reading, just now", F.big(mine.crowd_value), "seconds ago", "hl"],
  ];

  const pubPanel = `<div class="panel">
    <h2>2 · Publish what you read</h2>
    <div class="rows" style="margin:4px 0 16px">
      ${rows.map(([k,v,when,c])=>`<div class="row"><div class="k">${k}</div>
        <div class="track"><span class="num" style="font-size:12px;color:var(--ink-3)">${when}</span></div>
        <div class="v num ${c}">${v}</div></div>`).join("")}
      <div class="row"><div class="k">Moved since the snapshot</div><div class="track"></div>
        <div class="v num ${cls(moved)}">${moved==null?"—":F.pct(moved,true,2)}</div></div>
      <div class="row"><div class="k">Newer than the stored mark by</div><div class="track"></div>
        <div class="v num ${newer>0?"up":"down"}">${newer>0?F.dur(newer):"not newer"}</div></div>
      <div class="row"><div class="k">Market it priced from</div><div class="track"></div>
        <div class="v num" style="font-size:12px">${mine.cap_source||"ladder"}</div></div>
      <div class="row"><div class="k">Times refreshed</div><div class="track"></div>
        <div class="v num">${m?.publish_count ?? "—"}</div></div>
      <div class="row"><div class="k">Last publisher</div><div class="track"></div>
        <div class="v num">${m?.last_publisher?F.short(m.last_publisher):"—"}</div></div>
    </div>
    <button class="btn primary" id="pubBtn" ${WALLET&&newer>0?"":"disabled"}>
      ${!WALLET?"Connect a wallet to publish"
        :newer>0?`Publish ${t.company} as ${F.short(WALLET)}`
        :"The stored mark is already this fresh"}</button>
    <div id="pubOut" class="verify" style="margin-top:14px"></div>
    <p class="cap">This sends a real transaction on devnet, signed by your key, and the account
      changes for everyone. It costs a network fee of about five millionths of a SOL, and if the
      wallet has none the faucet is asked once. The program refuses a reading that is stale,
      impossible, or older than the one already stored, whoever signs it.</p>
  </div>
  <div class="panel">
    <h2>What your browser used</h2>
    <p class="muted" style="margin-top:-6px">Read here, just now, from the market itself:
      the crowd's ${mine.kind==="ipo"?"distribution over listing-day value and its timing odds"
      :"ladder of touch probabilities"}.</p>
    <p class="muted">Carried from the snapshot, because prestocks.com does not answer browser
      requests: the issuer's mark price of ${F.usd(t.mark_price,2)} and the
      ${F.num(t.shares/1e6,1)}M shares it implies. Your reading records that snapshot's age, so
      a fresh timestamp cannot hide an old price.</p>
  </div>`;

  return readPanel + pubPanel;
}

const VIEWS={publish:viewPublish,board:viewBoard,valuation:viewValuation,payoff:viewPayoff,
             execution:viewExecution,issuer:viewIssuer,position:viewPosition,verify:viewVerify};
function renderView(){
  $$("#nav button").forEach(b=>b.setAttribute("aria-selected", b.dataset.view===VIEW));
  $("#symBar").style.display=["valuation","payoff"].includes(VIEW)?"":"none";
  $("#main").innerHTML=VIEWS[VIEW]();
  if(VIEW==="board"||VIEW==="execution")
    $$("tr[data-sym]").forEach(r=>r.onclick=()=>{CUR=r.dataset.sym;VIEW="valuation";renderView();});
  if(VIEW==="valuation") wireValuation();
  if(VIEW==="payoff") wirePayoff();
  if(VIEW==="verify") wireVerify();
  if(VIEW==="publish") wirePublish();
  if(VIEW==="position"){
    $("#goBtn").onclick=()=>showPosition($("#addr").value.trim());
    $("#addr").addEventListener("keydown",e=>{if(e.key==="Enter")showPosition($("#addr").value.trim());});
    $("#demoLink").onclick=e=>{e.preventDefault();$("#addr").value="2sujbbTjp2r5ugbjfHgUNDSwtdVfYpTiCSKPgT84CvD7";showPosition($("#addr").value);};
    if(WALLET) showPosition(WALLET);
  }
}

/* Paint from the file first. Nothing waits on a network call that might not
   answer, and any failure says so on the screen instead of leaving it blank. */
async function boot(){
  try{
    const r = await fetch("desk.json?"+Date.now());
    if(!r.ok) throw new Error("desk.json "+r.status);
    DESK = await r.json();
  }catch(e){
    document.querySelector("#main").innerHTML =
      `<div class="panel"><h2>Could not load the desk</h2>
       <p class="muted">${e.message}. The data file sits beside this page, so a refresh usually fixes it.</p></div>`;
    return;
  }
  const a = DESK.tokens.ANTHROPIC;
  $("#tag").innerHTML = `${a.company} is priced at <b>${F.big(a.token_implied_value)}</b> by its token and
    <b>${F.big(a.crowd_value)}</b> by the people betting on its IPO. SpaceX, the one that has already listed,
    still trades <b>${Math.round(DESK.spacex.discount*100)}%</b> below its listed stock.`;
  $("#stamp").textContent = `sources read ${new Date(DESK.read_at).toUTCString().slice(5,22)} UTC · epoch ${DESK.epoch}`;
  $("#symBar").innerHTML = Object.values(DESK.tokens).filter(t=>t.covered).map(t=>
    `<button data-sym="${t.symbol}" class="${t.symbol===CUR?'on':''}">${t.company}
      ${t.gap!=null?`<span class="tick num ${cls(t.gap)}">${F.pct(t.gap)}</span>`:""}</button>`).join("");
  $$("#symBar button").forEach(b=>b.onclick=()=>{ CUR=b.dataset.sym;
    $$("#symBar button").forEach(x=>x.classList.toggle("on",x===b)); renderView(); });
  renderView();                                    // the desk is usable from here
  paintStatus();

  /* Then, separately, try to read the chain. A failure only changes the badge. */
  try{
    CHAIN = await loadChain(Object.keys(DESK.tokens).filter(s=>DESK.tokens[s].covered));
    CHAIN_SOURCE = "read live from Solana devnet by your browser";
    $("#netPill").textContent = "devnet · live";
    const cs=$("#chainStat"); if(cs) cs.innerHTML="chain <b class=\"up\">live</b>";
    if(VIEW==="valuation"||VIEW==="verify") renderView();
  }catch(e){ $("#netPill").textContent = "devnet · offline";
    const cs=$("#chainStat"); if(cs) cs.innerHTML="chain <b class=\"warn\">offline</b>"; }

  const p = provider();
  if(p?.isConnected && p.publicKey){ WALLET = p.publicKey.toString();
    $("#connectBtn").textContent = F.short(WALLET); }
}
boot();
$$("#nav button").forEach(b=>b.onclick=()=>{VIEW=b.dataset.view;renderView();});
$("#connectBtn").onclick=connect;
$("#themeBtn").onclick=()=>{const cur=document.documentElement.getAttribute("data-theme")
  ||(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light");
  document.documentElement.setAttribute("data-theme",cur==="dark"?"light":"dark");};

/* A status bar that stays put, and number keys to move between views. */
function paintStatus(){
  if(!DESK) return;
  const t=DESK.tokens, fee=t.ANTHROPIC?.powers?.transfer_fee_bps;
  const bits=[
    `<b>${Object.keys(t).length}</b> tokens`,
    `anthropic <b class="${cls(t.ANTHROPIC?.gap)}">${F.pct(t.ANTHROPIC?.gap)}</b> vs crowd`,
    `openai <b class="${cls(t.OPENAI?.gap)}">${F.pct(t.OPENAI?.gap)}</b>`,
    `spacex conversion <b class="down">−${Math.round(DESK.spacex.discount*100)}%</b>`,
    `transfer fee <b class="warn">${fee!=null?(fee/100).toFixed(2)+"%":"—"}</b>`,
    `epoch <b>${DESK.epoch}</b>`,
    `<span id="chainStat">chain …</span>`,
  ];
  $("#statusbar").innerHTML = bits.join('<span class="sep">│</span>');
}
document.addEventListener("keydown", e=>{
  if(e.target.tagName==="INPUT"||e.target.tagName==="SELECT") return;
  const keys={"1":"board","2":"valuation","3":"payoff","4":"execution","5":"issuer",
              "6":"position","7":"publish","8":"verify"};
  if(keys[e.key]){ VIEW=keys[e.key]; renderView(); }
});
