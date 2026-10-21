#!/usr/bin/env python3
"""
Fake SOM instruments -> MQ-BRIDGE (MQTT 5, QoS 0 like most small devices / telegraf).

  pubdata/lunatico/cloudwatcher  JSON  AAG CloudWatcher format, every CW_INTERVAL s (default 30)
                                       {"dataGMTTime":"2026/10/15 03:26:00","cwinfo":"Serial: 1588, FW: 5.73",
                                        "slddata":"...","clouds":8.82,"cloudsSafe":"Unsafe","temp":36.76,...}
  pubdata/alcor/seeing           JSON  Alcor Solar Seeing Monitor, as devices/alcor/alcor_ssm_mqtt.py sends it,
                                       every INTERVAL s: {"mean_adu_nf":..,"ec_adu_nf":..,..,"seeing_arcsec":..}
  pubdata/telegraf/cpu           telegraf JSON {"fields":{...},"name":"cpu","tags":{...},"timestamp":...}

No timestamps used from the devices: the plugin in MQ-BRIDGE stamps them.
"n" (cpu) is a counter: a gap in n in InfluxDB = a lost message.
The CloudWatcher and Alcor payloads have no counter, like the real devices.
"""
import json
import math
import os
import random
import time

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

HOST = os.environ.get("BRIDGE_HOST", "mqbridge")
PORT = int(os.environ.get("BRIDGE_PORT", "1883"))
USER = os.environ.get("DEVICE_USER", "device")
PASS = os.environ.get("DEVICE_PASS", "")
INTERVAL = float(os.environ.get("INTERVAL", "2"))
CW_INTERVAL = float(os.environ.get("CW_INTERVAL", "30"))
UTC_OFFSET_H = float(os.environ.get("UTC_OFFSET_H", "7"))      # CloudWatcher local time (WIB)
QOS = int(os.environ.get("QOS", "0"))

c = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="sim-som-devices", protocol=mqtt.MQTTv5)
c.username_pw_set(USER, PASS)
c.on_connect = lambda cl, u, f, rc, p: print(f"simulator: connected to {HOST}:{PORT} rc={rc}", flush=True)
c.reconnect_delay_set(1, 10)
c.connect_async(HOST, PORT, 30)
c.loop_start()


def local_hour(t):
    lt = time.gmtime(t + UTC_OFFSET_H * 3600)
    return lt, lt.tm_hour + lt.tm_min / 60


def ambient(hour):
    return 22 + 7 * math.cos(2 * math.pi * (hour - 14) / 24)


class CloudWatcher:
    """AAG CloudWatcher: slowly varying weather + an occasional short rain shower."""

    def __init__(self):
        self.clouds = -25.0      # sky - ambient (corrected), < -15 clear
        self.cloudy = False      # weather regime: clear (target -25) or cloudy (target -5)
        self.wind = 5.0          # km/h
        self.rain_left = 0       # samples left in the current shower

    def sample(self, t):
        local, hour = local_hour(t)
        temp = ambient(hour) + random.gauss(0, 0.15)
        hum = min(100, max(20, 86 - 2.2 * (temp - 15) + random.gauss(0, 2)))
        g = math.log(hum / 100) + 17.62 * temp / (243.12 + temp)      # Magnus
        dewp = 243.12 * g / (17.62 - g)

        if random.random() < 1 / 180:                                  # regime change ~ every 1.5 h
            self.cloudy = not self.cloudy
        target = -5 if self.cloudy else -25
        self.clouds = min(15, max(-35, self.clouds + 0.05 * (target - self.clouds) + random.gauss(0, 0.8)))
        rawir = temp + self.clouds - 24 + random.gauss(0, 0.3)
        self.wind = min(40, max(0, self.wind + 0.1 * (8 - self.wind) + random.gauss(0, 2)))
        gust = self.wind + abs(random.gauss(0, 3))
        if self.rain_left == 0 and random.random() < 1 / 120:        # ~ one shower per hour at 30 s
            self.rain_left = 10
        raining = self.rain_left > 0
        self.rain_left = max(0, self.rain_left - 1)
        rain = int(random.gauss(450, 80) if raining else random.gauss(2176, 15))
        day = 6 <= hour < 18
        light = int(random.gauss(3, 1) if day else random.gauss(5200, 200))
        light = max(0, light)

        cloudsSafe = "Unsafe" if self.clouds > -15 else "Safe"
        windSafe = "Unsafe" if self.wind > 30 else "Safe"
        rainSafe = "Unsafe" if rain < 1700 else "Safe"
        humSafe = "Unsafe" if hum > 90 else "Safe"
        lightSafe = "Safe"
        safe = int(all(s == "Safe" for s in (cloudsSafe, windSafe, rainSafe, humSafe, lightSafe)))

        # Boltwood "single line data" as the CloudWatcher writes it
        cc = 1 if self.clouds < -25 else 2 if self.clouds < -15 else 3
        wc = 1 if self.wind < 20 else 2 if self.wind < 30 else 3
        rc = 3 if raining else 1
        dc = 3 if day else 1
        serial = (t + UTC_OFFSET_H * 3600) / 86400 + 25569             # days since 1899-12-30
        sld = (f"{time.strftime('%Y-%m-%d %H:%M:%S', local)}.00 C K "
               f"{self.clouds:6.1f} {temp:6.1f} {temp:6.1f} {self.wind:6.1f} {int(hum):3d} {dewp:6.1f} "
               f"{10:3d} {int(raining)} {int(raining)} 00000 {serial:012.5f} {cc} {wc} {rc} {dc} 1 1 -99.99")

        return {
            "dataGMTTime": time.strftime("%Y/%m/%d %H:%M:%S", time.gmtime(t)),
            "cwinfo": "Serial: 1588, FW: 5.73",
            "slddata": sld,
            "clouds": round(self.clouds, 2), "cloudsSafe": cloudsSafe,
            "temp": round(temp, 2),
            "wind": int(round(self.wind)), "windSafe": windSafe,
            "gust": int(round(gust)),
            "rain": rain, "rainSafe": rainSafe,
            "light": light, "lightSafe": lightSafe,
            "switch": -1,
            "safe": safe,
            "hum": int(round(hum)), "humSafe": humSafe,
            "dewp": round(dewp, 2),
            "rawir": round(rawir, 2),
            "abspress": 0, "relpress": 0, "pressureSafe": "Unknown",
        }


