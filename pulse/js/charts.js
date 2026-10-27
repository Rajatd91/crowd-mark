/* Small SVG charts, drawn by hand so the page loads fast and depends on
   nothing. Colours come from CSS classes, so light and dark themes both work. */

const esc = s => String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const pct = p => `${Math.round(p * 100)}%`;

/* The listing-value distribution: one bar per bracket, the median's bracket marked. */
export function distributionChart(dist, median, fmtShort){
  const n = dist.brackets.length;
  const W = 640, H = 260, padL = 8, padR = 8, padT = 28, padB = 54;
  const bw = (W - padL - padR) / n, maxQ = Math.max(...dist.brackets.map(b => b.q), 0.01);
  const bars = dist.brackets.map((b, i) => {
    const h = (H - padT - padB) * b.q / maxQ;
    const x = padL + i * bw + bw * 0.12, w = bw * 0.76, y = H - padB - h;
    const isMedian = median >= b.lo && median < b.hi;
    const label = b.open === "top" ? `${fmtShort(b.lo)}+` : b.open === "bottom" ? `<${fmtShort(b.hi)}` : compact(b.lo, b.hi);
    return `<g class="bar${isMedian ? " is-median" : ""}">
      <rect x="${x}" y="${y}" width="${w}" height="${Math.max(h, 1.5)}" rx="5"><title>${esc(b.title)}: ${pct(b.q)}</title></rect>
      <text class="v" x="${x + w / 2}" y="${y - 8}" text-anchor="middle">${pct(b.q)}</text>
      <text class="l" x="${x + w / 2}" y="${H - padB + 20}" text-anchor="middle">${esc(label)}</text>
      ${isMedian ? `<text class="m" x="${x + w / 2}" y="${H - padB + 38}" text-anchor="middle">median</text>` : ""}
    </g>`;
  }).join("");
  return `<svg class="chart dist" viewBox="0 0 ${W} ${H}" role="img" aria-label="Probability of each listing value">
    <line class="axis" x1="${padL}" x2="${W - padR}" y1="${H - padB}" y2="${H - padB}"/>${bars}</svg>`;
}

/* "1.25–1.5T" rather than "$1.25T–$1.5T": the unit once, so labels fit under narrow bars. */
function compact(lo, hi){
  const u = hi >= 1e12 ? [1e12, "T"] : [1e9, "B"];
  const n = v => +(v / u[0]).toFixed(2);
  return lo >= u[0] || u[1] === "B" ? `${n(lo)}–${n(hi)}${u[1]}` : `${+(lo / 1e9).toFixed(0)}B–${n(hi)}${u[1]}`;
}

const fmtMonth = t => new Date(t).toLocaleDateString("en-GB", {month: "short", year: "2-digit", timeZone: "UTC"});

/* Chance of a listing by each date, with today and the median date marked. */
export function timelineChart(timeline, now){
  const from = now - 92 * 864e5;
  const recent = timeline.points.filter(p => p.t >= from);
  const pts = recent.length >= 2 ? recent : timeline.points;
  const W = 640, H = 240, padL = 40, padR = 16, padT = 16, padB = 36;
  const t0 = Math.min(pts[0].t, now), t1 = pts[pts.length - 1].t;
  const X = t => padL + (t - t0) / (t1 - t0 || 1) * (W - padL - padR);
  const Y = p => padT + (1 - p) * (H - padT - padB);
  const path = pts.map((p, i) => `${i ? "L" : "M"}${X(p.t).toFixed(1)},${Y(p.p).toFixed(1)}`).join(" ");
  const area = `${path} L${X(pts[pts.length - 1].t).toFixed(1)},${Y(0)} L${X(pts[0].t).toFixed(1)},${Y(0)} Z`;
  const grid = [0, 0.25, 0.5, 0.75, 1].map(p =>
    `<line class="grid${p === 0.5 ? " half" : ""}" x1="${padL}" x2="${W - padR}" y1="${Y(p)}" y2="${Y(p)}"/>
     <text class="tick" x="${padL - 8}" y="${Y(p) + 4}" text-anchor="end">${pct(p)}</text>`).join("");
  const dots = pts.map(p => `<circle class="dot${p.closed ? " closed" : ""}" cx="${X(p.t)}" cy="${Y(p.p)}" r="4">
      <title>${esc(p.title)}: ${pct(p.p)}${p.closed ? " (resolved)" : ""}</title></circle>`).join("");
  const labels = thin(pts, 6).map(p => `<text class="tick" x="${X(p.t)}" y="${H - 12}" text-anchor="middle">${fmtMonth(p.t)}</text>`).join("");
  const today = now >= t0 && now <= t1
    ? `<line class="today" x1="${X(now)}" x2="${X(now)}" y1="${padT}" y2="${H - padB}"/><text class="today-l" x="${X(now) + 6}" y="${padT + 12}">today</text>` : "";
  const med = timeline.median && timeline.median.bounded
    ? `<circle class="median" cx="${X(timeline.median.t)}" cy="${Y(0.5)}" r="6"/>` : "";
  return `<svg class="chart timeline" viewBox="0 0 ${W} ${H}" role="img" aria-label="Chance of a listing by each date">
    ${grid}<path class="area" d="${area}"/><path class="line" d="${path}"/>${today}${dots}${med}${labels}</svg>`;
}

function thin(arr, max){
  if(arr.length <= max) return arr;
  const step = Math.ceil(arr.length / max);
  return arr.filter((_, i) => i % step === 0 || i === arr.length - 1);
}

/* Touch odds: the chance the valuation reaches each level, levels already reached marked. */
export function ladderChart(ladder, fmtShort){
  const rows = [...ladder.up].reverse();
  const W = 480, rowH = 34, padL = 70, padR = 64, H = rows.length * rowH + 8;
  const body = rows.map((r, i) => {
    const y = 4 + i * rowH, w = (W - padL - padR) * r.p;
    return `<g class="rung${r.reached ? " reached" : ""}">
      <text class="l" x="${padL - 12}" y="${y + rowH / 2 + 4}" text-anchor="end">${esc(fmtShort(r.level))}</text>
      <rect class="track" x="${padL}" y="${y + 7}" width="${W - padL - padR}" height="${rowH - 14}" rx="6"/>
      <rect class="fill" x="${padL}" y="${y + 7}" width="${Math.max(w, 2)}" height="${rowH - 14}" rx="6"><title>${esc(r.title)}: ${pct(r.p)}</title></rect>
      <text class="v" x="${W - padR + 10}" y="${y + rowH / 2 + 4}">${r.reached ? "reached" : pct(r.p)}</text>
    </g>`;
  }).join("");
  return `<svg class="chart ladder" viewBox="0 0 ${W} ${H}" role="img" aria-label="Chance the valuation reaches each level">${body}</svg>`;
}

/* A slim bar showing the 80% range with the median, on a shared scale. */
export function rangeBar(p10, median, p90, lo, hi){
  const X = v => Math.max(0, Math.min(100, (v - lo) / (hi - lo || 1) * 100));
  return `<div class="rangebar" aria-hidden="true">
    <span class="rb-range" style="left:${X(p10)}%;width:${X(p90) - X(p10)}%"></span>
    <span class="rb-median" style="left:${X(median)}%"></span></div>`;
}
