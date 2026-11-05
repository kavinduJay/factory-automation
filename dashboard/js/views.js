// Page views. Each returns {html, bind(root), update(kinds)?}.
import { api } from './api.js';
import { lineChart, spark } from './chart.js';
import { describe, keysForEntity, lowerSVG, markSelected, updateMimic, upperSVG } from './mimic.js';
import { S, can, inSync, openAlarms, reading } from './store.js';
import { $, $$, ago, colomboDate, dateTime, esc, fmt, sevClass, throttle, time, toast } from './util.js';

const UNITS = { t_c: '°C', rh_pct: '% RH', amp: 'A', run: '' };
const KEY_LABEL = { t_c: 'Temperature', rh_pct: 'Humidity', amp: 'Current', run: 'Running' };
export const ui = { floor: 'both', sel: null, go: null };

// ---- shared pieces ----------------------------------------------------------------

export function alarmHTML(a) {
  const keys = keysForEntity(a.entity_id);
  return `<button class="al ${sevClass(a.severity)}" data-alarm="${a.id}" ${keys[0] ? `data-goto="${keys[0]}"` : ''}>
    <div><b>${esc(a.message || a.type)}</b><span>${esc(a.severity)} · ${esc(a.entity_id)} · since ${time(a.started_at)}${a.status === 'acked' ? ` · acked by ${esc(a.acked_by)}` : ''}</span></div></button>`;
}

function bindAlarmClicks(root) {
  $$('[data-goto]', root).forEach(b => b.addEventListener('click', () => { ui.sel = b.dataset.goto; ui.go('overview'); }));
}

function err(e) { toast(e.message || String(e), 'bad'); }

function table(cols, rows, { rowAttr = () => '', empty = 'Nothing yet.' } = {}) {
  if (!rows.length) return `<p class="note">${empty}</p>`;
  return `<div class="tbl-wrap"><table><tr>${cols.map(c => `<th class="${c.n ? 'n' : ''}">${c.h}</th>`).join('')}</tr>${rows.map(r =>
    `<tr ${rowAttr(r)}>${cols.map(c => `<td class="${c.n ? 'n' : ''}">${c.f(r)}</td>`).join('')}</tr>`).join('')}</table></div>`;
}

function dialog(html, onSubmit) {
  const d = document.createElement('dialog');
  d.innerHTML = `<form method="dialog">${html}<p class="err" data-err></p><div class="btns"><button class="btn" value="ok">Save</button><button class="btn ghost" value="cancel" formnovalidate>Cancel</button></div></form>`;
  document.body.append(d);
  d.addEventListener('close', () => d.remove());
  d.querySelector('form').addEventListener('submit', async e => {
    if (e.submitter?.value === 'cancel') return;
    e.preventDefault();
    try { await onSubmit(new FormData(e.target), d); d.close(); } catch (x) { d.querySelector('[data-err]').textContent = x.message; }
  });
  d.showModal();
  return d;
}

// ---- overview -------------------------------------------------------------------------

let summary = null;
async function loadSummary() { try { summary = await api('/summary'); } catch (e) { /* shown as – */ } }

function kpis() {
  const devs = Object.values(S.devices), on = devs.filter(d => d.online).length;
  const al = openAlarms(), bad = al.filter(a => a.severity !== 'warning').length;
  const k = (v, l, cls = '') => `<div class="kpi ${cls}"><div class="v">${v}</div><div class="l">${l}</div></div>`;
  return k(`${on}/${devs.length}`, 'Devices online', on < devs.length ? 'bad' : '') +
    k(al.length, `Open alarms${bad ? `, ${bad} major or worse` : ''}`, bad ? 'bad' : '') +
    k(`${S.areas.length}/88`, 'Trough areas loaded') +
    k(summary ? fmt(summary.green_leaf_kg, 0) : '–', 'Green leaf today, kg') +
    k(summary ? fmt(summary.withered_kg, 0) : '–', 'Withered today, kg') +
    k(summary ? summary.batches : '–', 'Batches opened today') +
    k(summary ? fmt(summary.made_tea_kg, 0) : '–', 'Made tea today, kg');
}

async function sidePanel() {
  const el = $('#side');
  if (!el) return;
  el.classList.toggle('open', !!ui.sel);
  markSelected(ui.sel);
  if (!ui.sel) { el.innerHTML = '<p class="note">Select a trough, area, roller, weigh point or zone on the plan to see its readings, trends and alarms.</p>'; return; }
  const d = describe(ui.sel);
  const sensorIds = new Set(d.sensors.map(s => s.id));
  const alarms = openAlarms().filter(a => sensorIds.has(a.entity_id) || d.devices.includes(a.entity_id));
  const rows = d.sensors.map(s => {
    const r = S.readings[s.id] || {};
    return Object.entries(r).filter(([k]) => k !== 'run').map(([k, v]) =>
      `<dt>${esc(s.name)} <span class="tag">${esc(k)}</span></dt><dd>${fmt(v.value)} ${UNITS[k] || ''}</dd>`).join('');
  }).join('');
  el.innerHTML = `<div class="sp-head"><div><div class="sp-kind">${esc(d.kind)}</div><h2>${esc(d.title)}</h2></div><button class="xbtn" data-close>Close</button></div>
    ${rows ? `<dl class="rd">${rows}</dl>` : ''}${d.extra || ''}
    <div class="ids">${d.devices.map(id => { const dv = S.devices[id]; return `<span class="${dv?.online ? '' : 'offline'}" title="${dv?.online ? 'online' : 'offline'}, last seen ${ago(dv?.last_seen)}">${esc(id)}</span>`; }).join('')}</div>
    ${alarms.length ? `<div class="sp-sec">Alarms</div>${alarms.map(alarmHTML).join('')}` : '<div class="sp-sec">No open alarms here.</div>'}
    <div id="sp-charts"></div>`;
  el.querySelector('[data-close]').addEventListener('click', () => { ui.sel = null; sidePanel(); });
  // last hour per sensor and key
  const charts = el.querySelector('#sp-charts');
  const wanted = d.sensors.slice(0, 4);
  if (!wanted.length) return;
  try {
    const h = await api('/history', { params: { sensor_id: wanted.map(s => s.id).join(','), from: new Date(Date.now() - 3600e3).toISOString() } });
    if (describe(ui.sel).title !== d.title) return; // selection changed meanwhile
    charts.innerHTML = h.series.filter(s => s.key !== 'run').map((s, i) =>
      `<div class="chart-title">${esc(S.sensors[s.sensor_id]?.name)} · ${KEY_LABEL[s.key] || s.key}, last hour</div><div data-c="${i}"></div>`).join('');
    h.series.filter(s => s.key !== 'run').forEach((s, i) => lineChart(charts.querySelector(`[data-c="${i}"]`), s.points, { unit: UNITS[s.key] }));
  } catch (e) { charts.innerHTML = `<p class="err">${esc(e.message)}</p>`; }
}

