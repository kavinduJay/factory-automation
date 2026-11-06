// One-series time chart: 2 px line, min-max band when aggregated, optional
// dashed limit line, recessive grid, crosshair + tooltip on hover.
import { esc, fmt, time, dateTime } from './util.js';

const P = { l: 40, r: 10, t: 10, b: 22 };

export function lineChart(el, points, { unit = '', limit = null, digits = 1, long = false } = {}) {
  if (!points || points.length < 2) { el.innerHTML = '<p class="note">Not enough data yet.</p>'; return; }
  // Draw in CSS pixels so text stays 11 px whatever the container width.
  const W = Math.max(260, Math.round(el.clientWidth || el.parentElement?.clientWidth || 640));
  const H = Math.round(Math.min(220, Math.max(150, W * 0.38)));
  const ts = points.map(p => new Date(p[0]).getTime());
  const lo = Math.min(...points.map(p => p[2]), ...(limit != null ? [limit] : []));
  const hi = Math.max(...points.map(p => p[3]), ...(limit != null ? [limit] : []));
  const pad = (hi - lo) * 0.1 || 1;
  const y0 = lo - pad, y1 = hi + pad, x0 = ts[0], x1 = ts[ts.length - 1];
  const X = t => P.l + (t - x0) / (x1 - x0 || 1) * (W - P.l - P.r);
  const Y = v => H - P.b - (v - y0) / (y1 - y0) * (H - P.t - P.b);
  const line = points.map((p, i) => `${i ? 'L' : 'M'}${X(ts[i]).toFixed(1)} ${Y(p[1]).toFixed(1)}`).join('');
  const aggregated = points.some(p => p[2] !== p[3]);
  const band = aggregated
    ? points.map((p, i) => `${i ? 'L' : 'M'}${X(ts[i]).toFixed(1)} ${Y(p[3]).toFixed(1)}`).join('') +
      points.slice().reverse().map((p, i) => `L${X(ts[ts.length - 1 - i]).toFixed(1)} ${Y(p[2]).toFixed(1)}`).join('') + 'Z'
    : '';
  const ticks = 4, grid = [];
  for (let i = 0; i <= ticks; i++) {
    const v = y0 + (y1 - y0) * i / ticks;
    grid.push(`<line x1="${P.l}" x2="${W - P.r}" y1="${Y(v)}" y2="${Y(v)}"/>`);
    grid.push(`<text x="${P.l - 6}" y="${Y(v) + 4}" text-anchor="end">${fmt(v, Math.abs(y1 - y0) < 5 ? 1 : 0)}</text>`);
  }
  const xt = [];
  for (let i = 0; i <= 3; i++) {
    const t = x0 + (x1 - x0) * i / 3;
    xt.push(`<text x="${X(t)}" y="${H - 6}" text-anchor="${i === 0 ? 'start' : i === 3 ? 'end' : 'middle'}">${long ? dateTime(t) : time(t)}</text>`);
  }
  el.classList.add('chart');
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Line chart, ${points.length} points">
    <g class="grid axis">${grid.join('')}</g><g class="axis">${xt.join('')}</g>
    ${band ? `<path class="band" d="${band}"/>` : ''}
    ${limit != null ? `<line class="limit" x1="${P.l}" x2="${W - P.r}" y1="${Y(limit)}" y2="${Y(limit)}"/>` : ''}
    <path class="line" d="${line}"/>
    <line class="cross" y1="${P.t}" y2="${H - P.b}" visibility="hidden"/>
    <circle class="marker" r="4.5" visibility="hidden"/>
    <rect x="${P.l}" y="0" width="${W - P.l - P.r}" height="${H}" fill="transparent"/>
  </svg><div class="tip" hidden></div>`;
  const svg = el.querySelector('svg'), cross = svg.querySelector('.cross'), mark = svg.querySelector('.marker'), tip = el.querySelector('.tip');
  function show(evt) {
    const r = svg.getBoundingClientRect();
    const x = (evt.clientX - r.left) / r.width * W;
    const t = x0 + (x - P.l) / (W - P.l - P.r) * (x1 - x0);
    let i = 0, best = Infinity;
    ts.forEach((v, j) => { const d = Math.abs(v - t); if (d < best) { best = d; i = j; } });
    const p = points[i], px = X(ts[i]), py = Y(p[1]);
    cross.setAttribute('x1', px); cross.setAttribute('x2', px); cross.setAttribute('visibility', 'visible');
    mark.setAttribute('cx', px); mark.setAttribute('cy', py); mark.setAttribute('visibility', 'visible');
    tip.hidden = false;
    tip.style.left = `${px / W * 100}%`; tip.style.top = `${py / H * 100}%`;
    tip.innerHTML = `${esc(long ? dateTime(ts[i]) : time(ts[i], true))} · <b>${fmt(p[1], digits)} ${esc(unit)}</b>` +
      (aggregated ? ` <span class="note">(${fmt(p[2], digits)}–${fmt(p[3], digits)})</span>` : '');
  }
  function hide() { cross.setAttribute('visibility', 'hidden'); mark.setAttribute('visibility', 'hidden'); tip.hidden = true; }
  svg.addEventListener('pointermove', show);
  svg.addEventListener('pointerleave', hide);
}

// Tiny inline trend for side panels (no axes; the number beside it is the value).
export function spark(values) {
  const v = values.filter(x => x != null);
  if (v.length < 2) return '';
  const mn = Math.min(...v), mx = Math.max(...v), rg = (mx - mn) || 1;
  const pts = v.map((x, i) => `${(i / (v.length - 1) * 100).toFixed(1)},${(40 - (x - mn) / rg * 34).toFixed(1)}`).join(' ');
  return `<svg class="spark" viewBox="0 0 100 44" preserveAspectRatio="none" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="var(--sel)" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>`;
}
