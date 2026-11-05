// Live plant state: loaded from /api/live, then kept current by the WebSocket.
import { api } from './api.js';
import { debounce } from './util.js';

export const S = {
  user: null,
  wsOn: false,
  mqtt: false,
  devices: {},     // id -> device
  sensors: {},     // id -> sensor
  bySensorAsset: {}, // asset_id -> [sensor]
  readings: {},    // sensor_id -> key -> {value, ts}
  alarms: {},      // id -> open alarm
  settings: {},    // device_id -> {desired, reported}
  areas: [],       // open area cycles
  lastEvent: {},   // device_id -> {event, result, ts}
  history: {},     // sensor_id|key -> [[ts, v]] short client-side trail for sparklines
};

const listeners = new Set();
export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }
let pending = new Set(), scheduled = false;
export function emit(kind) {
  pending.add(kind);
  if (scheduled) return;
  scheduled = true;
  requestAnimationFrame(() => {
    const kinds = pending; pending = new Set(); scheduled = false;
    listeners.forEach(fn => { try { fn(kinds); } catch (e) { console.error(e); } });
  });
}

export async function loadLive() {
  const d = await api('/live');
  S.mqtt = d.mqtt_connected;
  S.devices = Object.fromEntries(d.devices.map(x => [x.id, x]));
  S.sensors = Object.fromEntries(d.sensors.map(x => [x.id, x]));
  S.bySensorAsset = {};
  d.sensors.forEach(s => (S.bySensorAsset[s.asset_id] ||= []).push(s));
  S.readings = d.readings;
  S.alarms = Object.fromEntries(d.alarms.map(a => [a.id, a]));
  S.settings = d.settings;
  S.areas = d.areas;
  S.lastEvent = d.last_events || {};
  emit('all');
}

const refreshAreas = debounce(async () => {
  try { S.areas = await api('/areas'); emit('areas'); } catch (e) { /* next event retries */ }
}, 1500);

function trail(sensor, key, ts, value) {
  const k = `${sensor}|${key}`;
  const arr = (S.history[k] ||= []);
  arr.push([ts, value]);
  if (arr.length > 360) arr.splice(0, arr.length - 360);
}

export function apply(m) {
  switch (m.type) {
    case 'telemetry':
      for (const r of m.readings) {
        (S.readings[r.sensor] ||= {})[r.key] = { value: r.value, ts: m.ts };
        trail(r.sensor, r.key, m.ts, r.value);
      }
      if (S.devices[m.device_id]) { S.devices[m.device_id].last_seen = new Date().toISOString(); S.devices[m.device_id].online = true; }
      emit('telemetry');
      break;
    case 'event':
      S.lastEvent[m.device_id] = { event: m.event, result: m.result, ts: m.ts };
      if (['sack_weighed', 'crate_weighed', 'area_unloaded'].includes(m.event.type)) refreshAreas();
      emit('event');
      break;
    case 'alarm':
      if (m.alarm.cleared_at) delete S.alarms[m.alarm.id]; else S.alarms[m.alarm.id] = m.alarm;
      emit('alarm');
      break;
    case 'device':
      if (S.devices[m.device_id]) Object.assign(S.devices[m.device_id], { online: m.online, last_seen: m.last_seen });
      emit('device');
      break;
    case 'attributes': {
      const st = (S.settings[m.device_id] ||= { desired: {}, reported: null });
      if (m.scope === 'shared') st.desired = m.values;
      else if (m.values.settings) st.reported = m.values.settings;
      emit('settings');
      break;
    }
    case 'correction':
      emit('correction');
      break;
    default:
  }
}

export function openAlarms() {
  return Object.values(S.alarms).sort((a, b) =>
    ({ critical: 0, major: 1, warning: 2 }[a.severity] - { critical: 0, major: 1, warning: 2 }[b.severity])
    || new Date(b.started_at) - new Date(a.started_at));
}

export function inSync(deviceId) {
  const st = S.settings[deviceId];
  if (!st || !st.reported) return false;
  return Object.entries(st.desired || {}).every(([k, v]) => st.reported[k] === v);
}

export function reading(sensorId, key) { return S.readings[sensorId]?.[key]; }

export const can = {
  configure: () => ['owner', 'manager', 'admin'].includes(S.user?.role),
  users: () => ['owner', 'admin'].includes(S.user?.role),
};