function overview() {
  loadSummary().then(() => { const k = $('#kpis'); if (k) k.innerHTML = kpis(); });
  const al = openAlarms();
  return {
    html: `<div class="kpis" id="kpis">${kpis()}</div>
      <div class="ov"><section class="panel mimic"><div class="mimic-head">
        <div class="seg" role="group" aria-label="Floor">${[['both', 'Both floors'], ['upper', 'Upper'], ['lower', 'Lower']].map(([k, l]) =>
          `<button data-floor="${k}" aria-pressed="${ui.floor === k}">${l}</button>`).join('')}</div>
        <div class="legend"><span><span class="sw" style="background:#3F7A5A"></span>Area loaded</span><span><span class="sw" style="background:#5E5A2E"></span>Unloading at B</span>
          <span><span class="sw" style="background:#1A2228;border:1px solid var(--line2)"></span>Empty</span><span><span class="sw" style="background:var(--alarm)"></span>Alarm</span></div></div>
        <div class="floors ${ui.floor}"><figure class="floor fl-upper"><figcaption>Upper floor: intake and withering</figcaption>${upperSVG()}</figure>
        <figure class="floor fl-lower"><figcaption>Lower floor: rolling, fermentation and drying</figcaption>${lowerSVG()}</figure></div></section>
        <aside class="panel side-p" id="side" aria-live="polite"></aside>
        <section class="panel alstrip" id="alstrip"></section></div>`,
    bind(root) {
      $$('[data-floor]', root).forEach(b => b.addEventListener('click', () => {
        ui.floor = b.dataset.floor;
        $$('[data-floor]', root).forEach(x => x.setAttribute('aria-pressed', x === b));
        $('.floors', root).className = `floors ${ui.floor}`;
      }));
      $$('[data-sel]', root).forEach(g => g.addEventListener('click', e => { e.stopPropagation(); ui.sel = g.dataset.sel; sidePanel(); }));
      updateMimic(); sidePanel(); alStrip();
    },
    update(kinds) {
      updateMimic();
      if (kinds.has('alarm') || kinds.has('device') || kinds.has('all')) { alStrip(); const k = $('#kpis'); if (k) k.innerHTML = kpis(); }
      if (kinds.has('event')) loadSummaryThrottled();
    },
  };
}
let lastSummary = 0;
function loadSummaryThrottled() {
  if (Date.now() - lastSummary < 10000) return;
  lastSummary = Date.now();
  loadSummary().then(() => { const k = $('#kpis'); if (k) k.innerHTML = kpis(); });
}
function alStrip() {
  const el = $('#alstrip'); if (!el) return;
  const L = openAlarms();
  el.innerHTML = `<h2>Open alarms <span class="note">(${L.length})</span></h2>` +
    (L.length ? `<div class="al-row">${L.map(alarmHTML).join('')}</div>` : '<p class="note">Everything is within limits.</p>');
  bindAlarmClicks(el);
}

// ---- weighings -----------------------------------------------------------------------

const KINDS = {
  sack: { label: 'Sacks at A', cols: [
    { h: 'Time', f: r => dateTime(r.ts) }, { h: 'Supplier', f: r => esc(r.supplier_id) }, { h: 'Seq', n: 1, f: r => r.sack_seq ?? '' },
    { h: 'Gross', n: 1, f: r => fmt(r.gross_kg) }, { h: 'Deductions', n: 1, f: r => fmt(Number(r.sack_tare_kg) + Number(r.wet_deduction_kg) + Number(r.coarse_deduction_kg)) },
    { h: 'Net kg', n: 1, f: r => `<b>${fmt(r.net_kg)}</b>` }, { h: 'Area', f: r => `T${r.trough_no}-A${r.area_no}` }, { h: 'Maturity', f: r => esc(r.maturity || '') }] },
  crate: { label: 'Crates at B', cols: [
    { h: 'Time', f: r => dateTime(r.ts) }, { h: 'Area', f: r => `T${r.trough_no}-A${r.area_no}` }, { h: 'Crate', f: r => esc(r.crate_id || '') },
    { h: 'Net kg', n: 1, f: r => `<b>${fmt(r.net_kg)}</b>` }, { h: 'Limit', n: 1, f: r => fmt(r.max_limit_kg) }, { h: 'Batch', f: r => batchLink(r.batch_id) }] },
  stage: { label: 'Rolling W1–W4', cols: [
    { h: 'Time', f: r => dateTime(r.ts) }, { h: 'Batch', f: r => batchLink(r.batch_id) }, { h: 'Stage', f: r => `W${r.stage}${r.bulk ? ' <span class="tag">bulk</span>' : ''}` },
    { h: 'Net kg', n: 1, f: r => `<b>${fmt(r.net_kg)}</b>` }] },
  drier: { label: 'Made tea at D', cols: [
    { h: 'Time', f: r => dateTime(r.ts) }, { h: 'Batch', f: r => `${batchLink(r.batch_id)}${r.batch_assigned !== 'device' ? ` <span class="tag">${esc(r.batch_assigned)}</span>` : ''}` },
    { h: 'Net kg', n: 1, f: r => `<b>${fmt(r.net_kg)}</b>` }, { h: 'Moisture %', n: 1, f: r => fmt(r.moisture_pct) }] },
};
const CORRECTABLE = {
  sack: ['supplier_id', 'gross_kg', 'sack_tare_kg', 'wet_deduction_kg', 'coarse_deduction_kg', 'net_kg', 'maturity'],
  crate: ['net_kg', 'gross_kg', 'tare_kg', 'crate_id', 'batch_id'],
  stage: ['net_kg', 'stage', 'bulk', 'batch_id'],
  drier: ['net_kg', 'moisture_pct', 'batch_id'],
};
const batchLink = id => id ? `<a href="#/batches/${encodeURIComponent(id)}">${esc(id)}</a>` : '<span class="tag warn">no batch</span>';

