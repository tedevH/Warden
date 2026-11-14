"""Warden Box bridge: connects the Arduino (USB serial) to the orchestrator.

    make box            use the Arduino plugged into this Mac
    make box-sim        no Arduino: type  p = press button,  k 512 = turn knob (0-1023),  u = caregiver unlock

Button press -> POST /box/press   (approves what Warden is waiting on; otherwise locks everything and gets help)
Knob         -> POST /box/knob    (lowers the spending limit; it can never raise it above the family's cap)
Light        <- GET  /box         (ok / approve / locked / alert), sent to the Arduino as L0..L3
"""
import argparse
import glob
import os
import sys
import threading
import time

import httpx

ORCH = os.getenv("ORCH_URL", "http://127.0.0.1:8200")
LIGHT = {"ok": "0", "approve": "1", "locked": "2", "alert": "3"}
WORDS = {"0": "off (all good)", "1": "slow blink (press to approve)", "2": "solid (locked down)",
         "3": "fast blink (scam blocked)"}


def find_port():
    ports = sorted(glob.glob("/dev/cu.usbmodem*") + glob.glob("/dev/cu.usbserial*") + glob.glob("/dev/cu.wchusbserial*"))
    return ports[0] if ports else None


def handle(http, line):
    line = line.strip()
    if not line:
        return
    try:
        if line == "PRESS":
            r = http.post("/box/press", json={}).json()
            print(f"button -> {r.get('did')}: {r}", flush=True)
        elif line.startswith("KNOB"):
            r = http.post("/box/knob", json={"value": int(line.split()[1])}).json()
            print(f"knob -> spending limit ${r['limit']:.0f}", flush=True)
        elif line == "u":
            print(f"caregiver unlock -> {http.post('/unlock', json={'source': 'caregiver'}).json()}", flush=True)
        elif line == "READY":
            print("Arduino is ready", flush=True)
    except (httpx.HTTPError, ValueError, IndexError) as e:
        print(f"! {line!r}: {e} (is the orchestrator running? make orchestrator)", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true", help="no Arduino: read p / k N / u from the keyboard")
    ap.add_argument("--port", help="serial port (default: first /dev/cu.usbmodem*)")
    a = ap.parse_args()
    http = httpx.Client(base_url=ORCH, timeout=5)

    ser = None
    if not a.sim:
        import serial
        port = a.port or find_port()
        if not port:
            sys.exit("No Arduino found. Plug it in, or run `make box-sim` to try it without one.")
        ser = serial.Serial(port, 9600, timeout=0.2)
        print(f"Connected to the Arduino on {port}", flush=True)
        time.sleep(2)  # the Uno resets when the port opens

    def reader():
        if ser:
            while True:
                handle(http, ser.readline().decode("ascii", "ignore"))
        for line in sys.stdin:
            line = line.strip()
            handle(http, "PRESS" if line == "p" else "KNOB " + line[1:].strip() if line.startswith("k") else line)

    threading.Thread(target=reader, daemon=True).start()
    sent = None
    while True:
        try:
            code = LIGHT.get(http.get("/box").json()["light"], "0")
        except (httpx.HTTPError, ValueError, KeyError):
            code = sent or "0"
        if code != sent:
            sent = code
            print(f"light -> {WORDS[code]}", flush=True)
        if ser:
            ser.write(f"L{code}".encode())  # resend every tick so a reset Arduino catches up
        time.sleep(0.4)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
