#!/usr/bin/env python3
"""
Alcor Solar Seeing Monitor (CSSMS, Microchip PIC18F14K50 USB HID) -> MQTT 5

Based on the manufacturer's test_CSSMS_AllOS.py: same HID commands (0x80 system info,
0x81 measurement), same byte layout and the same seeing / r0 formulas. Differences:
non-interactive, reconnects when the USB device or the broker goes away, and publishes
every measurement as JSON instead of printing / writing CSV.

  topic    pubdata/alcor/seeing  (MQ-BRIDGE adds the timestamp; none is sent here)
  payload  {"mean_adu_nf":..,"ec_adu_nf":..,"mean_adu_f":..,"ec_adu_f":..,"nb_samples":..,
            "temp_inside_box":..,"valid_seeing":1,"seeing_arcsec":..,"r0":..,
            "quality":"GOOD","serial":"1234","fw":"1.2"}
           seeing_arcsec / r0 / quality are left out when valid_seeing is 0.

Config from the environment (the testbed .env works as systemd EnvironmentFile):
  MQTT_HOST       localhost            MQ-BRIDGE host
  MQTT_PORT       $BRIDGE_PORT or 1883
  MQTT_USER       device
  MQTT_PASS       $DEVICE_PASS
  ALCOR_TOPIC     pubdata/alcor/seeing
  ALCOR_INTERVAL  2                    seconds between measurements (manufacturer: 2)

Usage:
  python3 alcor_ssm_mqtt.py            run, publish to MQTT
  python3 alcor_ssm_mqtt.py --stdout   print JSON only, no MQTT (check the device)
  python3 alcor_ssm_mqtt.py --once     one measurement, then exit (with --stdout: no MQTT)
"""
import argparse
import json
import math
import os
import signal
import socket
import struct
import sys
import time

VENDOR_ID, PRODUCT_ID = 0x04D8, 0x003F
PACKET_SIZE = 65
CMD_SYSTEM_INFO, CMD_MEASUREMENT = 0x80, 0x81

# constants from the manufacturer script
ONE_ADU_VOLTS = 4.096 / 65535.0
WAVELENGTH_M = 550e-9

TOPIC = os.environ.get("ALCOR_TOPIC", "pubdata/alcor/seeing")
INTERVAL = float(os.environ.get("ALCOR_INTERVAL", "2"))


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------- decoding ---
def decode_system_info(buf):
    """[1-2] version, [3] channel, [4] LED, [5-8] serial (BE uint), [9-24] 4 BE floats."""
    b = bytes(buf)
    serial, rshunt, gain_f, gain_nf, offset_v = struct.unpack_from(">Iffff", b, 5)
    return {"major_version": b[1], "minor_version": b[2], "channel_to_read": b[3],
            "led_enable": b[4] > 0, "serial": serial, "rshunt": rshunt,
            "gain_filtered": gain_f, "gain_unfiltered": gain_nf, "offset_volts": offset_v}


def seeing_from_raw(mean_adu_nf, ec_adu_nf):
    """Manufacturer formula -> (valid, seeing_arcsec, r0_mm)."""
    if not (ec_adu_nf > 0 and mean_adu_nf > 0):
        return False, 0.0, 0.0
    variance = max(0.0, ec_adu_nf - mean_adu_nf ** 2)
    theta_0_rad = math.sqrt(variance) * ONE_ADU_VOLTS / mean_adu_nf
    seeing_rad = 0.98 * WAVELENGTH_M / theta_0_rad if theta_0_rad > 0 else 0
    seeing_arcsec = seeing_rad * 206265.0
    r0 = 0.98 * WAVELENGTH_M / seeing_rad * 1000 if seeing_rad > 0 else 0   # mm
    return True, seeing_arcsec, r0