function weighings(kind = 'crate') {
  if (!KINDS[kind]) kind = 'crate';
  let rows = [], history = false;
  const render = () => {
    const el = $('#wtable'); if (!el) return;
    const cols = [...KINDS[kind].cols];
    if (history) cols.push({ h: 'Record', f: r => r.corrects_id ? `correction of #${r.corrects_id}${r.voided ? ' <span class="tag bad">void</span>' : ''}<br><span class="note">${esc(r.reason)} · ${esc(r.created_by)}</span>` : `#${r.id}` });
    else cols.push({ h: '', f: r => `${r.original_id !== r.id ? '<span class="tag warn">corrected</span>' : ''}${can.configure() ? ` <button class="btn ghost sm" data-fix="${r.id}">Correct</button>` : ''}` });
    el.innerHTML = table(cols, rows, { rowAttr: r => r.voided ? 'class="voided"' : '', empty: 'No weighings yet.' });
    $$('[data-fix]', el).forEach(b => b.addEventListener('click', () => correct(kind, rows.find(r => String(r.id) === b.dataset.fix), load)));
  };
  const load = async () => {
    try { rows = await api(`/weighings/${kind}`, { params: { history, limit: 300 } }); render(); } catch (e) { err(e); }
  };
  const slow = throttle(load, 5000);
  return {
    html: `<div class="tabs">${Object.entries(KINDS).map(([k, v]) => `<a class="btn ${k === kind ? '' : 'ghost'} sm" href="#/weighings/${k}">${v.label}</a>`).join('')}
      <label class="toggle" style="margin:0 0 0 auto"><input type="checkbox" id="whist"> Show originals and corrections</label></div>
      <div class="panel"><p class="note">Weighings are never changed. A correction is stored as a new record that points at the original, with a reason; reports use the latest correction.</p><div id="wtable"><p class="note">Loading…</p></div></div>`,
    bind(root) { $('#whist', root).addEventListener('change', e => { history = e.target.checked; load(); }); load(); },
    update(kinds) { if (kinds.has('event') || kinds.has('correction')) slow(); },
  };
}

function correct(kind, row, done) {
  const fields = CORRECTABLE[kind];
  dialog(`<h2>Correct ${kind} weighing #${row.original_id ?? row.id}</h2>
    <p class="note">${dateTime(row.ts)}. Change only what was wrong.</p>
    <div class="row">${fields.map(f => f === 'bulk'
      ? `<label class="f">${f}<select name="${f}"><option value="">unchanged</option><option value="true">true</option><option value="false">false</option></select></label>`
      : `<label class="f">${f}<input type="text" name="${f}" placeholder="${esc(row[f] ?? '')}"></label>`).join('')}</div>
    <label class="toggle"><input type="checkbox" name="voided"> Void this weighing (remove it from reports)</label>
    <label class="f">Reason (required)<textarea name="reason" required minlength="3"></textarea></label>`,
  async fd => {
    const changes = {};
    for (const f of fields) {
      const v = fd.get(f);
      if (v === null || v === '') continue;
      changes[f] = f === 'bulk' ? v === 'true' : ['supplier_id', 'batch_id', 'crate_id', 'maturity'].includes(f) ? v : Number(v);
      if (typeof changes[f] === 'number' && Number.isNaN(changes[f])) throw new Error(`${f} must be a number`);
    }
    await api(`/weighings/${kind}/${row.id}/correct`, { method: 'POST', body: { changes, voided: fd.get('voided') === 'on', reason: fd.get('reason') } });
    toast('Correction saved');
    done();
  });
}

// ---- batches ----------------------------------------------------------------------------

function batches(id) {
  if (id) return batchDetail(decodeURIComponent(id));
  let rows = [];
  const slow = throttle(() => load(), 5000);
  const load = async () => {
    try {
      rows = await api('/batches', { params: { limit: 100 } });
      $('#btable').innerHTML = table([
        { h: 'Batch', f: r => batchLink(r.batch_id) }, { h: 'Opened', f: r => dateTime(r.opened_at) }, { h: 'Status', f: r => esc(r.status) },
        { h: 'Wz', n: 1, f: r => fmt(r.wz_kg, 0) }, { h: 'W1', n: 1, f: r => fmt(r.w1_kg, 0) }, { h: 'W2', n: 1, f: r => fmt(r.w2_kg, 0) },
        { h: 'W3', n: 1, f: r => fmt(r.w3_kg, 0) }, { h: 'W4', n: 1, f: r => fmt(r.w4_kg, 0) }, { h: 'Made tea', n: 1, f: r => fmt(r.made_tea_kg, 0) },
        { h: 'Out-turn', n: 1, f: r => r.out_turn_pct != null ? `${fmt(r.out_turn_pct)} %` : '–' },
        { h: '', f: r => r.warnings.map(w => `<span class="tag warn">${esc(w)}</span>`).join('') }], rows, { empty: 'No batches yet.' });
    } catch (e) { err(e); }
  };
  return {
    html: `<div class="panel"><p class="note">Wz is the withered leaf from B in the batch; W1–W4 is what continued after each sieving. Out-turn = made tea ÷ green leaf.</p><div id="btable"><p class="note">Loading…</p></div></div>`,
    bind: load,
    update(kinds) { if (kinds.has('event') || kinds.has('correction')) slow(); },
  };
}

