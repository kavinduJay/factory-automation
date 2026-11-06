// Shell: login, navigation (hash routes), live connection, view lifecycle.
import { api, auth, connectWs } from './api.js';
import { S, apply, emit, loadLive, openAlarms, subscribe } from './store.js';
import { $, esc, toast } from './util.js';
import { VIEWS, ui } from './views.js';

let current = null, stopWs = null;

function route() {
  const [, name = 'overview', arg] = location.hash.split('/');
  return { name: VIEWS[name] ? name : 'overview', arg };
}

function go(name) { location.hash = `#/${name}`; }
ui.go = name => { if (route().name === name) render(); else go(name); };

function renderNav() {
  const n = openAlarms().length, { name } = route();
  $('#nav').innerHTML = `<div class="brand"><b>TF01</b><span>Factory monitor</span></div>` +
    Object.entries(VIEWS).filter(([k]) => k !== 'users' || ['owner', 'admin'].includes(S.user?.role)).map(([k, v]) =>
      `<button data-nav="${k}" ${k === name ? 'aria-current="page"' : ''}><span>${esc(v.title.replace('Plant overview', 'Overview'))}</span>${k === 'alarms' && n ? `<span class="count">${n}</span>` : ''}</button>`).join('') +
    `<div class="note who">${esc(S.user?.display_name || S.user?.username)} · ${esc(S.user?.role)} <a href="#" id="logout">Log out</a></div>`;
  $('#nav').querySelectorAll('[data-nav]').forEach(b => b.addEventListener('click', () => go(b.dataset.nav)));
  $('#logout').addEventListener('click', e => { e.preventDefault(); logout(); });
}

function header(v) {
  const n = openAlarms().filter(a => a.severity !== 'warning').length;
  return `<div class="top"><div><h1>${esc(v.title)}</h1><div class="sub">${esc(v.sub)}</div></div>
    <div class="status"><span class="pill" title="Live connection to the server"><span class="conn-dot ${S.wsOn ? 'on' : ''}" id="wsdot"></span><span id="wstxt">${S.wsOn ? 'Live' : 'Reconnecting…'}</span></span>
    <button class="pill ${n ? 'alarm' : ''}" id="hdrAl" style="cursor:pointer">${pillText()}</button></div></div>`;
}

function pillText() {
  const all = openAlarms(), n = all.filter(a => a.severity !== 'warning').length, w = all.length - n;
  if (!all.length) return 'No alarms';
  return [n && `${n} alarm${n > 1 ? 's' : ''}`, w && `${w} warning${w > 1 ? 's' : ''}`].filter(Boolean).join(' · ');
}

function render() {
  const { name, arg } = route();
  const v = VIEWS[name];
  current = v.fn(arg);
  renderNav();
  $('#main').innerHTML = header(v) + current.html;
  $('#hdrAl').addEventListener('click', () => go('alarms'));
  current.bind?.($('#main'));
}

subscribe(kinds => {
  if (!S.user) return;
  if (kinds.has('alarm') || kinds.has('all')) {
    renderNav();
    const h = $('#hdrAl');
    if (h) { const n = openAlarms().filter(a => a.severity !== 'warning').length; h.className = `pill ${n ? 'alarm' : ''}`; h.textContent = pillText(); }
  }
  current?.update?.(kinds);
});

function setWs(on) {
  S.wsOn = on;
  const d = $('#wsdot'), t = $('#wstxt');
  if (d) d.className = `conn-dot ${on ? 'on' : ''}`;
  if (t) t.textContent = on ? 'Live' : 'Reconnecting…';
  if (on) loadLive().catch(() => {}); // catch up on anything missed while disconnected
}

function onMessage(m) {
  apply(m);
  if (m.type === 'alarm' && !m.alarm.cleared_at && m.alarm.status === 'active' && m.alarm.severity !== 'warning') toast(`Alarm: ${m.alarm.message}`, 'bad');
}

async function start() {
  try { S.user = await api('/auth/me'); } catch (e) { showLogin(); return; }
  $('#login').hidden = true; $('#app').hidden = false;
  try { await loadLive(); } catch (e) { toast(e.message, 'bad'); }
  stopWs?.(); stopWs = connectWs(onMessage, setWs);
  render();
}

function showLogin(msg = '') {
  stopWs?.(); stopWs = null; S.user = null;
  $('#app').hidden = true; $('#login').hidden = false;
  $('#loginErr').textContent = msg;
  $('#lu').focus();
}

function logout() { auth.set(null); showLogin(); }
auth.onLogout = () => { if (S.user) showLogin('Your session has ended. Please log in again.'); };

$('#loginForm').addEventListener('submit', async e => {
  e.preventDefault();
  $('#loginErr').textContent = '';
  try {
    const r = await api('/auth/login', { method: 'POST', body: { username: $('#lu').value, password: $('#lp').value } });
    auth.set(r.token); $('#lp').value = '';
    start();
  } catch (x) { $('#loginErr').textContent = x.message; }
});
window.addEventListener('hashchange', () => { if (S.user) render(); });
setInterval(() => emit('tick'), 15000); // refresh "x min ago" texts
if (auth.token) start(); else showLogin();
