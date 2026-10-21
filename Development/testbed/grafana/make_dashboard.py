#!/usr/bin/env python3
"""
Generates grafana/dashboards/wrwo.json (same dashboard for SOM and CAM).
Run again after editing:  python3 grafana/make_dashboard.py
Grafana picks up the file within 30 s.
"""
import json, pathlib

DS = {"type": "influxdb", "uid": "influx-wrwo"}
_ids = iter(range(1, 1000))


def q(ref, alias, query):
    return {"refId": ref, "rawQuery": True, "resultFormat": "time_series", "alias": alias, "query": query}


def series(measurement, field, fn="mean", group="time($__interval)", fill="null", extra=""):
    return (f'SELECT {fn}("{field}") FROM "{measurement}" WHERE {extra}$timeFilter '
            f'GROUP BY {group} fill({fill})')


def last(measurement, field):
    return f'SELECT last("{field}") FROM "{measurement}" WHERE $timeFilter'


def steps(*pairs):
    """steps('green', None, 'red', 30) -> threshold steps"""
    return {"mode": "absolute",
            "steps": [{"color": pairs[i], "value": pairs[i + 1]} for i in range(0, len(pairs), 2)]}


def row(title, y):
    return {"id": next(_ids), "type": "row", "title": title, "collapsed": False,
            "gridPos": {"h": 1, "w": 24, "x": 0, "y": y}, "panels": []}


