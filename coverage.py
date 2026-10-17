# TODO(A): replace with SRTM horizon masks + USFS canopy + skyfield passes
"""Fake sky-openness coverage along the trail, built from per-point canopy and ridge data."""
import re

from data import SERVICES

GREEN_MIN = 0.6
YELLOW_MIN = 0.3
CHECKIN_NAMES = ["Forest junction", "Ridge viewpoint", "Boulder field"]
START_MINUTES = 9 * 60  # 9:00am
CHECKIN_GAP_MINUTES = 90


def _fmt(minutes):
    minutes = int(minutes) % (24 * 60)
    h, m = divmod(minutes, 60)
    suffix = "am" if h < 12 else "pm"
    return f"{(h - 1) % 12 + 1}:{m:02d}{suffix}"


def _parse_start_minutes(start_time, default=START_MINUTES):
    """Accept '9:00am', '09:00', or '9:00 AM'. Falls back to default on bad input."""
    if not start_time:
        return default
    text = str(start_time).strip().lower().replace(" ", "")
    match = re.fullmatch(r"(\d{1,2}):(\d{2})(am|pm)?", text)
    if not match:
        return default
    h, m = int(match.group(1)), int(match.group(2))
    ampm = match.group(3)
    if ampm:
        if not 1 <= h <= 12 or not 0 <= m <= 59:
            return default
        if ampm == "am":
            h = 0 if h == 12 else h
        else:
            h = 12 if h == 12 else h + 12
    elif not 0 <= h <= 23 or not 0 <= m <= 59:
        return default
    return h * 60 + m


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
    """Estimate coverage along the trail.

    Optional trip_date / start_time shift check-in clocks (Track C / A shared).
    Fake mode ignores orbital day-of-year; Track A can use trip_date for real passes.
    """
    if services is None:
        services = profile["services"]
    all_blocked = bool(services) and all(SERVICES[s]["blocked_by_south_ridge"] for s in services)
    start_minutes = _parse_start_minutes(start_time or trail.get("start_time"), START_MINUTES)

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

    result = {
        "segments": segments,
        "checkins": checkins,
        "confidence": "medium",
        "confidence_note": "simulated terrain + canopy (not live satellite passes)",
        "start_time": _fmt(start_minutes),
        "services": list(services),
    }
    if trip_date:
        result["trip_date"] = trip_date
    return result
