// Plant mimic. Geometry is taken from docs/floor-plans/upper-floor-plan.svg
// and lower-floor-plan.svg (same coordinate system), so positions of troughs,
// weigh points, chutes, rollers, fermentation and drier match the plans.
import { S, reading } from './store.js';
import { $, $$, esc, fmt } from './util.js';

const pad2 = n => String(n).padStart(2, '0');
const DEFS = `<defs>
  <pattern id="fpHatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
    <rect width="8" height="8" fill="#141D22"/><line x1="0" y1="0" x2="0" y2="8" stroke="#2A3840" stroke-width="3"/></pattern>
  <pattern id="fpBeltH" width="12" height="12" patternUnits="userSpaceOnUse">
    <rect width="12" height="12" fill="#1E2B33"/><line x1="0" y1="6" x2="12" y2="6" stroke="#34434C" stroke-width="1.5"/></pattern>
  <marker id="fpArr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
    <path d="M 0 0 L 10 5 L 0 10 z" fill="#7FA7B8"/></marker></defs>`;

const chk = (x, y, t, r = 13) => `<circle class="fp-chk" cx="${x}" cy="${y}" r="${r}"/><text class="fp-chk-t" x="${x}" y="${y}">${t}</text>`;
const flow = d => `<path class="fp-flow" d="${d}"/>`;

// Trough rows from the plan: 11..5 in the right column, 4..1 in the left.
export const TROUGH_POS = {};
[11, 10, 9, 8, 7, 6, 5].forEach((t, i) => { TROUGH_POS[t] = { x: 500, y: 215 + i * 57 }; });
[4, 3, 2, 1].forEach((t, i) => { TROUGH_POS[t] = { x: 110, y: 215 + i * 57 }; });
const AREA_X0 = 30, AREA_W = (300 - AREA_X0 - 4) / 8;

function troughSVG(t) {
  const { x, y } = TROUGH_POS[t];
  let s = `<g data-sel="trough:${t}" id="tr-${t}"><rect class="fp-trough hit" x="${x}" y="${y}" width="300" height="40" rx="3"/>
    <text class="fp-b end" x="${x - 8}" y="${y + 25}">${t}</text>
    <g class="fan" id="fan-${t}" transform="translate(${x + 15} ${y + 20})"><circle class="fanc" r="10"/>
      <g class="blades"><path d="M0 -8 Q4.5 -3 0 0 Q-4.5 -3 0 -8Z"/><path d="M0 -8 Q4.5 -3 0 0 Q-4.5 -3 0 -8Z" transform="rotate(120)"/><path d="M0 -8 Q4.5 -3 0 0 Q-4.5 -3 0 -8Z" transform="rotate(240)"/></g></g>`;
  for (let a = 1; a <= 8; a++) {
    s += `<rect class="fp-area empty" id="ar-${t}-${a}" data-sel="area:${t}:${a}" x="${(x + AREA_X0 + (a - 1) * AREA_W).toFixed(1)}" y="${y + 3}" width="${(AREA_W - 2).toFixed(1)}" height="20" rx="2"><title>T${t}-A${a}</title></rect>`;
  }
  s += `<text class="fp-s" id="trt-${t}" x="${x + AREA_X0}" y="${y + 35}">–</text></g>`;
  return s;
}

