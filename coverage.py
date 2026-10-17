# TODO(A): replace with SRTM horizon masks + USFS canopy + skyfield passes
"""Fake sky-openness coverage along the trail, built from per-point canopy and ridge data."""
import re
from datetime import datetime

from data import SERVICES

GREEN_MIN = 0.6
YELLOW_MIN = 0.3
CHECKIN_NAMES = ["Forest junction", "Ridge viewpoint", "Boulder field"]
START_MINUTES = 9 * 60  # 9:00am default
CHECKIN_GAP_MINUTES = 90


def _fmt(minutes):
    minutes = int(minutes) % (24 * 60)
    h, m = divmod(minutes, 60)
    suffix = "am" if h < 12 else "pm"
    return f"{(h - 1) % 12 + 1}:{m:02d}{suffix}"


def parse_start_time(start_time, default=START_MINUTES):
    """Parse '9:00am', '09:00', '14:30', etc. into minutes since midnight."""
    if start_time is None or start_time == "":
        return default
    if isinstance(start_time, int):
        return start_time
    text = str(start_time).strip().lower()
    # HTML time input: HH:MM
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h < 24 and 0 <= mi < 60:
            return h * 60 + mi
    m = re.fullmatch(r"(\d{1,2}):(\d{2})\s*([ap]m?)", text)
    if m:
        h, mi, ap = int(m.group(1)), int(m.group(2)), m.group(3)[0]
        if h == 12:
            h = 0
        if ap == "p":
            h += 12
        return h * 60 + mi
    m = re.fullmatch(r"(\d{1,2})\s*([ap]m?)", text)
    if m:
        h, ap = int(m.group(1)), m.group(2)[0]
        if h == 12:
            h = 0
        if ap == "p":
            h += 12
        return h * 60
    return default


def start_time_for_input(start_time, default="09:00"):
    """Normalize any start_time string to HH:MM for <input type=time>."""
    minutes = parse_start_time(start_time, parse_start_time(default))
    h, m = divmod(minutes, 60)
    return f"{h:02d}:{m:02d}"


def _color(openness):
    if openness >= GREEN_MIN:
        return "green"
    if openness >= YELLOW_MIN:
        return "yellow"
    return "red"


def _windows(color, t):
    if color == "green":
        return [f"{_fmt(t - 10)}–{_fmt(t + 5)}", f"{_fmt(t + 15)}–{_fmt(t + 30)}"]
    if color == "yellow":
        return [f"{_fmt(t - 5)}–{_fmt(t + 2)}"]
    return []


def get_coverage(trail, profile, services=None, trip_date=None, start_time=None):
    """
    Coverage along the trail.
    Optional trip_date / start_time personalize check-in clocks (and are ready for
    Track A's real satellite windows when a date is supplied).
    """
    if services is None:
        services = profile["services"]
    # Prefer explicit args; fall back to trail defaults used by older callers.
    if start_time is None:
        start_time = trail.get("start_time")
    if trip_date is None:
        trip_date = trail.get("trip_date")
    start_minutes = parse_start_time(start_time, START_MINUTES)

    all_blocked = all(SERVICES[s]["blocked_by_south_ridge"] for s in services)

    segments = []
    for p in trail["points"]:
        if not services:
            openness = 0.0
        elif all_blocked and p["south_blocked"]:
            openness = 0.1
        else:
            openness = round(1 - p["canopy"], 2)
        segments.append({"lat": p["lat"], "lon": p["lon"], "openness": openness, "color": _color(openness)})

    n = len(segments)
    checkins = []
    for i, frac in enumerate((0.25, 0.5, 0.75)):
        idx = int(frac * (n - 1))
        seg = segments[idx]
        t = start_minutes + CHECKIN_GAP_MINUTES * (i + 1)
        checkins.append({
            "idx": idx,
            "name": f"Check-in {i + 1}: {CHECKIN_NAMES[i]}",
            "lat": seg["lat"],
            "lon": seg["lon"],
            "time": _fmt(t),
            "windows": _windows(seg["color"], t),
            "color": seg["color"],
            "covered": seg["color"] != "red",
        })

    note = "Demo estimate · terrain + canopy"
    if trip_date:
        note = f"Demo estimate · terrain + canopy · trip {trip_date}"

    return {
        "segments": segments,
        "checkins": checkins,
        "confidence": "medium",
        "confidence_note": note,
        "start_time": _fmt(start_minutes),
        "trip_date": trip_date,
        "services": list(services),
    }


def trip_month_label(trip_date, fallback="this trip"):
    """Pretty month name from an ISO date for recommendation copy."""
    if not trip_date:
        return fallback
    try:
        return datetime.strptime(trip_date, "%Y-%m-%d").strftime("%B")
    except ValueError:
        return fallback
