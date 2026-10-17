# TODO(A): replace with SRTM horizon masks + USFS canopy + skyfield passes
"""Fake sky-openness coverage along the trail, built from per-point canopy and ridge data."""
from data import SERVICES

GREEN_MIN = 0.6
YELLOW_MIN = 0.3
CHECKIN_NAMES = ["Forest junction", "Ridge viewpoint", "Boulder field"]
START_MINUTES = 9 * 60  # 9:00am
CHECKIN_GAP_MINUTES = 90


def _fmt(minutes):
    h, m = divmod(minutes, 60)
    suffix = "am" if h < 12 else "pm"
    return f"{(h - 1) % 12 + 1}:{m:02d}{suffix}"


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


def get_coverage(trail, profile, services=None):
    if services is None:
        services = profile["services"]
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
        t = START_MINUTES + CHECKIN_GAP_MINUTES * (i + 1)
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

    return {
        "segments": segments,
        "checkins": checkins,
        "confidence": "medium",
        "confidence_note": "terrain + canopy data only",
        "start_time": _fmt(START_MINUTES),
        "services": list(services),
    }