export function upperSVG() {
  let h = `<svg viewBox="70 66 900 584" class="mimic-svg" role="img" aria-label="Upper floor: intake A, 11 withering troughs, withered weigh B">${DEFS}`;
  // unload outside at ground level + conveyor up
  h += `<rect x="830" y="78" width="130" height="66" class="fp-bay" stroke="#34434C" stroke-dasharray="6 4"/>
    <text class="fp-head mid" x="895" y="104">UNLOAD</text><text class="fp-s mid" x="895" y="122">ground level</text>
    <rect x="872" y="144" width="46" height="40" fill="url(#fpBeltH)" stroke="#34434C"/>`;
  // outdoor ambient (outside the building)
  h += `<g data-sel="env" id="env"><rect class="fp-weigh hit" x="90" y="112" width="230" height="44" rx="5"/>
    <text class="fp-head" x="102" y="130">OUTDOOR</text><text class="fp-t" id="envv" x="102" y="148">–</text></g>`;
  h += `<rect class="fp-floor" x="80" y="180" width="880" height="460"/>
    <rect class="fp-bay" x="836" y="184" width="120" height="452"/>
    <rect x="852" y="190" width="88" height="170" fill="url(#fpBeltH)" stroke="#34434C"/>
    <text class="fp-s mid" x="896" y="270">conveyor</text><text class="fp-s mid" x="896" y="284">from ground</text>`;
  // A
  h += `<g data-sel="weigh:A" id="w-A"><rect class="fp-weigh hit" x="852" y="400" width="88" height="130" fill="url(#fpHatch)"/>
    <rect x="856" y="420" width="80" height="92" fill="#162027" rx="3"/>
    <text class="fp-head mid" x="896" y="436">INTAKE</text>
    <text class="fp-b mid" id="wA" x="896" y="458">–</text>
    <text class="fp-s mid" id="wA2" x="896" y="476">–</text>
    <text class="fp-s mid" id="wA3" x="896" y="492">–</text>${chk(852, 400, 'A')}</g>`;
  h += `<text class="fp-head" x="500" y="205">WITHERING TROUGHS 11 – 5</text><text class="fp-head" x="110" y="205">TROUGHS 4 – 1</text>`;
  for (let t = 11; t >= 1; t--) h += troughSVG(t);
  // B and the three chutes
  h += `<g data-sel="weigh:B" id="w-B"><rect class="fp-weigh hit" x="110" y="452" width="350" height="34" fill="url(#fpHatch)"/>
    <rect x="128" y="455" width="324" height="28" fill="#162027" rx="3"/>
    <circle id="lampB" cx="142" cy="469" r="7" fill="#26333B"/>
    <text class="fp-head" x="156" y="473">WITHERED</text>
    <text class="fp-b" id="wB" x="240" y="474">–</text><text class="fp-s" id="wB2" x="300" y="473">–</text>${chk(110, 452, 'B')}</g>`;
  for (const cx of [160, 290, 420]) h += `<rect class="fp-chute" x="${cx}" y="514" width="26" height="26"/><path d="M ${cx + 6} 521 L ${cx + 20} 521 L ${cx + 13} 533 z" fill="#7FA7B8"/>`;
  h += `<text class="fp-s" x="160" y="562">3 chutes ↓ to charging rollers</text>`;
  h += flow('M 895 146 L 895 186') + flow('M 896 362 L 896 396') + flow('M 848 465 L 808 465') + flow('M 260 430 L 260 448') +
    flow('M 173 488 L 173 510') + flow('M 303 488 L 303 510') + flow('M 433 488 L 433 510');
  h += `<rect class="fp-wall" x="80" y="180" width="880" height="460"/></svg>`;
  return h;
}

// Rollers on the lower plan: CH (charging) = RC1-3, R2 = R21-23, R3 = R31-32, R4 = R41.
export const ROLLERS = [
  ['RC1', 220, 590, true], ['RC2', 350, 590, true], ['RC3', 480, 590, true],
  ['R21', 220, 492], ['R22', 350, 492], ['R23', 480, 492],
  ['R31', 220, 394], ['R32', 350, 394], ['R41', 220, 296],
];
const W_Y = { 1: 525, 2: 427, 3: 329, 4: 231 };
export const IRS_POS = [...Array(8)].map((_, i) => ({ n: i + 1, x: 592 + (i % 2) * 78, y: 250 + Math.floor(i / 2) * 50 }));