function batchDetail(id) {
  const load = async () => {
    const el = $('#bdetail'); if (!el) return;
    try {
      const b = await api(`/batches/${encodeURIComponent(id)}`);
      const st = (lbl, w, ws, bad) => `<div class="stage ${bad ? 'bad' : ''}"><div class="note">${lbl}</div><div class="v" style="font-size:24px;font-weight:700">${fmt(w, 1)} kg</div>${ws != null ? `<div class="ws">dhool ${fmt(ws, 1)} kg</div>` : ''}</div>`;
      el.innerHTML = `<div class="panel"><h2>${esc(b.batch_id)} <span class="tag">${esc(b.status)}</span>${b.warnings.map(w => `<span class="tag warn">${esc(w)}</span>`).join('')}</h2>
        <p class="note">Opened ${dateTime(b.opened_at)} · ${b.crates} crates · ${b.suppliers} suppliers · bulk at W${b.bulk_stage ?? '?'} · fermentation ${dateTime(b.fermentation_start)} to ${dateTime(b.fermentation_end)}</p>
        <div class="stages">${st('Wz (from B)', b.wz_kg)}${st('W1', b.w1_kg, b.ws1_kg, b.warnings.includes('W1 > Wz'))}${st('W2', b.w2_kg, b.ws2_kg, b.warnings.includes('W2 > W1'))}
          ${st('W3', b.w3_kg, b.ws3_kg, b.warnings.includes('W3 > W2'))}${b.w4_kg != null ? st('W4', b.w4_kg, b.ws4_kg, b.warnings.includes('W4 > W3')) : ''}</div>
        <div class="kpis" style="margin-top:12px"><div class="kpi"><div class="v">${fmt(b.green_leaf_kg, 0)}</div><div class="l">Green leaf, kg</div></div>
          <div class="kpi"><div class="v">${fmt(b.made_tea_kg, 1)}</div><div class="l">Made tea, kg (${b.drier_loads} loads)</div></div>
          <div class="kpi"><div class="v">${b.out_turn_pct != null ? fmt(b.out_turn_pct) + ' %' : '–'}</div><div class="l">Out-turn</div></div></div>
        ${can.configure() ? '<div class="btns"><button class="btn ghost sm" id="bedit">Edit status or notes</button></div>' : ''}</div>
        <div class="panel"><h2>Supplier attribution</h2><p class="note">Share = supplier's withered weight ÷ Wz. Made tea per supplier is always an estimate; withered weight is estimated when an area held more than one supplier.</p>
        ${table([{ h: 'Supplier', f: r => esc(r.supplier_id) }, { h: 'Green leaf kg', n: 1, f: r => fmt(r.green_leaf_kg) }, { h: 'Withered kg', n: 1, f: r => `${fmt(r.bw_kg)}${r.bw_estimated ? ' *' : ''}` },
          { h: 'Share', n: 1, f: r => `${fmt(r.share_pct)} %` }, { h: 'Made tea kg (est.)', n: 1, f: r => fmt(r.made_tea_kg) }], b.suppliers, { empty: 'No crates in this batch yet.' })}</div>
        <div class="grid2"><div class="panel"><h2>Rolling weighings</h2>${table([{ h: 'Time', f: r => time(r.ts) }, { h: 'Stage', f: r => `W${r.stage}${r.bulk ? ' bulk' : ''}` }, { h: 'kg', n: 1, f: r => fmt(r.net_kg) }], b.stages)}</div>
        <div class="panel"><h2>Made tea at D</h2>${table([{ h: 'Time', f: r => time(r.ts) }, { h: 'kg', n: 1, f: r => fmt(r.net_kg) }, { h: 'Moisture', n: 1, f: r => fmt(r.moisture_pct) }], b.drier)}</div></div>`;
      $('#bedit')?.addEventListener('click', () => dialog(`<h2>Edit ${esc(b.batch_id)}</h2>
        <label class="f">Status<select name="status">${['withered', 'rolling', 'fermenting', 'drying', 'done'].map(s => `<option ${s === b.status ? 'selected' : ''}>${s}</option>`).join('')}</select></label>
        <label class="f">Notes<textarea name="notes">${esc(b.notes || '')}</textarea></label><label class="f">Reason<input type="text" name="reason"></label>`,
      async fd => { await api(`/batches/${encodeURIComponent(id)}`, { method: 'PATCH', body: { status: fd.get('status'), notes: fd.get('notes'), reason: fd.get('reason') || null } }); load(); }));
    } catch (e) { el.innerHTML = `<p class="err">${esc(e.message)}</p>`; }
  };
  const slow = throttle(load, 5000);
  return { html: `<p><a href="#/batches">← All batches</a></p><div class="stack" id="bdetail"><p class="note">Loading…</p></div>`, bind: load,
    update(kinds) { if (kinds.has('event') || kinds.has('correction')) slow(); } };
}

// ---- reports ------------------------------------------------------------------------------