class AlcorSSM:
    """Alcor Solar Seeing Monitor. Works backwards from a seeing value to the raw ADU
    values, so the payload goes through the manufacturer formula like the real device.
    NOTE: the real raw ranges are unknown; only seeing/r0 are meant to look realistic."""
    ONE_ADU_VOLTS = 4.096 / 65535.0
    WAVELENGTH_M = 550e-9

    def __init__(self):
        self.seeing_offset = 0.0     # slow random walk on top of the daily curve

    def sample(self, t, cloudy):
        _, hour = local_hour(t)
        temp_box = ambient(hour) + 6 + random.gauss(0, 0.1)
        sun = max(0.0, math.sin(math.pi * (hour - 6) / 12))           # 0 at night
        if sun < 0.05:                                                 # no sun: no seeing
            mean_nf = ec_nf = 0.0
            mean_f = random.gauss(50, 2)
        else:
            sun *= 0.3 if cloudy else 1.0
            self.seeing_offset = min(1.5, max(-0.8, self.seeing_offset + random.gauss(0, 0.05)))
            # good in the morning, worse when the ground heats up, worse through clouds
            seeing = 1.8 + 1.6 * math.sin(math.pi * (hour - 6) / 12) ** 2 + self.seeing_offset                 + (1.0 if cloudy else 0.0) + random.gauss(0, 0.15)
            seeing = max(0.4, seeing)
            theta_0 = 0.98 * self.WAVELENGTH_M / (seeing / 206265.0)
            mean_nf = random.gauss(20, 0.5)
            std = theta_0 * mean_nf / self.ONE_ADU_VOLTS
            ec_nf = std ** 2 + mean_nf ** 2
            mean_f = 30000 * sun + random.gauss(0, 20)
        ec_f = mean_f ** 2 * (1 + 1e-4)
        p = {"mean_adu_nf": round(mean_nf, 4), "ec_adu_nf": round(ec_nf, 4),
             "mean_adu_f": round(mean_f, 4), "ec_adu_f": round(ec_f, 4),
             "nb_samples": int(random.gauss(4000, 10)), "temp_inside_box": round(temp_box, 2)}
        # derived values exactly as devices/alcor/alcor_ssm_mqtt.py computes them
        valid = ec_nf > 0 and mean_nf > 0
        p["valid_seeing"] = int(valid)
        if valid:
            theta = math.sqrt(max(0.0, ec_nf - mean_nf ** 2)) * self.ONE_ADU_VOLTS / mean_nf
            s_rad = 0.98 * self.WAVELENGTH_M / theta
            s_arc = s_rad * 206265.0
            p.update(seeing_arcsec=round(s_arc, 3), r0=round(0.98 * self.WAVELENGTH_M / s_rad * 1000, 2),
                     quality="EXCELLENT" if s_arc < 1 else "GOOD" if s_arc < 2 else "AVERAGE" if s_arc < 3 else "POOR")
        p.update(serial="20231", fw="1.4")
        return p


cw = CloudWatcher()
ssm = AlcorSSM()
next_cw = 0.0
n = 0
while True:
    n += 1
    t = time.time()
    if t >= next_cw:
        c.publish("pubdata/lunatico/cloudwatcher", json.dumps(cw.sample(t)), qos=QOS)
        next_cw = t + CW_INTERVAL
    c.publish("pubdata/alcor/seeing", json.dumps(ssm.sample(t, cw.cloudy)), qos=QOS)
    if n % 5 == 0:
        c.publish("pubdata/telegraf/cpu", json.dumps({
            "fields": {"usage_idle": round(90 + random.gauss(0, 2), 2), "n": n // 5},
            "name": "cpu", "tags": {"cpu": "cpu-total", "host": "som-pi"}, "timestamp": int(t)}), qos=QOS)
    if n % 30 == 0:
        print(f"simulator: {n} cycles", flush=True)
    time.sleep(INTERVAL)