export function lowerSVG() {
  let h = `<svg viewBox="70 110 900 540" class="mimic-svg" role="img" aria-label="Lower floor: rolling with W1-W4, fermentation, drier and drier output D">${DEFS}`;
  h += `<rect class="fp-floor" x="80" y="180" width="880" height="460"/><rect class="fp-roll" x="84" y="184" width="496" height="452"/>
    <text class="fp-head" x="100" y="206">ROLLING</text>`;
  for (const y of [534, 436, 338, 240]) h += `<rect x="190" y="${y}" width="332" height="14" fill="url(#fpBeltH)" stroke="#34434C"/>`;
  for (const n of [1, 2, 3, 4]) {
    const y = W_Y[n];
    h += `<g data-sel="weigh:W${n}" id="w-W${n}"><rect class="fp-weigh hit" x="526" y="${y}" width="50" height="32" rx="2"/>
      <text class="fp-s mid" x="551" y="${y + 12}">W${n}</text><text class="fp-t mid" id="wW${n}" x="551" y="${y + 26}">–</text></g>`;
  }
  for (const [z, x, y, ch] of ROLLERS) {
    h += `<g data-sel="roller:${z}" class="roller" id="rol-${z}"><circle class="rc hit" cx="${x}" cy="${y}" r="${ch ? 32 : 30}"/>
      ${ch ? `<circle class="ring" cx="${x}" cy="${y}" r="25"/>` : ''}
      <text class="fp-s mid" x="${x}" y="${y - 9}">${z}</text>
      <text class="fp-t mid" id="rolT-${z}" x="${x}" y="${y + 5}">–</text>
      <text class="fp-s mid" id="rolA-${z}" x="${x}" y="${y + 18}">–</text></g>`;
  }
  h += chk(120, 590, 'C') + chk(120, 492, 'D') + chk(120, 394, 'E');
  for (const cx of [160, 290, 420]) h += `<rect class="fp-chute" x="${cx}" y="577" width="26" height="26" opacity=".8"/>`;
  // fermentation
  h += `<g data-sel="ferm" id="ferm"><rect class="fp-ferm hit" x="580" y="184" width="170" height="276"/>
    <text class="fp-head" x="592" y="204">FERMENTATION</text>
    <text class="fp-t" id="fermRoom" x="592" y="222">–</text><text class="fp-s" id="fermRoom2" x="592" y="238">–</text></g>`;
  for (const p of IRS_POS) {
    h += `<g data-sel="irs:${p.n}" id="irs-${p.n}"><rect class="hot-cell hit" id="irsc-${p.n}" x="${p.x}" y="${p.y}" width="72" height="44" rx="4" fill="#3E3529"/>
      <text class="fp-s" x="${p.x + 5}" y="${p.y + 13}">${p.n}</text>
      <text class="fp-b mid" id="irsT-${p.n}" x="${p.x + 36}" y="${p.y + 32}">–</text></g>`;
  }
  // drier, chamber behind the wall, D in sorting & grading
  h += `<rect x="750" y="118" width="206" height="58" fill="#3B3128" stroke="#34434C" stroke-dasharray="6 4"/>
    <text class="fp-s mid" x="853" y="143">drier chamber</text><text class="fp-s mid" x="853" y="158">(behind wall)</text>`;
  h += `<g data-sel="drier" id="drier"><rect class="fp-dry hit" x="750" y="184" width="206" height="122"/>
    <text class="fp-head" x="762" y="204">DRIER</text>
    <text class="fp-s" x="762" y="226">Inlet</text><text class="fp-b end" id="dIn" x="944" y="226">–</text>
    <text class="fp-s" x="762" y="248">Outlet</text><text class="fp-t end" id="dOut" x="944" y="248">–</text>
    <text class="fp-s" x="762" y="270">Exhaust</text><text class="fp-t end" id="dEx" x="944" y="270">–</text>
    <text class="fp-s" x="762" y="292">Motor</text><text class="fp-t end" id="dMot" x="944" y="292">–</text></g>`;
  h += `<rect class="fp-sort" x="750" y="306" width="206" height="184"/>
    <text class="fp-s mid" x="853" y="460">sorting &amp; grading</text>
    <g data-sel="weigh:D" id="w-D"><rect class="fp-weigh hit" x="770" y="320" width="168" height="62" rx="3"/>
      <circle id="lampD" cx="790" cy="340" r="7" fill="#26333B"/>
      <text class="fp-head" x="804" y="344">DRIER OUT</text>
      <text class="fp-b" id="wD" x="790" y="370">–</text><text class="fp-s end" id="wD2" x="930" y="370">–</text>${chk(770, 320, 'D')}</g>`;
  h += `<rect class="fp-ground" x="580" y="490" width="376" height="146"/><rect class="fp-ground" x="580" y="460" width="100" height="30"/>
    <text class="fp-s mid" x="788" y="568">ground-level area</text>`;
  h += `<line x1="580" y1="184" x2="580" y2="636" stroke="#34434C" stroke-width="2"/><line x1="750" y1="184" x2="750" y2="490" stroke="#34434C" stroke-width="2"/>
    <line x1="750" y1="306" x2="956" y2="306" stroke="#34434C" stroke-width="2"/><line x1="580" y1="490" x2="956" y2="490" stroke="#34434C" stroke-width="2"/>`;
  h += flow('M 440 541 L 520 541') + flow('M 550 523 L 550 492 L 516 492') + flow('M 440 443 L 520 443') + flow('M 550 425 L 550 394 L 386 394') +
    flow('M 440 345 L 520 345') + flow('M 550 327 L 550 296 L 256 296') + flow('M 440 247 L 520 247') + flow('M 576 247 L 586 247') +
    flow('M 700 445 L 700 470 L 790 470 L 790 300');
  h += `<rect class="fp-wall" x="80" y="180" width="880" height="460"/></svg>`;
  return h;
}