function reports(tab = 'moisture') {
  const today = colomboDate(), weekAgo = colomboDate(new Date(Date.now() - 6 * 864e5));
  const load = async () => {
    const el = $('#rep'); if (!el) return;
    try {
      if (tab === 'moisture') {
        const rows = await api('/reports/moisture-loss', { params: { from: $('#rfrom').value, to: $('#rto').value } });
        el.innerHTML = table([{ h: 'Day', f: r => r.day }, { h: 'Supplier', f: r => esc(r.supplier_id) }, { h: 'Areas', n: 1, f: r => r.areas },
          { h: 'Received N kg', n: 1, f: r => fmt(r.n_kg) }, { h: 'Withered kg', n: 1, f: r => `${fmt(r.bw_kg)}${r.estimated ? ' *' : ''}` },
          { h: 'Moisture loss', n: 1, f: r => `<b>${fmt(r.moisture_loss_pct)} %</b>` }], rows, { empty: 'No fully unloaded areas in this range.' }) +
          '<p class="note">Only areas fully unloaded at B. * estimated: the area held more than one supplier, so withered weight is split by received weight.</p>';
      } else if (tab === 'suppliers') {
        const rows = await api('/reports/supplier-attribution', { params: { limit: 500 } });
        el.innerHTML = table([{ h: 'Batch', f: r => batchLink(r.batch_id) }, { h: 'Opened', f: r => dateTime(r.opened_at) }, { h: 'Supplier', f: r => esc(r.supplier_id) },
          { h: 'Withered kg', n: 1, f: r => `${fmt(r.bw_kg)}${r.bw_estimated ? ' *' : ''}` }, { h: 'Share', n: 1, f: r => `${fmt(r.share_pct)} %` },
          { h: 'Made tea kg (est.)', n: 1, f: r => fmt(r.made_tea_kg) }], rows, { empty: 'No batches yet.' });
      } else {
        const rows = await api('/reports/areas', { params: { limit: 300 } });
        el.innerHTML = table([{ h: 'Area', f: r => `T${r.trough_no}-A${r.area_no}` }, { h: 'Loaded', f: r => dateTime(r.loaded_at) }, { h: 'Unloaded', f: r => dateTime(r.unloaded_at) },
          { h: 'Sacks', n: 1, f: r => r.sacks }, { h: 'N kg', n: 1, f: r => fmt(r.n_kg) }, { h: 'Crates', n: 1, f: r => r.crates }, { h: 'Bw kg', n: 1, f: r => fmt(r.bw_kg) },
          { h: 'Loss', n: 1, f: r => r.moisture_loss_pct != null ? `${fmt(r.moisture_loss_pct)} %` : '–' }, { h: 'Suppliers', n: 1, f: r => r.suppliers }], rows);
      }
    } catch (e) { err(e); }
  };
  const tabs = [['moisture', 'Moisture loss per supplier'], ['suppliers', 'Supplier share of batches'], ['areas', 'Area cycles']];
  return {
    html: `<div class="tabs">${tabs.map(([k, l]) => `<a class="btn ${k === tab ? '' : 'ghost'} sm" href="#/reports/${k}">${l}</a>`).join('')}</div>
      <div class="panel">${tab === 'moisture' ? `<div class="row" style="max-width:420px;margin-bottom:12px"><label class="f">From<input type="date" id="rfrom" value="${weekAgo}"></label><label class="f">To<input type="date" id="rto" value="${today}"></label></div>` : ''}
      <div id="rep"><p class="note">Loading…</p></div></div>`,
    bind(root) { $$('input[type=date]', root).forEach(i => i.addEventListener('change', load)); load(); },
  };
}

// ---- alarms --------------------------------------------------------------------------------

function alarmsView() {
  const load = async () => {
    const el = $('#alh'); if (!el) return;
    try {
      const rows = await api('/alarms', { params: { status: 'all', limit: 200 } });
      el.innerHTML = table([{ h: 'Started', f: r => dateTime(r.started_at) }, { h: 'Severity', f: r => `<span class="tag ${r.severity === 'warning' ? 'warn' : 'bad'}">${esc(r.severity)}</span>` },
        { h: 'Alarm', f: r => esc(r.message || r.type) }, { h: 'Entity', f: r => esc(r.entity_id) }, { h: 'Status', f: r => esc(r.status) },
        { h: 'Acked', f: r => r.acked_by ? `${esc(r.acked_by)} ${time(r.acked_at)}` : '' }, { h: 'Cleared', f: r => dateTime(r.cleared_at) }], rows);
    } catch (e) { err(e); }
  };
  const slowHistory = throttle(() => load(), 3000);
  const openList = () => {
    const el = $('#alopen'); if (!el) return;
    const L = openAlarms();
    el.innerHTML = L.length ? L.map(a => `<div style="display:flex;gap:8px;align-items:flex-start">${alarmHTML(a)}${a.acked_at ? '' : `<button class="btn ghost sm" data-ack="${a.id}">Acknowledge</button>`}</div>`).join('') : '<p class="note">No open alarms.</p>';
    bindAlarmClicks(el);
    $$('[data-ack]', el).forEach(b => b.addEventListener('click', async () => {
      try { await api(`/alarms/${b.dataset.ack}/ack`, { method: 'POST' }); } catch (e) { err(e); }
    }));
  };
  return {
    html: `<div class="stack"><div class="panel"><h2>Open</h2><div id="alopen"></div></div><div class="panel"><h2>History</h2><div id="alh"><p class="note">Loading…</p></div></div></div>`,
    bind() { openList(); load(); },
    update(kinds) { if (kinds.has('alarm')) { openList(); slowHistory(); } },
  };
}

// ---- devices and settings -----------------------------------------------------------------

function devices(id) {
  if (id) return deviceDetail(decodeURIComponent(id));
  const render = () => {
    const el = $('#dtable'); if (!el) return;
    const rows = Object.values(S.devices);
    el.innerHTML = table([
      { h: 'Device', f: d => `<a href="#/devices/${d.id}">${esc(d.id)}</a>` }, { h: 'Name', f: d => esc(d.name) }, { h: 'Profile', f: d => esc(d.profile_id) },
      { h: 'Status', f: d => `<span class="dot ${d.online ? 'on' : d.last_seen ? 'off' : 'idle'}"></span>${d.online ? 'Online' : d.last_seen ? 'Offline' : 'Never seen'}` },
      { h: 'Last data', f: d => ago(d.last_seen) },
      { h: 'Settings', f: d => S.settings[d.id]?.reported ? (inSync(d.id) ? '<span class="tag good">applied</span>' : '<span class="tag warn">pending</span>') : '<span class="tag">not reported</span>' }], rows);
  };
  return { html: `<div class="panel"><div id="dtable"></div></div>`, bind: render, update: render };
}