def decode_measurement(buf):
    """[1-16] MeanADU_NF, EC_ADU_NF, MeanADU_F, EC_ADU_F (BE floats), [17-20] Nb_Samples
    (BE uint), [25-28] TempInsideBox (BE float; the manufacturer comment says 21-24,
    its code reads 25-28)."""
    b = bytes(buf)
    mean_nf, ec_nf, mean_f, ec_f, nb = struct.unpack_from(">ffffI", b, 1)
    (temp_box,) = struct.unpack_from(">f", b, 25)
    valid, seeing, r0 = seeing_from_raw(mean_nf, ec_nf)
    return {"mean_adu_nf": mean_nf, "ec_adu_nf": ec_nf, "mean_adu_f": mean_f, "ec_adu_f": ec_f,
            "nb_samples": nb, "temp_inside_box": temp_box,
            "seeing_arcsec": seeing, "r0": r0, "valid_seeing": valid}


def quality(seeing_arcsec):
    return ("EXCELLENT" if seeing_arcsec < 1.0 else "GOOD" if seeing_arcsec < 2.0
            else "AVERAGE" if seeing_arcsec < 3.0 else "POOR")


def to_payload(m, info):
    p = {"mean_adu_nf": round(m["mean_adu_nf"], 4), "ec_adu_nf": round(m["ec_adu_nf"], 4),
         "mean_adu_f": round(m["mean_adu_f"], 4), "ec_adu_f": round(m["ec_adu_f"], 4),
         "nb_samples": m["nb_samples"], "temp_inside_box": round(m["temp_inside_box"], 2),
         "valid_seeing": int(m["valid_seeing"])}
    if m["valid_seeing"]:
        p.update(seeing_arcsec=round(m["seeing_arcsec"], 3), r0=round(m["r0"], 2),
                 quality=quality(m["seeing_arcsec"]))
    if info:
        p.update(serial=str(info["serial"]), fw=f"{info['major_version']}.{info['minor_version']}")
    return p


# --------------------------------------------------------------------- HID ---
def load_hid():
    """cython-hidapi, either backend (same API): 'hid' (pip install hidapi; libusb) or
    'hidraw' (Linux hidraw backend, also part of cython-hidapi). Raises SystemExit with a
    hint when neither is usable - e.g. the unrelated ctypes package python3-hid, which is
    also imported as 'hid' but has hid.Device instead of hid.device."""
    tried = []
    for name in ("hid", "hidraw"):
        try:
            mod = __import__(name)
        except ImportError as e:
            tried.append(f"{name}: {e}")
            continue
        if hasattr(mod, "device"):
            return mod
        tried.append(f"{name}: {getattr(mod, '__file__', '?')} has no device() (not cython-hidapi)")
    try:                                 # Debian/Pi OS trixie apt python3-hidapi = hidapi-cffi
        tried.append(f"hidapi: {__import__('hidapi').__file__} is a different binding (cffi), not used")
    except ImportError:
        pass
    raise SystemExit("no usable HID module (cython-hidapi):\n  " + "\n  ".join(tried) +
                     "\nInstall it in the Python that runs this script, e.g.\n"
                     "  venv/bin/pip install hidapi        (see requirements.txt)")


class SSM:
    hid = None                           # set by main() via load_hid()

    def __init__(self):
        self.dev = self.hid.device()
        self.dev.open(VENDOR_ID, PRODUCT_ID)
        try:
            self.dev.set_nonblocking(1)
        except Exception:
            pass
        log(f"USB: {self.dev.get_manufacturer_string()} - {self.dev.get_product_string()}"
            f" serial={self.dev.get_serial_number_string()}")

    def close(self):
        try:
            self.dev.close()
        except Exception:
            pass

    def _cmd(self, command, timeout_s=0.5):
        packet = [0x00, command] + [0x00] * (PACKET_SIZE - 2)
        if self.dev.write(packet) <= 0:
            raise IOError("HID write failed")
        time.sleep(0.1)
        end = time.time() + timeout_s
        while time.time() < end:
            r = self.dev.read(PACKET_SIZE)
            if r:
                return list(r)
            time.sleep(0.01)
        return None

    def system_info(self):
        r = self._cmd(CMD_SYSTEM_INFO)
        return decode_system_info(r) if r else None

    def measure(self):
        r = self._cmd(CMD_MEASUREMENT)
        return decode_measurement(r) if r else None


