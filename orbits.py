"""Satellite visibility: low-orbit pass windows (Starlink, Globalstar) and geostationary look angles (Skylo).

Orbit data (TLEs) comes from CelesTrak and is cached in data/tle/. The app only reads
the cache; refresh it with `python tools/fetch_tles.py` (CelesTrak asks for at most
one download per group every couple of hours).
"""
import math
import os
from datetime import datetime, timedelta, timezone

import numpy as np
from sgp4.api import SatrecArray, Satrec
from skyfield.api import load

from terrain import horizon_at

TLE_DIR = os.path.join(os.path.dirname(__file__), "data", "tle")
CELESTRAK = "https://celestrak.org/NORAD/elements/gp.php?GROUP={group}&FORMAT=tle"
STEP_S = 30
MIN_WINDOW_S = 120  # shorter gaps in the sky aren't worth planning a check-in around
MERGE_GAP_S = 180   # a dropout this short between passes still reads as one window to a hiker

# Per service: TLE group, which satellites count, and the lowest usable elevation.
# Min elevations are estimates for a phone in hand, not published specs.
LEO = {
    "starlink": {"group": "starlink", "only": "[DTC]", "min_el": 25.0},  # direct-to-cell sats only
    "globalstar": {"group": "globalstar", "only": None, "min_el": 20.0},
}

# Skylo rides geostationary L-band satellites. Which one serves a given phone isn't
# published; we assume one over the Americas near 98 W. Estimate.
SKYLO_SAT_LON = -98.0

WGS84_A = 6378.137
WGS84_F = 1 / 298.257223563
GEO_RADIUS_KM = 42164.0

_ts = load.timescale(builtin=True)
_cache = {}


def tle_path(group):
    return os.path.join(TLE_DIR, f"{group}.tle")


def _satellites(service):
    if service not in _cache:
        cfg = LEO[service]
        lines = [ln.rstrip() for ln in open(tle_path(cfg["group"]), encoding="utf-8") if ln.strip()]
        sats, epochs = [], []
        for name, l1, l2 in zip(lines[0::3], lines[1::3], lines[2::3]):
            if cfg["only"] and cfg["only"] not in name:
                continue
            s = Satrec.twoline2rv(l1, l2)
            sats.append(s)
            epochs.append(s.jdsatepoch + s.jdsatepochF)
        _cache[service] = (SatrecArray(sats), max(epochs))
    return _cache[service]


def tle_age_days(service, when_utc):
    _, newest = _satellites(service)
    jd = when_utc.timestamp() / 86400 + 2440587.5
    return jd - newest


def _observer_ecef(lat, lon, elev_m):
    phi, lam = math.radians(lat), math.radians(lon)
    e2 = WGS84_F * (2 - WGS84_F)
    n = WGS84_A / math.sqrt(1 - e2 * math.sin(phi) ** 2)
    h = elev_m / 1000
    return np.array([(n + h) * math.cos(phi) * math.cos(lam),
                     (n + h) * math.cos(phi) * math.sin(lam),
                     (n * (1 - e2) + h) * math.sin(phi)])


def _look_angles(ecef, lat, lon, elev_m):
    """Azimuth/elevation in degrees of ECEF positions (..., 3) seen from the observer."""
    phi, lam = math.radians(lat), math.radians(lon)
    rho = ecef - _observer_ecef(lat, lon, elev_m)
    x, y, z = rho[..., 0], rho[..., 1], rho[..., 2]
    e = -math.sin(lam) * x + math.cos(lam) * y
    n = -math.sin(phi) * math.cos(lam) * x - math.sin(phi) * math.sin(lam) * y + math.cos(phi) * z
    u = math.cos(phi) * math.cos(lam) * x + math.cos(phi) * math.sin(lam) * y + math.sin(phi) * z
    return np.degrees(np.arctan2(e, n)) % 360, np.degrees(np.arctan2(u, np.hypot(e, n)))


def geo_look_angle(lat, lon, sat_lon):
    """(azimuth, elevation) in degrees of a geostationary satellite at sat_lon."""
    lam = math.radians(sat_lon)
    sat = np.array([GEO_RADIUS_KM * math.cos(lam), GEO_RADIUS_KM * math.sin(lam), 0.0])
    az, el = _look_angles(sat, lat, lon, 0)
    return float(az), float(el)


def pass_windows(lat, lon, elev_m, horizon, start_utc, end_utc, service):
    """[(start, end), ...] UTC datetimes when at least one usable satellite clears the local horizon."""
    sats, _ = _satellites(service)
    min_el = LEO[service]["min_el"]
    secs = np.arange(0, (end_utc - start_utc).total_seconds() + 1, STEP_S)
    jd_all = start_utc.timestamp() / 86400 + 2440587.5 + secs / 86400
    jd, fr = np.floor(jd_all), jd_all - np.floor(jd_all)

    err, r, _ = sats.sgp4(jd, fr)  # TEME km, shape (sats, times, 3)
    theta = np.radians(_ts.ut1_jd(jd_all).gmst * 15.0)  # TEME -> Earth-fixed rotation
    c, s = np.cos(theta), np.sin(theta)
    ecef = np.stack([c * r[..., 0] + s * r[..., 1], -s * r[..., 0] + c * r[..., 1], r[..., 2]], axis=-1)

    az, el = _look_angles(ecef, lat, lon, elev_m)
    visible = ((el >= np.maximum(min_el, horizon_at(horizon, az))) & (err == 0)).any(axis=0)

    runs, run_start = [], None
    for i, v in enumerate(np.append(visible, False)):
        if v and run_start is None:
            run_start = i
        elif not v and run_start is not None:
            if runs and (run_start - runs[-1][1]) * STEP_S <= MERGE_GAP_S:
                runs[-1] = (runs[-1][0], i - 1)
            else:
                runs.append((run_start, i - 1))
            run_start = None
    return [(start_utc + timedelta(seconds=float(secs[a])), start_utc + timedelta(seconds=float(secs[b])))
            for a, b in runs if (b - a + 1) * STEP_S >= MIN_WINDOW_S]


def utc(dt):
    return dt.astimezone(timezone.utc)


def now_utc():
    return datetime.now(timezone.utc)