// ---- mapping entities (sensors, devices) to mimic elements ------------------

export function keysForSensor(s) {
  if (!s) return [];
  const zone = s.asset_id.split('-')[2];
  if (zone?.startsWith('TR')) return [`trough:${Number(zone.slice(2))}`];
  if (ROLLERS.some(r => r[0] === zone)) return [`roller:${zone}`];
  if (zone === 'FER') return s.kind === 'IRS' ? [`irs:${Number(s.id.slice(-2))}`] : ['ferm'];
  if (zone === 'DRY') return ['drier'];
  if (zone === 'ENV') return ['env'];
  return [];
}

export function keysForEntity(id) {
  if (S.sensors[id]) return keysForSensor(S.sensors[id]);
  const d = S.devices[id];
  if (!d) return [];
  if (d.point) return [`weigh:${d.point}`];
  return [...new Set(Object.values(S.sensors).filter(s => s.device_id === id).flatMap(keysForSensor))];
}

const ELEMENT_ID = k => {
  const [a, b] = k.split(':');
  return { trough: `tr-${b}`, roller: `rol-${b}`, irs: `irs-${b}`, weigh: `w-${b}`, ferm: 'ferm', drier: 'drier', env: 'env' }[a];
};

// ---- live update ---------------------------------------------------------------

const val = (sid, key) => reading(sid, key)?.value;
const setT = (id, text) => { const el = document.getElementById(id); if (el && el.textContent !== text) el.textContent = text; };

function lamp(id, net, max, amberPct) {
  const el = document.getElementById(id);
  if (!el) return;
  let c = '#26333B';
  if (net != null && max) c = net > max ? 'var(--alarm)' : net > max * (1 - (amberPct ?? 5) / 100) ? 'var(--warn)' : 'var(--run)';
  el.setAttribute('fill', c);
}