function deviceDetail(id) {
  const load = async () => {
    const el = $('#ddetail'); if (!el) return;
    try {
      const d = await api(`/devices/${encodeURIComponent(id)}`);
      const client = Object.fromEntries(d.attributes.filter(a => a.scope === 'client').map(a => [a.key, a.value]));
      const st = d.settings;
      const measuring = d.sensors.filter(s => s.measuring);
      el.innerHTML = `<div class="grid2"><div class="panel"><h2>${esc(d.name)}</h2><dl class="rd">
          <dt>ID</dt><dd>${esc(d.id)}</dd><dt>Profile</dt><dd>${esc(d.profile_id)}</dd><dt>Status</dt><dd>${S.devices[id]?.online ? 'Online' : 'Offline'}</dd>
          <dt>Last data</dt><dd>${ago(S.devices[id]?.last_seen)}</dd><dt>Firmware</dt><dd>${esc(client.fw ?? '–')}</dd><dt>Wi-Fi</dt><dd>${client.rssi != null ? `${client.rssi} dBm` : '–'}</dd>
          ${d.point ? `<dt>Weigh point</dt><dd>${esc(d.point)}</dd>` : ''}</dl>
          <h2>Sensors and peripherals</h2>${table([{ h: 'ID', f: s => esc(s.id) }, { h: 'Kind', f: s => esc(s.kind) }, { h: 'Position', f: s => esc(s.position || '') },
            { h: 'Modbus', n: 1, f: s => s.modbus_addr ?? '' }, { h: 'Now', n: 1, f: s => Object.entries(S.readings[s.id] || {}).filter(([k]) => k !== 'run').map(([k, v]) => `${fmt(v.value)} ${UNITS[k] || ''}`).join(' · ') }], d.sensors, { empty: 'No sensors.' })}</div>
        <div class="panel"><h2>Settings <span id="sync">${st.in_sync ? '<span class="tag good">applied by device</span>' : '<span class="tag warn">waiting for device</span>'}</span></h2>
          <p class="note">Saved settings are pushed to the device as a retained message, so it also gets them after a reboot. The device reports back what it uses.</p>
          <form id="sform"><div class="row">${Object.entries(st.desired).map(([k, v]) => `<label class="f">${esc(k)}${typeof v === 'boolean'
            ? `<select name="${k}" ${can.configure() ? '' : 'disabled'}><option ${v ? 'selected' : ''}>true</option><option ${!v ? 'selected' : ''}>false</option></select>`
            : `<input type="${typeof v === 'number' ? 'number' : 'text'}" step="any" name="${k}" value="${esc(v)}" ${can.configure() ? '' : 'disabled'}>`}
            <span class="note">device: ${esc(st.reported?.[k] ?? '–')}</span></label>`).join('')}</div>
            ${can.configure() ? `<label class="f" style="margin-top:10px">Reason<input type="text" name="_reason" placeholder="optional"></label><div class="btns"><button class="btn">Save and send</button></div>` : '<p class="note">Your role can view settings but not change them.</p>'}</form></div></div>
        <div class="panel"><h2>Last 6 hours</h2><div id="dcharts" class="grid2"></div></div>`;
      $('#sform')?.addEventListener('submit', async e => {
        e.preventDefault();
        const fd = new FormData(e.target), changes = {};
        for (const [k, v] of Object.entries(st.desired)) {
          const raw = fd.get(k); if (raw === null) continue;
          const nv = typeof v === 'boolean' ? raw === 'true' : typeof v === 'number' ? Number(raw) : raw;
          if (nv !== v) changes[k] = nv;
        }
        if (!Object.keys(changes).length) { toast('Nothing changed'); return; }
        try { await api(`/devices/${encodeURIComponent(id)}/settings`, { method: 'PUT', body: { changes, reason: fd.get('_reason') || null } }); toast('Settings sent to the device'); load(); } catch (x) { err(x); }
      });
      if (measuring.length) {
        const h = await api('/history', { params: { sensor_id: measuring.map(s => s.id).join(','), from: new Date(Date.now() - 6 * 3600e3).toISOString(), resolution: '1m' } });
        const series = h.series.filter(s => s.key !== 'run');
        $('#dcharts').innerHTML = series.map((s, i) => `<div><div class="chart-title">${esc(S.sensors[s.sensor_id]?.name)} · ${KEY_LABEL[s.key] || s.key} (${UNITS[s.key]})</div><div data-c="${i}"></div></div>`).join('') || '<p class="note">No readings yet.</p>';
        series.forEach((s, i) => lineChart($(`[data-c="${i}"]`), s.points, { unit: UNITS[s.key] }));
      } else $('#dcharts').innerHTML = '<p class="note">Scale bridges send events, not telemetry. See Weighings.</p>';
    } catch (e) { el.innerHTML = `<p class="err">${esc(e.message)}</p>`; }
  };
  return { html: `<p><a href="#/devices">← All devices</a></p><div class="stack" id="ddetail"><p class="note">Loading…</p></div>`, bind: load,
    update(kinds) {
      if (!kinds.has('settings')) return;
      const s = $('#sync'); if (s) s.innerHTML = inSync(id) ? '<span class="tag good">applied by device</span>' : '<span class="tag warn">waiting for device</span>';
    } };
}

// ---- rules ---------------------------------------------------------------------------------

