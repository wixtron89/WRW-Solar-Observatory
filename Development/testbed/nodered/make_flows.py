#!/usr/bin/env python3
"""
Generates the Node-RED data folders for SOM and CAM (identical flow, different env):
    nodered/som/data/{flows.json,flows_cred.json,settings.js}
    nodered/cam/data/...
Run again to reset the flow:  python3 nodered/make_flows.py
"""
import json, pathlib

PARSE = r"""
// wrwo/<site>/pubdata/<device>/<measurement...>   +  MQTT5 user property timestamp=<unix ns>
const parts = msg.topic.split('/');
if (parts.length < 4 || parts[2] !== 'pubdata') {
    return [null, { topic: msg.topic, payload: { reason: 'unexpected topic' } }];
}
const site = parts[1];
const device = parts[3];
let measurement = parts.slice(4).join('_') || 'data';

// ---- timestamp from the MQ-BRIDGE plugin (string, ns) ----------------------
let ts = (msg.userProperties || {}).timestamp;
// an MQTT 5 device may send its own "timestamp" user property; the plugin appends its own
// last. Node-RED hands duplicates over as a JSON string '["<device>","<plugin>"]', so take
// the last ns number in whatever form it arrives (string, array, JSON string)
const tsAll = String(Array.isArray(ts) ? ts.join(',') : (ts || '')).match(/\d{16,20}/g);
ts = tsAll ? tsAll[tsAll.length - 1] : undefined;
const tags = { site, device };
if (!/^\d{16,20}$/.test(String(ts || ''))) {        // no plugin timestamp -> fall back, but mark it
    ts = (BigInt(Date.now()) * 1000000n).toString();
    tags.ts_source = 'nodered';
}

// ---- payload -> fields: JSON / telegraf JSON / number / key=value / text ----
const text = (Buffer.isBuffer(msg.payload) ? msg.payload.toString() : String(msg.payload)).trim();
let fields = {};
let obj;
try { obj = JSON.parse(text); } catch (e) { obj = undefined; }
if (obj && typeof obj === 'object' && !Array.isArray(obj)) {
    if (obj.fields && typeof obj.fields === 'object') {      // telegraf data_format = "json"
        if (obj.name) measurement = String(obj.name);
        Object.assign(tags, obj.tags || {});
        obj = obj.fields;
    }
    for (const [k, v] of Object.entries(obj)) {
        if (['ts', 'time', 'timestamp'].includes(k)) continue;
        if (['number', 'boolean', 'string'].includes(typeof v)) fields[k] = v;
    }
} else if (typeof obj === 'number') {
    fields.value = obj;
} else if (/^[A-Za-z_][\w.-]*\s*=/.test(text)) {
    for (const p of text.split(/[,;]/)) {
        const i = p.indexOf('=');
        if (i < 0) continue;
        const k = p.slice(0, i).trim(), s = p.slice(i + 1).trim(), n = Number(s);
        fields[k] = (s !== '' && !isNaN(n)) ? n : (s === 'true' || s === 'false') ? s === 'true' : s;
    }
} else {
    fields.raw = text;
}

// ---- quality control: physical limits per measurement.field ----------------
const LIMITS = {
    cloudwatcher: { temp: [-30, 60], hum: [0, 100], dewp: [-60, 50], clouds: [-60, 30], rawir: [-80, 60], wind: [0, 200], gust: [0, 250] },
    seeing:       { seeing_arcsec: [0.1, 20], r0: [0, 2000], temp_inside_box: [-20, 70] },
};
const OFFSET = { 'lunatico.temp': 0.0 };      // calibration, key "<device>.<field>"
const lim = LIMITS[measurement] || {};
const rejected = [];
for (const [k, v] of Object.entries(fields)) {
    if (typeof v !== 'number') continue;
    const val = v + (OFFSET[device + '.' + k] || 0);
    const L = lim[k];
    if (L && (val < L[0] || val > L[1])) { rejected.push(k + '=' + v); delete fields[k]; }
    else fields[k] = val;
}
fields.qc_rejected = rejected.length;
// how late the point reached THIS Node-RED (grows after a CAM link outage)
fields.delay_s = Number(BigInt(Date.now()) * 1000000n - BigInt(ts)) / 1e9;

msg.record = { measurement, tags, fields, ts };
const reject = rejected.length ? { topic: msg.topic, payload: { reason: 'out of range', rejected } } : null;
return [msg, reject];
"""