# -------------------------------------------------------------------- MQTT ---
def mqtt_client():
    try:
        import paho.mqtt.client as mqtt
        from paho.mqtt.enums import CallbackAPIVersion
    except ImportError as e:
        raise SystemExit(f"paho-mqtt 2.x needed ({e}). Pi OS trixie: sudo apt install python3-paho-mqtt;\n"
                         "  bookworm (apt has 1.6): venv/bin/pip install -r requirements.txt")
    from paho.mqtt.packettypes import PacketTypes
    from paho.mqtt.properties import Properties
    host = os.environ.get("MQTT_HOST", "localhost")
    port = int(os.environ.get("MQTT_PORT") or os.environ.get("BRIDGE_PORT") or 1883)
    c = mqtt.Client(CallbackAPIVersion.VERSION2, client_id=f"alcor-ssm-{socket.gethostname()}",
                    protocol=mqtt.MQTTv5)
    c.username_pw_set(os.environ.get("MQTT_USER", "device"),
                      os.environ.get("MQTT_PASS") or os.environ.get("DEVICE_PASS", ""))
    c.on_connect = lambda cl, u, f, rc, p: log(f"MQTT: connected to {host}:{port} rc={rc}"
                                               f" session_present={f.session_present}")
    c.on_disconnect = lambda cl, u, f, rc, p: log(f"MQTT: disconnected rc={rc}")
    c.reconnect_delay_set(1, 30)
    # MQTT 5 persistent session (clean_start False + session expiry) + QoS 1: unacknowledged
    # messages are resent after a reconnect; paho also keeps messages published while offline
    props = Properties(PacketTypes.CONNECT)
    props.SessionExpiryInterval = 3600
    c.connect_async(host, port, 30, clean_start=False, properties=props)
    c.loop_start()
    return c


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--stdout", action="store_true", help="print JSON, do not publish")
    ap.add_argument("--once", action="store_true", help="one measurement, then exit")
    args = ap.parse_args()

    SSM.hid = load_hid()                   # fail fast: retrying cannot fix a missing module
    log(f"HID module: {SSM.hid.__name__} ({getattr(SSM.hid, '__file__', '?')})")
    stop = []
    signal.signal(signal.SIGTERM, lambda *a: stop.append(1))
    client = None if args.stdout else mqtt_client()
    ssm, info, fails = None, None, 0
    next_t = time.monotonic()

    try:
        while not stop:
            if ssm is None:
                try:
                    ssm = SSM()
                    info = ssm.system_info()
                    if info:
                        log(f"SSM: fw {info['major_version']}.{info['minor_version']} serial {info['serial']}"
                            f" rshunt={info['rshunt']:.6f} gain_f={info['gain_filtered']:.6f}"
                            f" gain_nf={info['gain_unfiltered']:.6f} offset={info['offset_volts']:.6f} V")
                    fails = 0
                except Exception as e:
                    log(f"USB: cannot open {VENDOR_ID:04x}:{PRODUCT_ID:04x}: {e}; retry in 5 s")
                    ssm = None
                    time.sleep(5)
                    continue

            try:
                m = ssm.measure()
            except Exception as e:
                log(f"USB: read error: {e}")
                m = None
            if m is None:
                fails += 1
                if fails >= 3:                     # unplugged / hung: reopen
                    log("USB: no data 3x, reopening")
                    ssm.close()
                    ssm = None
            else:
                fails = 0
                payload = json.dumps(to_payload(m, info))
                if client:
                    client.publish(TOPIC, payload, qos=1)
                else:
                    print(payload, flush=True)
                if args.once:
                    break

            next_t += INTERVAL
            time.sleep(max(0.0, next_t - time.monotonic()))
            if next_t < time.monotonic() - INTERVAL:   # fell behind (USB retry): resync
                next_t = time.monotonic()
    except KeyboardInterrupt:
        pass
    finally:
        if ssm:
            ssm.close()
        if client:
            time.sleep(1)                          # let the last QoS 1 publish go out
            client.loop_stop()
            client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