def stat(title, targets, pos, unit=None, decimals=None, thresholds=None, mappings=None,
         color="value", graph="none", text="value", no_value=None, desc=None, fixed=None):
    d = {}
    if unit: d["unit"] = unit
    if decimals is not None: d["decimals"] = decimals
    if thresholds: d["thresholds"] = thresholds
    if mappings: d["mappings"] = mappings
    if no_value is not None: d["noValue"] = no_value
    if fixed: d["color"] = {"mode": "fixed", "fixedColor": fixed}
    p = {"id": next(_ids), "type": "stat", "title": title, "datasource": DS, "gridPos": pos,
         "targets": targets, "fieldConfig": {"defaults": d, "overrides": []},
         "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                     "colorMode": color, "graphMode": graph, "textMode": text}}
    if desc: p["description"] = desc
    return p


def ts(title, targets, pos, unit=None, interval=None, draw="line", fill=0, width=1, minmax=None,
       right=(), thresholds=None, threshold_style=None, decimals=None, desc=None):
    custom = {"drawStyle": draw, "lineWidth": width, "fillOpacity": fill, "showPoints": "never",
              "spanNulls": False}
    if threshold_style: custom["thresholdsStyle"] = {"mode": threshold_style}
    d = {"custom": custom}
    if unit: d["unit"] = unit
    if decimals is not None: d["decimals"] = decimals
    if minmax: d["min"], d["max"] = minmax
    if thresholds:
        d["thresholds"] = thresholds
        d["color"] = {"mode": "thresholds"}
    overrides = [{"matcher": {"id": "byName", "options": n},
                  "properties": [{"id": "custom.axisPlacement", "value": "right"}]} for n in right]
    p = {"id": next(_ids), "type": "timeseries", "title": title, "datasource": DS, "gridPos": pos,
         "targets": targets, "fieldConfig": {"defaults": d, "overrides": overrides},
         "options": {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                     "tooltip": {"mode": "multi", "sort": "none"}}}
    if interval: p["interval"] = interval
    if desc: p["description"] = desc
    return p


def pos(x, y, w, h):
    return {"h": h, "w": w, "x": x, "y": y}


CW, SEE = "cloudwatcher", "seeing"
SAFE_COLORS = [{"type": "value", "options": {
    "Safe": {"text": "Safe", "color": "green", "index": 0},
    "Unsafe": {"text": "Unsafe", "color": "red", "index": 1},
    "Unknown": {"text": "Unknown", "color": "#808080", "index": 2}}}]
SEEING_STEPS = steps("blue", None, "green", 1, "yellow", 2, "red", 3)   # excellent/good/average/poor

panels = [
    # ------------------------------------------------------------ pipeline ---
    row("Pipeline (SOM → CAM)", 0),
    stat("Points / last minute", [q("A", "seeing", f'SELECT count("delay_s") FROM "{SEE}" WHERE time > now() - 1m'),
                                  q("B", "cloudwatcher", f'SELECT count("delay_s") FROM "{CW}" WHERE time > now() - 1m')],
         pos(0, 1, 6, 4), thresholds=steps("red", None, "green", 1), color="background", text="value_and_name",
         no_value="0", desc="Simulator default: seeing 30 (every 2 s), cloudwatcher 2 (every 30 s). 0 = no data arriving."),
    stat("Latest delay", [q("A", "seeing", last(SEE, "delay_s"))], pos(6, 1, 6, 4), unit="s", decimals=2,
         thresholds=steps("green", None, "yellow", 2, "red", 30), color="background", graph="area",
         desc="Arrival time at Node-RED minus the MQ-BRIDGE plugin timestamp. Large after a SOM-CAM link outage."),
    stat("Values rejected by QC (time range)",
         [q("A", "cloudwatcher", f'SELECT sum("qc_rejected") FROM "{CW}" WHERE $timeFilter'),
          q("B", "seeing", f'SELECT sum("qc_rejected") FROM "{SEE}" WHERE $timeFilter')],
         pos(12, 1, 6, 4), thresholds=steps("green", None, "orange", 1), text="value_and_name", no_value="0"),
    stat("Points without plugin timestamp",
         [q("A", "seeing", f'SELECT count("delay_s") FROM "{SEE}" WHERE "ts_source" = \'nodered\' AND $timeFilter'),
          q("B", "cloudwatcher", f'SELECT count("delay_s") FROM "{CW}" WHERE "ts_source" = \'nodered\' AND $timeFilter')],
         pos(18, 1, 6, 4), thresholds=steps("green", None, "red", 1), text="value_and_name", no_value="0",
         desc="ts_source=nodered: message did not pass MQ-BRIDGE or the plugin is not loaded. Must be 0."),
    ts("Delay (delay_s)", [q("A", "cloudwatcher", series(CW, "delay_s", "max")),
                           q("B", "seeing", series(SEE, "delay_s", "max"))],
       pos(0, 5, 12, 8), unit="s", interval="30s", fill=10,
       desc="Normally < 1 s. After a link outage: a spike as high as the outage was long, then back down."),
    ts("Points per minute", [q("A", "cloudwatcher", series(CW, "delay_s", "count", "time(1m)", "0")),
                             q("B", "seeing", series(SEE, "delay_s", "count", "time(1m)", "0"))],
       pos(12, 5, 12, 8), draw="bars", fill=60,
       desc="A 0 bar = gap in the data. After a CAM outage there should be none: the bridge queue fills it in."),

    # ------------------------------------------------------- CloudWatcher ---
    row("Lunatico AAG CloudWatcher", 13),
    stat("Status", [q("A", "safe", last(CW, "safe"))], pos(0, 14, 4, 4), color="background",
         thresholds=steps("red", None, "green", 1),
         mappings=[{"type": "value", "options": {"1": {"text": "SAFE", "color": "green", "index": 0},
                                                 "0": {"text": "UNSAFE", "color": "red", "index": 1}}}],
         desc="CloudWatcher 'safe' field: 1 = all conditions Safe."),
    stat("Clouds (sky − ambient)", [q("A", "clouds", last(CW, "clouds"))], pos(4, 14, 4, 4), unit="celsius",
         decimals=1, thresholds=steps("green", None, "orange", -25, "red", -15), graph="area"),
    stat("Temperature", [q("A", "temp", last(CW, "temp"))], pos(8, 14, 4, 4), unit="celsius", decimals=1,
         graph="area", fixed="text"),
    stat("Humidity", [q("A", "hum", last(CW, "hum"))], pos(12, 14, 4, 4), unit="humidity", decimals=0,
         thresholds=steps("green", None, "red", 90), graph="area"),
    stat("Wind", [q("A", "wind", last(CW, "wind"))], pos(16, 14, 4, 4), unit="velocitykmh", decimals=0,
         thresholds=steps("green", None, "red", 30), graph="area"),
    stat("Rain sensor", [q("A", "rain", last(CW, "rain"))], pos(20, 14, 4, 4), decimals=0,
         thresholds=steps("red", None, "green", 1700), graph="area",
         desc="Rain sensor frequency: high (about 2100+) = dry, low = wet."),
    {"id": next(_ids), "type": "state-timeline", "title": "Safety conditions", "datasource": DS,
     "interval": "30s", "gridPos": pos(0, 18, 24, 7),
     "targets": [q(r, a, series(CW, f, "last")) for r, a, f in
                 (("A", "clouds", "cloudsSafe"), ("B", "wind", "windSafe"), ("C", "rain", "rainSafe"),
                  ("D", "humidity", "humSafe"), ("E", "light", "lightSafe"), ("F", "pressure", "pressureSafe"))],
     "fieldConfig": {"defaults": {"color": {"mode": "thresholds"}, "thresholds": steps("text", None),
                                  "mappings": SAFE_COLORS, "custom": {"fillOpacity": 80, "lineWidth": 0}},
                     "overrides": []},
     "options": {"showValue": "never", "mergeValues": True, "alignValue": "left", "rowHeight": 0.85,
                 "legend": {"displayMode": "list", "placement": "bottom", "showLegend": False},
                 "tooltip": {"mode": "single", "sort": "none"}}},
    ts("Temperature, dew point, raw IR", [q("A", "temp", series(CW, "temp")), q("B", "dew point", series(CW, "dewp")),
                                          q("C", "raw IR", series(CW, "rawir"))],
       pos(0, 25, 12, 8), unit="celsius", interval="30s"),
    ts("Clouds (sky − ambient)", [q("A", "clouds", series(CW, "clouds"))], pos(12, 25, 12, 8), unit="celsius",
       interval="30s", width=2, thresholds=steps("green", None, "orange", -25, "red", -15), threshold_style="dashed",
       desc="Dashed lines: clear/cloudy (-25) and unsafe (-15) limits used by the simulator."),
    ts("Humidity", [q("A", "humidity", series(CW, "hum"))], pos(0, 33, 8, 8), unit="humidity", interval="30s",
       fill=10, minmax=(0, 100)),
    ts("Wind & gust", [q("A", "wind", series(CW, "wind")), q("B", "gust", series(CW, "gust", "max"))],
       pos(8, 33, 8, 8), unit="velocitykmh", interval="30s"),
    ts("Rain & light sensors", [q("A", "rain", series(CW, "rain")), q("B", "light", series(CW, "light"))],
       pos(16, 33, 8, 8), interval="30s", right=("light",),
       desc="rain: rain sensor frequency (low = wet). light: raw light sensor value (right axis)."),

    # ------------------------------------------------- Alcor seeing monitor ---
    row("Alcor Solar Seeing Monitor", 41),
    stat("Seeing (FWHM)", [q("A", "seeing", last(SEE, "seeing_arcsec"))], pos(0, 42, 6, 4), unit="arcsec",
         decimals=2, thresholds=SEEING_STEPS, color="background", graph="area", no_value="no sun",
         desc="< 1\" excellent, < 2\" good, < 3\" average, otherwise poor (manufacturer classes)."),
    stat("Fried parameter r₀", [q("A", "r0", last(SEE, "r0"))], pos(6, 42, 6, 4), unit="lengthmm", decimals=1,
         graph="area", fixed="text", no_value="no sun"),
    stat("Box temperature", [q("A", "temp", last(SEE, "temp_inside_box"))], pos(12, 42, 6, 4), unit="celsius",
         decimals=1, thresholds=steps("green", None, "orange", 45, "red", 60), graph="area"),
    stat("Valid seeing", [q("A", "valid", last(SEE, "valid_seeing"))], pos(18, 42, 6, 4), color="background",
         thresholds=steps("#808080", None, "green", 1),
         mappings=[{"type": "value", "options": {"1": {"text": "YES", "color": "green", "index": 0},
                                                 "0": {"text": "NO (no sun)", "color": "#808080", "index": 1}}}]),
    ts("Seeing", [q("A", "seeing", series(SEE, "seeing_arcsec")),
                  q("B", "seeing max", series(SEE, "seeing_arcsec", "max"))],
       pos(0, 46, 12, 8), unit="arcsec", decimals=2, interval="10s", thresholds=SEEING_STEPS,
       threshold_style="dashed", desc="Dashed lines: 1\" / 2\" / 3\" quality classes."),
    ts("Fried parameter r₀", [q("A", "r0", series(SEE, "r0"))], pos(12, 46, 12, 8), unit="lengthmm",
       interval="10s"),
    ts("Sun signal (filtered mean ADU)", [q("A", "mean ADU F", series(SEE, "mean_adu_f")),
                                         q("B", "valid", series(SEE, "valid_seeing", "max"))],
       pos(0, 54, 12, 8), interval="10s", right=("valid",),
       desc="Raw solar signal level; drops at night and under clouds. valid (right axis): 1 = seeing computed."),
    ts("Box temperature", [q("A", "temp", series(SEE, "temp_inside_box"))], pos(12, 54, 12, 8), unit="celsius",
       interval="10s"),

    # ----------------------------------------------------------- telegraf ---
    row("Telegraf", 62),
    ts("CPU idle", [q("A", "$tag_host", 'SELECT mean("usage_idle") FROM "cpu" WHERE $timeFilter '
                                         'GROUP BY time($__interval), "host" fill(null)')],
       pos(0, 63, 24, 7), unit="percent", fill=10, minmax=(0, 100)),
]

def link(title, uid):
    return {"title": title, "type": "link", "url": f"/d/{uid}", "icon": "dashboard",
            "keepTime": False, "includeVars": False, "targetBlank": False, "tooltip": "", "tags": []}


dashboard = {
    "uid": "wrwo-telemetry", "title": "WRW telemetry", "tags": ["wrwo"], "timezone": "browser",
    "editable": True, "graphTooltip": 1, "refresh": "10s", "time": {"from": "now-1h", "to": "now"},
    "timepicker": {"refresh_intervals": ["5s", "10s", "30s", "1m", "5m"]}, "schemaVersion": 39,
    "version": 4, "templating": {"list": []}, "annotations": {"list": []}, "panels": panels,
    "links": [link("Daily statistics", "wrwo-daily")],
}


# ================================================================ daily statistics ===
# Reads retention policy "daily", filled by the continuous query "daily_stats" that
# Node-RED creates on start: one point per local day per measurement with
# mean_<field>, min_<field>, max_<field> for every numeric field, plus "points".
# Today's row is partial and recomputed every hour.

def daily(m):
    return f'"wrwo"."daily"."{m}"'


def table(title, targets, pos_, desc=None, decimals=2, merge=False):
    p = {"id": next(_ids), "type": "table", "title": title, "datasource": DS, "gridPos": pos_,
         "targets": targets,
         "fieldConfig": {"defaults": {"decimals": decimals, "custom": {"align": "auto"}},
                         "overrides": [{"matcher": {"id": "byName", "options": "Time"},
                                        "properties": [{"id": "unit", "value": "time:YYYY-MM-DD"},
                                                       {"id": "displayName", "value": "Day"}]},
                                       {"matcher": {"id": "byRegexp", "options": ".*points.*"},
                                        "properties": [{"id": "decimals", "value": 0}]}]},
         "options": {"showHeader": True, "cellHeight": "sm",
                     "sortBy": [{"displayName": "Day", "desc": True}]}}
    if merge:
        p["transformations"] = [{"id": "merge", "options": {}}]
    if desc:
        p["description"] = desc
    return p


def tq(ref, query):
    return {"refId": ref, "rawQuery": True, "resultFormat": "table", "query": query}


def cols(*pairs):
    """cols(('min_temp', 'temp min'), ...) -> 'SELECT "min_temp" AS "temp min", ...'"""
    return "SELECT " + ", ".join(f'{e if "*" in e else chr(34) + e + chr(34)} AS "{a}"' for e, a in pairs)


DAY_TS = dict(interval="1d", draw="line", width=1)

daily_panels = [
    row("Daily summary", 0),
    table("Pipeline: points and worst delay per day",
          [tq("A", cols(("points", "cloudwatcher points"), ("max_delay_s", "cloudwatcher max delay (s)"))
              + f" FROM {daily(CW)} WHERE $timeFilter"),
           tq("B", cols(("points", "seeing points"), ("max_delay_s", "seeing max delay (s)"))
              + f" FROM {daily(SEE)} WHERE $timeFilter")],
          pos(0, 1, 24, 7), merge=True,
          desc="Compare with the other machine: SOM and CAM should have the same points per day. "
               "Max delay shows the longest SOM→CAM outage of the day."),
    table("CloudWatcher per day",
          [tq("A", cols(("points", "points"), ("min_temp", "temp min °C"), ("mean_temp", "temp mean"),
                        ("max_temp", "temp max"), ("min_hum", "hum min %"), ("mean_hum", "hum mean"),
                        ("max_hum", "hum max"), ("mean_dewp", "dew point mean °C"),
                        ("min_clouds", "clouds min"), ("mean_clouds", "clouds mean"), ("max_clouds", "clouds max"),
                        ("mean_wind", "wind mean km/h"), ("max_gust", "gust max"), ("min_rain", "rain min"),
                        ('"mean_safe" * 100', "safe % of day"))
              + f" FROM {daily(CW)} WHERE $timeFilter")],
          pos(0, 8, 24, 8), decimals=1,
          desc="safe % of day = share of CloudWatcher samples with safe=1. rain min < 1700 = it rained."),
    table("Alcor seeing per day",
          [tq("A", cols(("points", "points"), ("min_seeing_arcsec", "seeing min (arcsec)"),
                        ("mean_seeing_arcsec", "seeing mean"), ("max_seeing_arcsec", "seeing max"),
                        ("mean_r0", "r₀ mean mm"), ("max_r0", "r₀ max mm"),
                        ("min_temp_inside_box", "box temp min °C"), ("max_temp_inside_box", "box temp max °C"),
                        ('"mean_valid_seeing" * 100', "valid % of samples"))
              + f" FROM {daily(SEE)} WHERE $timeFilter")],
          pos(0, 16, 24, 8),
          desc="Seeing statistics over the valid (sunlit) samples only. valid % ≈ share of the day with sun."),

    row("Daily trends", 24),
    ts("Seeing min / mean / max", [q("A", "$col", cols(("min_seeing_arcsec", "min"), ("mean_seeing_arcsec", "mean"),
                                                      ("max_seeing_arcsec", "max"))
                                     + f" FROM {daily(SEE)} WHERE $timeFilter")],
       pos(0, 25, 12, 8), unit="arcsec", **DAY_TS, thresholds=SEEING_STEPS, threshold_style="dashed"),
    ts("Temperature min / mean / max", [q("A", "$col", cols(("min_temp", "min"), ("mean_temp", "mean"),
                                                           ("max_temp", "max"))
                                          + f" FROM {daily(CW)} WHERE $timeFilter")],
       pos(12, 25, 12, 8), unit="celsius", **DAY_TS),
    ts("Safe share of the day", [q("A", "safe %", cols(('"mean_safe" * 100', "safe"))
                                   + f" FROM {daily(CW)} WHERE $timeFilter")],
       pos(0, 33, 12, 8), unit="percent", minmax=(0, 100), interval="1d", draw="bars", fill=60),
    ts("Points per day", [q("A", "cloudwatcher", cols(("points", "points")) + f" FROM {daily(CW)} WHERE $timeFilter"),
                          q("B", "seeing", cols(("points", "points")) + f" FROM {daily(SEE)} WHERE $timeFilter")],
       pos(12, 33, 12, 8), interval="1d", draw="bars", fill=60, right=("cloudwatcher",),
       desc="A drop = data missing that day (device, bridge or link problem)."),

    row("All values: min / mean / max of every numeric field", 41),
    table("CloudWatcher: all fields", [tq("A", f"SELECT * FROM {daily(CW)} WHERE $timeFilter")], pos(0, 42, 24, 8)),
    table("Alcor seeing: all fields", [tq("A", f"SELECT * FROM {daily(SEE)} WHERE $timeFilter")], pos(0, 50, 24, 8)),
    table("Telegraf CPU: all fields", [tq("A", f'SELECT * FROM {daily("cpu")} WHERE $timeFilter')], pos(0, 58, 24, 6)),
]

daily_dashboard = {
    "uid": "wrwo-daily", "title": "WRW daily statistics", "tags": ["wrwo"], "timezone": "browser",
    "editable": True, "graphTooltip": 1, "refresh": "5m", "time": {"from": "now-30d", "to": "now"},
    "timepicker": {"refresh_intervals": ["1m", "5m", "15m", "1h"]}, "schemaVersion": 39,
    "version": 1, "templating": {"list": []}, "annotations": {"list": []}, "panels": daily_panels,
    "links": [link("Live telemetry", "wrwo-telemetry")],
    "description": "Per local day, from InfluxDB retention policy 'daily' (continuous query daily_stats). "
                   "Today is partial and updated hourly.",
}

for name, d in (("wrwo.json", dashboard), ("wrwo-daily.json", daily_dashboard)):
    out = pathlib.Path(__file__).parent / "dashboards" / name
    out.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print("wrote", out)
