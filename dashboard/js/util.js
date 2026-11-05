// Small helpers shared by every module.
export const $ = (s, el = document) => el.querySelector(s);
export const $$ = (s, el = document) => [...el.querySelectorAll(s)];

export function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export function fmt(v, d = 1) {
  if (v === null || v === undefined || v === '' || Number.isNaN(Number(v))) return '–';
  return Number(v).toLocaleString('en-GB', { minimumFractionDigits: d, maximumFractionDigits: d });
}

// The factory runs on Sri Lanka time whatever the viewer's clock says.
const TZ = 'Asia/Colombo';
export function time(ts, withSec = false) {
  if (!ts) return '–';
  return new Date(ts).toLocaleTimeString('en-GB', { timeZone: TZ, hour: '2-digit', minute: '2-digit', ...(withSec ? { second: '2-digit' } : {}) });
}
export function dateTime(ts) {
  if (!ts) return '–';
  return new Date(ts).toLocaleString('en-GB', { timeZone: TZ, day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}
export function ago(ts) {
  if (!ts) return 'never';
  const s = Math.max(0, (Date.now() - new Date(ts).getTime()) / 1000);
  if (s < 10) return 'just now';
  if (s < 90) return `${Math.round(s)} s ago`;
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 172800) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
}
export function colomboDate(d = new Date()) {
  return d.toLocaleDateString('en-CA', { timeZone: TZ }); // YYYY-MM-DD
}

export function toast(text, kind = '') {
  let box = $('#toast');
  if (!box) { box = document.createElement('div'); box.id = 'toast'; box.className = 'toast'; box.setAttribute('aria-live', 'polite'); document.body.append(box); }
  const el = document.createElement('div');
  el.className = kind; el.textContent = text;
  box.append(el);
  setTimeout(() => el.remove(), 5000);
}

export function debounce(fn, ms) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

export const SEV_ORDER = { critical: 0, major: 1, warning: 2 };
export function sevClass(sev) { return sev === 'warning' ? 'warn' : ''; }

// Run fn at most once per ms; a call during the wait schedules one trailing run.
export function throttle(fn, ms) {
  let last = 0, t = null;
  return (...a) => {
    const wait = ms - (Date.now() - last);
    if (wait <= 0) { last = Date.now(); fn(...a); }
    else if (!t) t = setTimeout(() => { t = null; last = Date.now(); fn(...a); }, wait);
  };
}
