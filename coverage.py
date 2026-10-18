# TODO(A): replace hand-estimated canopy with USFS Tree Canopy Cover
"""Coverage along the trail: terrain horizons + canopy for every point, real satellite
pass windows at each check-in when a trip date is given."""
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from orbits import LEO, pass_windows, tle_age_days
from route import haversine_m

GREEN_MIN = 0.6
YELLOW_MIN = 0.3
TZ = ZoneInfo("America/Los_Angeles")
WALK_KMH = 4.0          # hiking pace on flat ground (Naismith-style, with breaks)
CLIMB_M_PER_H = 600     # plus one hour per 600 m of climbing
WINDOW_BEFORE_MIN = 30  # satellite windows shown around each expected check-in time
WINDOW_AFTER_MIN = 60
MAX_TLE_AGE_DAYS = 7    # older orbit data drifts too much to trust exact minutes
GEO_ANYTIME = "Any time (fixed satellite)"
START_MINUTES = 9 * 60  # 9:00am default


def _fmt(dt):
    return dt.strftime("%I:%M%p").lstrip("0").lower()


def parse_start_time(start_time, default=START_MINUTES):
    """Minutes since midnight from '9:00am', '9:00 AM', '09:00', '14:30', '9am'. Bad input -> default."""
    if start_time is None or start_time == "":
        return default
    if isinstance(start_time, int):
        return start_time
    text = str(start_time).strip().lower().replace(" ", "")
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?([ap])m?", text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        if 1 <= h <= 12 and mi < 60:
            return (h % 12 + (12 if m.group(3) == "p" else 0)) * 60 + mi
        return default
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", text)  # HTML <input type=time>
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        return int(m.group(1)) * 60 + int(m.group(2))
    return default


_parse_start_minutes = parse_start_time  # older name used by tests


def start_time_for_input(start_time, default="09:00"):
    """Normalize any start time to HH:MM for <input type=time>."""
    h, m = divmod(parse_start_time(start_time, parse_start_time(default)), 60)
    return f"{h:02d}:{m:02d}"


def trip_month_label(trip_date, fallback="this trip"):
    """Month name from an ISO date, for recommendation copy."""
    if not trip_date:
        return fallback
    try:
        return datetime.strptime(str(trip_date), "%Y-%m-%d").strftime("%B")
    except ValueError:
        return fallback


def _color(openness):
    if openness >= GREEN_MIN:
        return "green"
    if openness >= YELLOW_MIN:
        return "yellow"
    return "red"


def _openness(point, services):
    """Best sky openness across the services, 0..1."""
    best = 0.0
    for s in services:
        if s in LEO:
            best = max(best, 1 - point["canopy"])
        elif s == "skylo":  # geostationary: one fixed direction, low in the southern sky
            best = max(best, 0.1 if point["south_blocked"] else 1 - point["canopy"])
    return round(best, 2)


def _with_defaults(points):
    """Fill fields older or hand-made trails may lack: distance along the route, elevation, horizon."""
    if all("dist_m" in p and "elev_m" in p and "horizon" in p for p in points):
        return points
    out, dist = [], 0.0
    for i, p in enumerate(points):
        if i:
            dist += haversine_m((points[i - 1]["lat"], points[i - 1]["lon"]), (p["lat"], p["lon"]))
        out.append({"dist_m": dist, "elev_m": 0, "horizon": [0.0] * 72, "canopy": 0.5, "south_blocked": False, **p})
    return out


def _minutes_from_start(points, idx):
    climb = sum(max(0, b["elev_m"] - a["elev_m"]) for a, b in zip(points[:idx], points[1:idx + 1]))
    hours = points[idx]["dist_m"] / 1000 / WALK_KMH + climb / CLIMB_M_PER_H
    return int(round(hours * 60 / 5) * 5)


