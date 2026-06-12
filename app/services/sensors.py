"""Mock datacenter environmental sensors with a continuous, live feel.

Values are generated deterministically from the timestamp (sine waves + per-bucket
hashed noise), so the same instant always yields the same value — giving a coherent
history that smoothly evolves over time without any storage.
"""

import math
import hashlib
from datetime import datetime, timezone, timedelta

# key, label, unit, icon, baseline, amplitude, period(min), warn, alarm, kind
SENSORS = [
    {"key": "temp",     "label": "Temperature",   "unit": "°C",   "icon": "fa-temperature-half", "base": 22.5, "amp": 2.5,  "period": 90,  "warn": 27,   "alarm": 32,   "kind": "analog"},
    {"key": "humidity", "label": "Humidity",      "unit": "%",    "icon": "fa-droplet",          "base": 45,   "amp": 8,    "period": 120, "warn": 60,   "alarm": 70,   "kind": "analog"},
    {"key": "co2",      "label": "CO₂",           "unit": "ppm",  "icon": "fa-cloud",            "base": 650,  "amp": 180,  "period": 60,  "warn": 1000, "alarm": 1500, "kind": "analog"},
    {"key": "co",       "label": "CO",            "unit": "ppm",  "icon": "fa-smog",             "base": 3,    "amp": 2,    "period": 75,  "warn": 25,   "alarm": 50,   "kind": "analog"},
    {"key": "ch4",      "label": "CH₄ (Methane)", "unit": "%LEL", "icon": "fa-fire-flame-simple","base": 2,    "amp": 1.5,  "period": 110, "warn": 10,   "alarm": 20,   "kind": "analog"},
    {"key": "airflow",  "label": "Airflow",       "unit": "m/s",  "icon": "fa-wind",             "base": 2.2,  "amp": 0.6,  "period": 40,  "warn": 1.0,  "alarm": 0.5,  "kind": "analog_low"},
    {"key": "power",    "label": "Rack Power",    "unit": "kW",   "icon": "fa-bolt",             "base": 6.5,  "amp": 1.8,  "period": 50,  "warn": 9,    "alarm": 11,   "kind": "analog"},
    {"key": "presence", "label": "Presence",      "unit": "",     "icon": "fa-person-walking",   "base": 0,    "amp": 1,    "period": 17,  "warn": None, "alarm": None, "kind": "binary"},
    {"key": "smoke",    "label": "Smoke",         "unit": "",     "icon": "fa-fire",             "base": 0,    "amp": 1,    "period": 240, "warn": None, "alarm": 1,    "kind": "binary"},
    {"key": "leak",     "label": "Water Leak",    "unit": "",     "icon": "fa-house-flood-water","base": 0,    "amp": 1,    "period": 300, "warn": None, "alarm": 1,    "kind": "binary"},
]
_BY_KEY = {s["key"]: s for s in SENSORS}


def _noise(key, bucket):
    h = hashlib.sha256(f"{key}:{bucket}".encode()).hexdigest()
    return (int(h[:8], 16) / 0xFFFFFFFF) * 2 - 1  # -1..1


def _value(s, ts):
    epoch_min = ts.timestamp() / 60.0
    if s["kind"] == "binary":
        # Occasional, deterministic blips (mostly 0)
        n = _noise(s["key"], int(epoch_min // 7))
        thresh = 0.93 if s["key"] == "presence" else 0.985
        return 1 if n > (2 * thresh - 1) else 0
    phase = int(hashlib.md5(s["key"].encode()).hexdigest()[:4], 16) / 0xFFFF * math.tau
    wave = math.sin(epoch_min / s["period"] * math.tau + phase)
    noise = _noise(s["key"], int(epoch_min // 5)) * (s["amp"] * 0.25)
    val = s["base"] + s["amp"] * wave + noise
    if s["key"] in ("co2", "co", "power", "airflow", "ch4"):
        val = max(0, val)
    return round(val, 2)


def _status(s, val):
    if s["kind"] == "binary":
        return "alarm" if (val and s["alarm"]) else "ok"
    if s["kind"] == "analog_low":  # lower is worse (airflow)
        if s["alarm"] is not None and val <= s["alarm"]:
            return "alarm"
        if s["warn"] is not None and val <= s["warn"]:
            return "warn"
        return "ok"
    if s["alarm"] is not None and val >= s["alarm"]:
        return "alarm"
    if s["warn"] is not None and val >= s["warn"]:
        return "warn"
    return "ok"


def current():
    """Returns the current reading for every sensor."""
    now = datetime.now(timezone.utc)
    out = []
    for s in SENSORS:
        v = _value(s, now)
        out.append({"key": s["key"], "label": s["label"], "unit": s["unit"], "icon": s["icon"],
                    "kind": s["kind"], "value": v, "status": _status(s, v)})
    return out


def history(key, points=72, step_min=20):
    """Returns the last `points` readings for one sensor (oldest first)."""
    s = _BY_KEY.get(key)
    if not s:
        return {"labels": [], "values": []}
    now = datetime.now(timezone.utc)
    labels, values = [], []
    for i in range(points - 1, -1, -1):
        t = now - timedelta(minutes=i * step_min)
        labels.append(t.strftime('%H:%M'))
        values.append(_value(s, t))
    return {"labels": labels, "values": values}


def all_histories(points=72, step_min=20):
    return {s["key"]: history(s["key"], points, step_min) for s in SENSORS}