export function updateMimic() {
  if (!$('.mimic-svg')) return;
  // troughs
  for (let t = 1; t <= 11; t++) {
    const z = `TF01-U-TR${pad2(t)}`;
    const amp = val(`${z}-CTS01`, 'amp'), run = val(`${z}-CTS01`, 'run');
    const fan = document.getElementById(`fan-${t}`);
    if (fan) fan.setAttribute('class', `fan ${run == null ? '' : run ? 'run' : 'stop'}`);
    const pl = val(`${z}-THS01`, 't_c');
    const leaf = [val(`${z}-THS02`, 'rh_pct'), val(`${z}-THS03`, 'rh_pct')].filter(v => v != null);
    const rh = leaf.length ? leaf.reduce((a, b) => a + b) / leaf.length : null;
    setT(`trt-${t}`, `plenum ${fmt(pl)} °C · leaf ${fmt(rh, 0)} % RH · fan ${fmt(amp)} A`);
    for (let a = 1; a <= 8; a++) {
      const el = document.getElementById(`ar-${t}-${a}`);
      if (!el) continue;
      const cyc = S.areas.find(x => x.trough_no === t && x.area_no === a);
      const cls = !cyc ? 'empty' : cyc.bw_kg > 0 ? 'unloading' : 'loaded';
      el.setAttribute('class', `fp-area ${cls}`);
      el.setAttribute('fill', cls === 'empty' ? '#1A2228' : cls === 'unloading' ? '#5E5A2E' : '#3F7A5A');
      el.querySelector('title').textContent = cyc
        ? `T${t}-A${a}: ${fmt(cyc.n_kg, 0)} kg green from ${cyc.suppliers.map(s => s.supplier_id).join(', ')}${cyc.bw_kg > 0 ? `; ${fmt(cyc.bw_kg, 1)} kg withered out so far` : ''}`
        : `T${t}-A${a}: empty`;
    }
  }
  const envT = val('TF01-G-ENV-THS01', 't_c'), envH = val('TF01-G-ENV-THS01', 'rh_pct');
  setT('envv', `${fmt(envT)} °C · ${fmt(envH, 0)} % RH`);
  // weigh points: last event
  const ev = id => S.lastEvent[id]?.event;
  const a = ev('TF01-U-RCV-SCB01');
  setT('wA', a ? `${fmt(a.net_kg)} kg` : '–');
  setT('wA2', a ? a.supplier_id : 'last sack');
  setT('wA3', a ? `to T${a.trough_no}-A${a.area_no}` : '');
  const b = ev('TF01-U-WWB-SCB01');
  const bSet = S.settings['TF01-U-WWB-SCB01']?.desired || {};
  const bCrate = b?.type === 'crate_weighed' ? b : null;
  setT('wB', bCrate ? `${fmt(bCrate.net_kg)} kg` : '–');
  setT('wB2', `${bCrate ? `T${bCrate.trough_no}-A${bCrate.area_no}${bCrate.over_limit ? ' · OVER, re-weigh' : ''} · ` : ''}max ${fmt(bSet.max_limit_kg)} kg`);
  lamp('lampB', bCrate?.net_kg, bSet.max_limit_kg, bSet.amber_pct);
  for (const n of [1, 2, 3, 4]) {
    const w = ev(`TF01-L-RW${n}-SCB01`);
    setT(`wW${n}`, w ? fmt(w.net_kg, 0) : '–');
  }
  const d = ev('TF01-L-DRO-SCB01'), dSet = S.settings['TF01-L-DRO-SCB01']?.desired || {};
  setT('wD', d ? `${fmt(d.net_kg)} kg` : '–');
  setT('wD2', `max ${fmt(dSet.max_limit_kg)} kg`);
  lamp('lampD', d?.net_kg, dSet.max_limit_kg, dSet.amber_pct);
  // rollers
  for (const [z] of ROLLERS) {
    const amp = val(`TF01-L-${z}-CTS01`, 'amp');
    setT(`rolT-${z}`, `${fmt(val(`TF01-L-${z}-THS01`, 't_c'))} °C`);
    setT(`rolA-${z}`, `${fmt(amp)} A`);
    const g = document.getElementById(`rol-${z}`);
    if (g) g.classList.toggle('stop', amp != null && amp < 1);
  }
  // fermentation
  const room = [1, 2, 3].map(n => `TF01-L-FER-THH0${n}`);
  const avg = k => { const v = room.map(s => val(s, k)).filter(x => x != null); return v.length ? v.reduce((p, q) => p + q) / v.length : null; };
  setT('fermRoom', `Room ${fmt(avg('t_c'))} °C`);
  setT('fermRoom2', `${fmt(avg('rh_pct'), 0)} % RH (3 probes)`);
  for (let n = 1; n <= 8; n++) {
    const t = val(`TF01-L-FER-IRS0${n}`, 't_c');
    setT(`irsT-${n}`, `${fmt(t)}°`);
    const c = document.getElementById(`irsc-${n}`);
    if (c && t != null) {
      const p = Math.max(0, Math.min(1, (t - 24) / 8)); // 24 °C -> 32 °C
      c.setAttribute('fill', `rgb(${Math.round(62 + p * 120)},${Math.round(53 + p * 20)},${Math.round(41 - p * 10)})`);
    }
  }
  setT('dIn', `${fmt(val('TF01-L-DRY-TCK01', 't_c'), 0)} °C`);
  setT('dOut', `${fmt(val('TF01-L-DRY-TCK02', 't_c'), 0)} °C`);
  setT('dEx', `${fmt(val('TF01-L-DRY-TCK03', 't_c'), 0)} °C`);
  setT('dMot', `${fmt(val('TF01-L-DRY-CTS01', 'amp'))} A`);
  markAlarms();
}