TO_LINE = r"""
const r = msg.record;
const escM = s => String(s).replace(/[, ]/g, m => '\\' + m);
const escK = s => String(s).replace(/[,= ]/g, m => '\\' + m);
const tagStr = Object.keys(r.tags).sort()
    .filter(k => r.tags[k] !== '' && r.tags[k] != null)
    .map(k => escK(k) + '=' + escK(r.tags[k])).join(',');
const f = [];
for (const [k, v] of Object.entries(r.fields)) {
    if (typeof v === 'number' && isFinite(v)) f.push(escK(k) + '=' + v);   // always float
    else if (typeof v === 'boolean') f.push(escK(k) + '=' + v);
    else if (typeof v === 'string') f.push(escK(k) + '="' + v.replace(/["\\]/g, m => '\\' + m) + '"');
}
if (!f.length) return null;
msg.payload = escM(r.measurement) + ',' + tagStr + ' ' + f.join(',') + ' ' + r.ts;   // ns
msg.headers = { 'Content-Type': 'text/plain' };
return msg;
"""

CHECK = r"""
if (msg.statusCode !== 204) {
    node.error('InfluxDB write failed (' + msg.statusCode + '): ' + msg.payload, msg);
    node.status({ fill: 'red', shape: 'dot', text: 'HTTP ' + msg.statusCode });
} else {
    const n = (context.get('n') || 0) + 1; context.set('n', n);
    node.status({ fill: 'green', shape: 'dot', text: n + ' points' });
}
return null;
"""

DAILY = r"""
// Daily statistics for ALL numeric fields of ALL measurements (new devices included):
// retention policy "daily" (kept forever) + continuous query, recreated on every start.
// Day boundaries follow the container TZ. Strings (cloudsSafe, quality, ...) are skipped
// by the wildcard; mean_safe / mean_valid_seeing give the fraction of the day.
const db = env.get('INFLUX_DB') || 'wrwo';
const tz = env.get('TZ') || 'UTC';
const sel = `SELECT mean(*), min(*), max(*), count("delay_s") AS points ` +
            `INTO "${db}"."daily".:MEASUREMENT FROM "${db}"."autogen"./.*/`;
const grp = `GROUP BY time(1d), "site", "device" tz('${tz}')`;
msg.payload = 'q=' + encodeURIComponent([
    `CREATE RETENTION POLICY "daily" ON "${db}" DURATION INF REPLICATION 1`,
    `DROP CONTINUOUS QUERY "daily_stats" ON "${db}"`,
    // every hour: recompute today and yesterday (late data after a link outage included)
    `CREATE CONTINUOUS QUERY "daily_stats" ON "${db}" RESAMPLE EVERY 1h FOR 2d BEGIN ${sel} ${grp} END`,
    // fill today/yesterday right away instead of waiting for the first CQ run
    `${sel} WHERE time > now() - 2d ${grp}`,
].join('; '));
msg.headers = { 'Content-Type': 'application/x-www-form-urlencoded' };
return msg;
"""

QUERY_CHECK = r"""
let r; try { r = JSON.parse(msg.payload); } catch (e) { r = null; }
const errs = ((r && r.results) || []).filter(x => x.error).map(x => x.error);
if (msg.statusCode !== 200 || errs.length) {
    node.error('daily statistics setup failed (' + msg.statusCode + '): ' + (errs.join('; ') || msg.payload), msg);
    node.status({ fill: 'red', shape: 'dot', text: 'failed' });
} else {
    node.status({ fill: 'green', shape: 'dot', text: 'CQ daily_stats ok' });
}
return null;
"""

BRIDGE_STATE = r"""
// $SYS/broker/connection/<bridge client id>/state : "1" = up, "0" = down
const id = msg.topic.split('/')[3];
node.status({ fill: msg.payload == '1' ? 'green' : 'red', shape: 'dot', text: id + (msg.payload == '1' ? ' UP' : ' DOWN') });
node.warn('bridge ' + id + ' ' + (msg.payload == '1' ? 'UP' : 'DOWN'));
return null;
"""

TAB, BROKER = "tab_wrwo", "broker_local"