def _fake_windows(color, eta):
    if color == "green":
        return [f"{_fmt(eta - timedelta(minutes=10))}–{_fmt(eta + timedelta(minutes=5))}",
                f"{_fmt(eta + timedelta(minutes=15))}–{_fmt(eta + timedelta(minutes=30))}"]
    if color == "yellow":
        return [f"{_fmt(eta - timedelta(minutes=5))}–{_fmt(eta + timedelta(minutes=2))}"]
    return []


def _real_windows(point, services, eta):
    """Best service's windows around eta, as display strings."""
    lo, hi = eta - timedelta(minutes=WINDOW_BEFORE_MIN), eta + timedelta(minutes=WINDOW_AFTER_MIN)
    best, best_minutes = [], 0
    for s in services:
        if s == "skylo":
            if not point["south_blocked"]:
                return [GEO_ANYTIME]
            continue
        if s not in LEO:
            continue
        wins = pass_windows(point["lat"], point["lon"], point["elev_m"], point["horizon"],
                            lo.astimezone(timezone.utc), hi.astimezone(timezone.utc), s)
        minutes = sum((b - a).total_seconds() for a, b in wins) / 60
        if minutes > best_minutes:
            best_minutes = minutes
            best = [f"{_fmt(a.astimezone(TZ))}–{_fmt(b.astimezone(TZ))}" for a, b in wins]
    return best


def get_coverage(trail, profile, services=None, trip_date=None, start_time=None):
    """trip_date: 'YYYY-MM-DD' or date; start_time: '9:00am' or '09:00'. Without a date, windows are placeholders."""
    if services is None:
        services = profile["services"]
    services = [s for s in services if s in LEO or s == "skylo"]
    points = _with_defaults(trail["points"])
    if trip_date is None:
        trip_date = trail.get("trip_date")
    if isinstance(trip_date, str):
        try:
            trip_date = date.fromisoformat(trip_date) if trip_date else None
        except ValueError:
            trip_date = None
    start_minutes = parse_start_time(start_time or trail.get("start_time"))
    start = datetime.combine(trip_date or date.today(), time(*divmod(start_minutes, 60)), TZ)

    segments = []
    for p in points:
        openness = _openness(p, services)
        segments.append({"lat": p["lat"], "lon": p["lon"], "openness": openness, "color": _color(openness)})

    spots = trail.get("checkins") or [{"name": f"Spot {i + 1}", "idx": round((len(points) - 1) * f)}
                                      for i, f in enumerate((0.25, 0.5, 0.75))]
    checkins = []
    for i, spot in enumerate(spots):
        idx = spot["idx"]
        seg = segments[idx]
        eta = start + timedelta(minutes=_minutes_from_start(points, idx))
        if trip_date:
            windows = _real_windows(points[idx], services, eta) if seg["color"] != "red" else []
            covered = seg["color"] != "red" and bool(windows)
        else:
            windows = _fake_windows(seg["color"], eta)
            covered = seg["color"] != "red"
        checkins.append({
            "idx": idx,
            "name": f"Check-in {i + 1}: {spot['name']}",
            "lat": seg["lat"],
            "lon": seg["lon"],
            "time": _fmt(eta),
            "windows": windows,
            "color": seg["color"],
            "covered": covered,
        })

    confidence, note = "medium", "terrain + estimated canopy; pick a date for satellite timing"
    leo = [s for s in services if s in LEO]
    if trip_date and leo:
        age = tle_age_days(leo[0], start.astimezone(timezone.utc))
        if abs(age) <= MAX_TLE_AGE_DAYS:
            confidence, note = "medium-high", "terrain + live orbit data; canopy estimated"
        else:
            note = f"orbit data is {abs(age):.0f} days from the trip date; refresh closer to the trip"
    elif trip_date:
        note = "terrain + estimated canopy"

    return {
        "segments": segments,
        "checkins": checkins,
        "confidence": confidence,
        "confidence_note": note,
        "start_time": _fmt(start),
        "trip_date": trip_date.isoformat() if trip_date else None,
        "orbit_based": bool(trip_date),
        "services": services,
    }