export function markAlarms() {
  $$('.is-alarm,.is-warn,.is-offline').forEach(e => e.classList.remove('is-alarm', 'is-warn', 'is-offline'));
  for (const al of Object.values(S.alarms)) {
    for (const k of keysForEntity(al.entity_id)) {
      const el = document.getElementById(ELEMENT_ID(k));
      if (el) el.classList.add(al.severity === 'warning' ? 'is-warn' : 'is-alarm');
    }
  }
  for (const d of Object.values(S.devices)) {
    if (d.online || !d.last_seen) continue;
    for (const k of keysForEntity(d.id)) document.getElementById(ELEMENT_ID(k))?.classList.add('is-offline');
  }
}

export function markSelected(sel) {
  $$('.is-sel').forEach(e => e.classList.remove('is-sel'));
  if (sel) $$(`[data-sel="${sel}"]`).forEach(e => e.classList.add('is-sel'));
}

// ---- what a selection shows -------------------------------------------------------

// Returns {title, kind, sensors: [{id, keys}], devices: [ids], extra: html}
export function describe(sel) {
  const [k, a, b] = sel.split(':');
  const sensorsOf = asset => (S.bySensorAsset[asset] || []).filter(s => s.measuring);
  const devOfSensors = list => [...new Set(list.map(s => s.device_id))];
  if (k === 'trough' || k === 'area') {
    const t = Number(a), list = sensorsOf(`TF01-U-TR${pad2(t)}`);
    let extra = '';
    const cycles = S.areas.filter(x => x.trough_no === t && (k === 'trough' || x.area_no === Number(b)));
    extra = cycles.length
      ? `<div class="tbl-wrap"><table><tr><th>Area</th><th class="n">Green kg</th><th class="n">Withered kg</th><th>Suppliers</th></tr>${cycles.map(c =>
        `<tr><td>A${c.area_no}</td><td class="n">${fmt(c.n_kg, 0)}</td><td class="n">${c.bw_kg > 0 ? fmt(c.bw_kg) : '–'}</td><td>${c.suppliers.map(s => esc(s.supplier_id)).join(', ')}</td></tr>`).join('')}</table></div>`
      : '<p class="note">No leaf loaded.</p>';
    return { title: k === 'area' ? `Trough ${t}, area ${b}` : `Trough ${t}`, kind: 'Withering trough', sensors: list, devices: devOfSensors(list), extra };
  }
  if (k === 'roller') { const list = sensorsOf(`TF01-L-${a}`); return { title: a, kind: 'Roller', sensors: list, devices: devOfSensors(list) }; }
  if (k === 'irs') { const s = S.sensors[`TF01-L-FER-IRS0${a}`]; return { title: `Leaf surface spot ${a}`, kind: 'Fermentation', sensors: [s], devices: [s.device_id] }; }
  if (k === 'ferm') { const list = sensorsOf('TF01-L-FER').filter(s => s.kind === 'THH'); return { title: 'Fermentation room', kind: 'Fermentation', sensors: list, devices: ['TF01-L-FER-NOD01', 'TF01-L-FER-NOD02'] }; }
  if (k === 'drier') { const list = sensorsOf('TF01-L-DRY'); return { title: 'Drier', kind: 'Drying', sensors: list, devices: devOfSensors(list) }; }
  if (k === 'env') { const list = sensorsOf('TF01-G-ENV'); return { title: 'Outdoor air', kind: 'Ambient', sensors: list, devices: devOfSensors(list) }; }
  if (k === 'weigh') {
    const dev = Object.values(S.devices).find(d => d.point === a);
    const e = S.lastEvent[dev.id];
    const rows = e ? Object.entries(e.event).filter(([key]) => !['msg_id', 'ts'].includes(key)) : [];
    const extra = e ? `<div class="sp-sec">Last event, ${esc(e.event.type)}</div><dl class="rd">${rows.map(([key, v]) => `<dt>${esc(key)}</dt><dd>${esc(typeof v === 'object' ? JSON.stringify(v) : v)}</dd>`).join('')}</dl>`
      : '<p class="note">No weighing since this page opened.</p>';
    return { title: `${dev.name}`, kind: `Weigh point ${a}`, sensors: [], devices: [dev.id], extra };
  }
  return { title: sel, kind: '', sensors: [], devices: [] };
}