function rules() {
  const load = async () => {
    const el = $('#rules'); if (!el) return;
    try {
      const [rows, profiles] = await Promise.all([api('/rules'), api('/profiles')]);
      const cond = c => `${esc(c.sensor_kind)}${c.position ? `/${esc(c.position)}` : ''} ${esc(c.key)} ${esc(c.op)} ${esc(c.value)} for ${c.for_s ?? 0} s`;
      el.innerHTML = `<div class="panel"><h2>Rules</h2><p class="note">When-then rules stored as data. Applies to sensors under the scope asset and/or on devices of the scope profile.</p>
        ${table([{ h: 'Name', f: r => esc(r.name) }, { h: 'Scope', f: r => esc(r.scope_asset_id || r.scope_profile_id || 'all') }, { h: 'When', f: r => cond(r.condition) },
          { h: 'Then', f: r => `${esc(r.action.severity)} · ${esc(r.action.alarm_type)}` }, { h: 'Enabled', f: r => r.enabled ? 'yes' : 'no' },
          { h: '', f: r => can.configure() ? `<button class="btn ghost sm" data-edit="${r.id}">Edit</button> <button class="btn ghost sm" data-del="${r.id}">Delete</button>` : '' }], rows, { empty: 'No rules.' })}
        ${can.configure() ? '<div class="btns"><button class="btn" id="rnew">New rule</button></div>' : ''}</div>
        <div class="panel"><h2>Profile alarm rules</h2><p class="note">Built into device profiles (the extensibility point). Edited through the profile API.</p>
        ${table([{ h: 'Profile', f: r => esc(r.p) }, { h: 'Alarm', f: r => esc(r.type) }, { h: 'When', f: r => cond(r) }, { h: 'Severity', f: r => esc(r.severity) }],
          profiles.flatMap(p => p.alarm_rules.map(r => ({ ...r, p: p.id }))))}</div>`;
      $('#rnew')?.addEventListener('click', () => ruleForm(null, load));
      $$('[data-edit]', el).forEach(b => b.addEventListener('click', () => ruleForm(rows.find(r => String(r.id) === b.dataset.edit), load)));
      $$('[data-del]', el).forEach(b => b.addEventListener('click', async () => {
        if (!confirm('Delete this rule? Its open alarms are cleared.')) return;
        try { await api(`/rules/${b.dataset.del}`, { method: 'DELETE' }); load(); } catch (e) { err(e); }
      }));
    } catch (e) { err(e); }
  };
  return { html: '<div class="stack" id="rules"><p class="note">Loading…</p></div>', bind: load };
}

function ruleForm(r, done) {
  const c = r?.condition || { sensor_kind: 'IRS', key: 't_c', op: '>', value: 30, for_s: 300, hysteresis: 0.5 };
  const a = r?.action || { alarm_type: '', severity: 'warning', message: '' };
  const zones = Object.values(S.sensors).map(s => s.asset_id);
  const assets = [...new Set(['TF01', ...zones])].sort();
  dialog(`<h2>${r ? 'Edit rule' : 'New rule'}</h2>
    <label class="f">Name<input type="text" name="name" required value="${esc(r?.name || '')}"></label>
    <div class="row"><label class="f">Scope asset<select name="scope_asset_id"><option value="">any</option>${assets.map(x => `<option ${x === r?.scope_asset_id ? 'selected' : ''}>${x}</option>`).join('')}</select></label>
      <label class="f">Sensor kind<select name="sensor_kind">${['THS', 'THH', 'IRS', 'TCK', 'CTS'].map(k => `<option ${k === c.sensor_kind ? 'selected' : ''}>${k}</option>`).join('')}</select></label>
      <label class="f">Position (optional)<input type="text" name="position" value="${esc(c.position || '')}"></label>
      <label class="f">Key<select name="key">${['t_c', 'rh_pct', 'amp'].map(k => `<option ${k === c.key ? 'selected' : ''}>${k}</option>`).join('')}</select></label>
      <label class="f">Operator<select name="op">${['>', '<', '>=', '<='].map(k => `<option ${k === c.op ? 'selected' : ''}>${esc(k)}</option>`).join('')}</select></label>
      <label class="f">Value<input type="number" step="any" name="value" required value="${c.value}"></label>
      <label class="f">For, seconds<input type="number" min="0" name="for_s" value="${c.for_s ?? 0}"></label>
      <label class="f">Hysteresis<input type="number" min="0" step="any" name="hysteresis" value="${c.hysteresis ?? 0}"></label>
      <label class="f">Alarm type<input type="text" name="alarm_type" required pattern="[a-z0-9_]+" value="${esc(a.alarm_type)}"></label>
      <label class="f">Severity<select name="severity">${['warning', 'major', 'critical'].map(k => `<option ${k === a.severity ? 'selected' : ''}>${k}</option>`).join('')}</select></label></div>
    <label class="f">Message<input type="text" name="message" value="${esc(a.message || '')}"></label>
    <label class="toggle"><input type="checkbox" name="enabled" ${r?.enabled === false ? '' : 'checked'}> Enabled</label>`,
  async fd => {
    const condition = { sensor_kind: fd.get('sensor_kind'), key: fd.get('key'), op: fd.get('op'), value: Number(fd.get('value')),
      for_s: Number(fd.get('for_s') || 0), hysteresis: Number(fd.get('hysteresis') || 0) };
    if (fd.get('position')) condition.position = fd.get('position');
    const body = { name: fd.get('name'), scope_asset_id: fd.get('scope_asset_id') || null, condition, enabled: fd.get('enabled') === 'on',
      action: { alarm_type: fd.get('alarm_type'), severity: fd.get('severity'), message: fd.get('message') || fd.get('name') } };
    await api(r ? `/rules/${r.id}` : '/rules', { method: r ? 'PUT' : 'POST', body });
    toast('Rule saved'); done();
  });
}

// ---- users -------------------------------------------------------------------------------------