def flows(site_label):
    return [
        {"id": TAB, "type": "tab", "label": f"wrwo -> InfluxDB ({site_label})", "disabled": False, "info": ""},
        {"id": BROKER, "type": "mqtt-broker", "name": "MQ-BROKER (MQTT 5)",
         "broker": "${MQTT_HOST}", "port": "${MQTT_PORT}", "clientid": "${MQTT_CLIENT_ID}",
         "autoConnect": True, "usetls": False, "protocolVersion": "5", "keepalive": "30",
         "cleansession": False, "autoUnsubscribe": False, "sessionExpiry": "86400",
         "birthTopic": "", "closeTopic": "", "willTopic": ""},
        # create the database on start (harmless if it exists)
        {"id": "inj_db", "type": "inject", "z": TAB, "name": "on start", "props": [], "repeat": "",
         "crontab": "", "once": True, "onceDelay": "3", "topic": "", "x": 120, "y": 40, "wires": [["http_db"]]},
        {"id": "http_db", "type": "http request", "z": TAB, "name": "CREATE DATABASE", "method": "POST",
         "ret": "txt", "paytoqs": "ignore", "url": "${INFLUX_CREATE_DB_URL}", "tls": "", "persist": False,
         "proxy": "", "insecureHTTPParser": False, "authType": "", "senderr": False, "headers": [],
         "x": 320, "y": 40, "wires": [["dbg_db", "fn_daily"]]},
        {"id": "dbg_db", "type": "debug", "z": TAB, "name": "db", "active": True, "tosidebar": True,
         "console": True, "complete": "statusCode", "targetType": "msg", "x": 500, "y": 20, "wires": []},
        # daily statistics (retention policy "daily" + continuous query), after the DB exists
        {"id": "fn_daily", "type": "function", "z": TAB, "name": "daily stats CQ", "func": DAILY.strip(),
         "outputs": 1, "x": 510, "y": 60, "wires": [["http_daily"]]},
        {"id": "http_daily", "type": "http request", "z": TAB, "name": "POST /query", "method": "POST",
         "ret": "txt", "paytoqs": "ignore", "url": "${INFLUX_QUERY_URL}", "tls": "", "persist": False,
         "proxy": "", "insecureHTTPParser": False, "authType": "", "senderr": False, "headers": [],
         "x": 690, "y": 60, "wires": [["fn_daily_check"]]},
        {"id": "fn_daily_check", "type": "function", "z": TAB, "name": "cek CQ", "func": QUERY_CHECK.strip(),
         "outputs": 1, "x": 860, "y": 60, "wires": [[]]},

        {"id": "in_data", "type": "mqtt in", "z": TAB, "name": "wrwo/+/pubdata/#", "topic": "wrwo/+/pubdata/#",
         "qos": "1", "datatype": "buffer", "broker": BROKER, "nl": False, "rap": True, "rh": 0, "inputs": 0,
         "x": 140, "y": 120, "wires": [["fn_parse"]]},
        {"id": "fn_parse", "type": "function", "z": TAB, "name": "parse + timestamp + QC", "func": PARSE.strip(),
         "outputs": 2, "x": 380, "y": 120, "wires": [["fn_line"], ["dbg_reject"]]},
        {"id": "fn_line", "type": "function", "z": TAB, "name": "to line protocol", "func": TO_LINE.strip(),
         "outputs": 1, "x": 610, "y": 100, "wires": [["http_write"]]},
        {"id": "http_write", "type": "http request", "z": TAB, "name": "POST /write (ns)", "method": "POST",
         "ret": "txt", "paytoqs": "ignore", "url": "${INFLUX_WRITE_URL}", "tls": "", "persist": True,
         "proxy": "", "insecureHTTPParser": False, "authType": "", "senderr": False, "headers": [],
         "x": 820, "y": 100, "wires": [["fn_check"]]},
        {"id": "fn_check", "type": "function", "z": TAB, "name": "cek respon", "func": CHECK.strip(),
         "outputs": 1, "x": 1000, "y": 100, "wires": [[]]},
        {"id": "dbg_reject", "type": "debug", "z": TAB, "name": "ditolak (QC)", "active": True,
         "tosidebar": True, "console": True, "complete": "payload", "targetType": "msg",
         "x": 610, "y": 160, "wires": []},

        {"id": "in_state", "type": "mqtt in", "z": TAB, "name": "status bridge",
         "topic": "$SYS/broker/connection/+/state", "qos": "1", "datatype": "utf8", "broker": BROKER,
         "nl": False, "rap": True, "rh": 0, "inputs": 0, "x": 130, "y": 240, "wires": [["fn_state"]]},
        {"id": "fn_state", "type": "function", "z": TAB, "name": "bridge UP/DOWN", "func": BRIDGE_STATE.strip(),
         "outputs": 1, "x": 360, "y": 240, "wires": [[]]},
    ]


SETTINGS = """// Minimal settings for the testbed.
// credentialSecret:false keeps flows_cred.json in plain text so the
// MQTT login can come from environment variables (${MQTT_USER}/${MQTT_PASS}).
// For production set a credentialSecret and enable adminAuth.
module.exports = {
    flowFile: 'flows.json',
    credentialSecret: false,
    uiPort: process.env.PORT || 1880,
    logging: { console: { level: 'info', metrics: false, audit: false } },
    editorTheme: { projects: { enabled: false } },
};
"""

root = pathlib.Path(__file__).parent
for site in ("som", "cam"):
    d = root / site / "data"
    d.mkdir(parents=True, exist_ok=True)
    (d / "flows.json").write_text(json.dumps(flows(site.upper()), indent=2))
    (d / "flows_cred.json").write_text(json.dumps({BROKER: {"user": "${MQTT_USER}", "password": "${MQTT_PASS}"}}, indent=2))
    (d / "settings.js").write_text(SETTINGS)
    print("wrote", d)
