// REST and WebSocket client. The token lives in localStorage (best effort).
const KEY = 'tf01-token';
let token = null;
try { token = localStorage.getItem(KEY); } catch (e) { /* storage blocked */ }

export const auth = {
  get token() { return token; },
  set(t) { token = t; try { t ? localStorage.setItem(KEY, t) : localStorage.removeItem(KEY); } catch (e) { /* ignore */ } },
  onLogout: null,
};

export class ApiError extends Error {
  constructor(status, detail) { super(detail); this.status = status; }
}

export async function api(path, { method = 'GET', body, params } = {}) {
  const url = new URL('/api' + path, location.origin);
  if (params) for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue;
    (Array.isArray(v) ? v : [v]).forEach(x => url.searchParams.append(k, x));
  }
  const res = await fetch(url, {
    method,
    headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401 && path !== '/auth/login') { auth.set(null); auth.onLogout?.(); }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const d = data?.detail;
    throw new ApiError(res.status, Array.isArray(d) ? d.map(x => `${x.loc?.slice(-1)[0]}: ${x.msg}`).join('; ') : (d || res.statusText));
  }
  return data;
}

// WebSocket with reconnect. onState(true/false) reports the connection.
export function connectWs(onMessage, onState) {
  let ws, timer, backoff = 1000, closed = false;
  function open() {
    if (!token) return;
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/api/ws?token=${encodeURIComponent(token)}`);
    ws.onopen = () => { backoff = 1000; onState(true); };
    ws.onmessage = e => { try { onMessage(JSON.parse(e.data)); } catch (err) { console.error(err); } };
    ws.onclose = e => {
      onState(false);
      if (closed) return;
      if (e.code === 4401) { auth.set(null); auth.onLogout?.(); return; }
      timer = setTimeout(open, backoff);
      backoff = Math.min(backoff * 2, 15000);
    };
  }
  open();
  const ping = setInterval(() => { if (ws?.readyState === 1) ws.send('ping'); }, 25000);
  return () => { closed = true; clearTimeout(timer); clearInterval(ping); ws?.close(); };
}