function users() {
  const load = async () => {
    const el = $('#users'); if (!el) return;
    if (!can.users()) { el.innerHTML = '<p class="note">Only owner and admin can manage users.</p>'; return; }
    try {
      const rows = await api('/users');
      el.innerHTML = table([{ h: 'User', f: u => esc(u.username) }, { h: 'Name', f: u => esc(u.display_name) }, { h: 'Role', f: u => esc(u.role) },
        { h: 'Active', f: u => u.active ? 'yes' : '<span class="tag bad">disabled</span>' },
        { h: '', f: u => `<button class="btn ghost sm" data-u="${u.id}">Edit</button>` }], rows) + '<div class="btns"><button class="btn" id="unew">Add user</button></div>';
      const roleSel = cur => `<select name="role">${['operator', 'manager', 'owner', 'admin'].map(x => `<option ${x === cur ? 'selected' : ''}>${x}</option>`).join('')}</select>`;
      $('#unew').addEventListener('click', () => dialog(`<h2>Add user</h2><div class="row"><label class="f">Username<input type="text" name="username" required pattern="[A-Za-z0-9_.\\-]+"></label>
        <label class="f">Name<input type="text" name="display_name"></label><label class="f">Role${roleSel('operator')}</label>
        <label class="f">Password (8+)<input type="password" name="password" required minlength="8" autocomplete="new-password"></label></div>`,
      async fd => { await api('/users', { method: 'POST', body: Object.fromEntries(fd) }); load(); }));
      $$('[data-u]', el).forEach(b => b.addEventListener('click', () => {
        const u = rows.find(x => String(x.id) === b.dataset.u);
        dialog(`<h2>${esc(u.username)}</h2><div class="row"><label class="f">Name<input type="text" name="display_name" value="${esc(u.display_name)}"></label>
          <label class="f">Role${roleSel(u.role)}</label><label class="f">New password<input type="password" name="password" minlength="8" autocomplete="new-password" placeholder="unchanged"></label></div>
          <label class="toggle"><input type="checkbox" name="active" ${u.active ? 'checked' : ''}> Active</label>`,
        async fd => { await api(`/users/${u.id}`, { method: 'PATCH', body: { display_name: fd.get('display_name'), role: fd.get('role'), active: fd.get('active') === 'on', password: fd.get('password') || null } }); load(); });
      }));
    } catch (e) { err(e); }
  };
  return { html: '<div class="panel" id="users"><p class="note">Loading…</p></div>', bind: load };
}

// ---- system -------------------------------------------------------------------------------------

function system() {
  const load = async () => {
    const el = $('#sys'); if (!el) return;
    try {
      const [stats, rejects, audit] = await Promise.all([api('/ingest/stats'), api('/ingest/rejects', { params: { limit: 50 } }),
        can.configure() ? api('/audit', { params: { limit: 100 } }) : Promise.resolve(null)]);
      const s = stats.since_start;
      el.innerHTML = `<div class="kpis"><div class="kpi"><div class="v">${stats.mqtt_connected ? 'Up' : 'Down'}</div><div class="l">Backend MQTT</div></div>
        <div class="kpi"><div class="v">${fmt(s.received || 0, 0)}</div><div class="l">Messages since start</div></div>
        <div class="kpi"><div class="v">${fmt(s.readings || 0, 0)}</div><div class="l">Readings stored</div></div>
        <div class="kpi"><div class="v">${fmt(s.events || 0, 0)}</div><div class="l">Events</div></div>
        <div class="kpi"><div class="v">${fmt(s.duplicates || 0, 0)}</div><div class="l">Duplicates dropped</div></div>
        <div class="kpi ${stats.rejects_24h ? 'bad' : ''}"><div class="v">${stats.rejects_24h}</div><div class="l">Rejects, 24 h</div></div></div>
        <div class="panel"><h2>Rejected messages</h2>${table([{ h: 'Time', f: r => dateTime(r.received_at) }, { h: 'Device', f: r => esc(r.device_id || '') }, { h: 'Reason', f: r => esc(r.reason) },
          { h: 'Payload', f: r => `<code>${esc(JSON.stringify(r.payload)).slice(0, 120)}</code>` }], rejects, { empty: 'None.' })}</div>
        ${audit ? `<div class="panel"><h2>Audit log</h2>${table([{ h: 'Time', f: r => dateTime(r.ts) }, { h: 'User', f: r => esc(r.username) }, { h: 'Action', f: r => esc(r.action) },
          { h: 'Entity', f: r => esc(r.entity) }, { h: 'Change', f: r => `<code>${esc(JSON.stringify(r.old))} → ${esc(JSON.stringify(r.new))}</code>` }, { h: 'Reason', f: r => esc(r.reason || '') }], audit)}</div>` : ''}`;
    } catch (e) { err(e); }
  };
  return { html: '<div class="stack" id="sys"><p class="note">Loading…</p></div>', bind: load };
}

export const VIEWS = {
  overview: { title: 'Plant overview', sub: 'Live from the factory floor.', fn: overview },
  weighings: { title: 'Weighings', sub: 'Every weighing from A, B, W1–W4 and D.', fn: weighings },
  batches: { title: 'Batches', sub: 'Rolling, dhool, fermentation, made tea.', fn: batches },
  reports: { title: 'Reports', sub: 'Moisture loss, supplier attribution and area cycles.', fn: reports },
  alarms: { title: 'Alarms', sub: 'Open alarms and history.', fn: alarmsView },
  devices: { title: 'Devices', sub: 'Scale bridges and zone nodes, and their settings.', fn: devices },
  rules: { title: 'Rules', sub: 'Alarm rules.', fn: rules },
  users: { title: 'Users', sub: 'Who can log in, and their roles.', fn: users },
  system: { title: 'System', sub: 'Ingest health, rejects and the audit log.', fn: system },
};
export { spark, reading };
