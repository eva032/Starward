"""Terrain: elevation grid and per-point horizon masks.

The heavy part (fetching the elevation grid and computing horizons) runs once in
tools/build_trail.py. At runtime the app only reads the precomputed masks.
"""
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request

import numpy as np

AZ_STEP = 5  # degrees between horizon samples; masks have 360 / AZ_STEP entries
EARTH_R = 6371000.0
REFRACTION_K = 0.13
OBSERVER_HEIGHT_M = 1.5
# A satellite must clear the terrain by this much: signals grazing a ridge are unreliable,
# and the 300 m elevation grid smooths ridgelines a little.
CLEARANCE_DEG = 5.0
ELEVATION_API = "https://api.open-meteo.com/v1/elevation"  # Copernicus DEM, free, no key


def fetch_elevations(coords, batch=100, pause_s=1.0):
    """Elevations (m) for [(lat, lon), ...] from Open-Meteo, 100 per request.

    Free tier counts each point toward the daily limit, so keep grids small.
    """
    out = []
    for i in range(0, len(coords), batch):
        chunk = coords[i:i + batch]
        q = urllib.parse.urlencode({
            "latitude": ",".join(f"{lat:.5f}" for lat, _ in chunk),
            "longitude": ",".join(f"{lon:.5f}" for _, lon in chunk),
        })
        req = urllib.request.Request(f"{ELEVATION_API}?{q}", headers={"User-Agent": "Starward-hackathon/0.1"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    out.extend(json.load(r)["elevation"])
                break
            except urllib.error.HTTPError as e:
                if e.code != 429 or attempt == 3:
                    raise
                print("[terrain] rate limited, waiting 65s")
                time.sleep(65)
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt == 3:
                    raise
                print(f"[terrain] network error ({e}), retrying in 20s")
                time.sleep(20)
        time.sleep(pause_s)
    return out


class DemGrid:
    """Regular lat/lon elevation grid with bilinear lookup."""

    def __init__(self, lats, lons, elev):
        self.lats, self.lons, self.elev = np.asarray(lats), np.asarray(lons), np.asarray(elev, dtype=float)

    @classmethod
    def fetch(cls, south, west, north, east, step_m):
        dlat = step_m / 111320.0
        dlon = step_m / (111320.0 * math.cos(math.radians((south + north) / 2)))
        lats = np.arange(south, north + dlat / 2, dlat)
        lons = np.arange(west, east + dlon / 2, dlon)
        coords = [(lat, lon) for lat in lats for lon in lons]
        print(f"[terrain] fetching {len(coords)} elevations ({math.ceil(len(coords) / 100)} requests)")
        elev = np.array(fetch_elevations(coords)).reshape(len(lats), len(lons))
        return cls(lats, lons, elev)

    @classmethod
    def load(cls, path):
        d = np.load(path)
        return cls(d["lats"], d["lons"], d["elev"])

    def save(self, path):
        np.savez_compressed(path, lats=self.lats, lons=self.lons, elev=self.elev)

    def sample(self, lat, lon):
        lat, lon = np.asarray(lat, dtype=float), np.asarray(lon, dtype=float)
        fy = np.clip((lat - self.lats[0]) / (self.lats[1] - self.lats[0]), 0, len(self.lats) - 1.001)
        fx = np.clip((lon - self.lons[0]) / (self.lons[1] - self.lons[0]), 0, len(self.lons) - 1.001)
        y0, x0 = fy.astype(int), fx.astype(int)
        ty, tx = fy - y0, fx - x0
        e = self.elev
        top = e[y0, x0] * (1 - tx) + e[y0, x0 + 1] * tx
        bot = e[y0 + 1, x0] * (1 - tx) + e[y0 + 1, x0 + 1] * tx
        return top * (1 - ty) + bot * ty


def horizon_mask(dem, lat, lon, max_dist_m=6000, step_m=60):
    """Horizon elevation angle (degrees, >= 0) for each azimuth 0, 5, ..., 355."""
    h0 = float(dem.sample(lat, lon)) + OBSERVER_HEIGHT_M
    az = np.radians(np.arange(0, 360, AZ_STEP))[:, None]
    d = np.arange(step_m, max_dist_m + 1, step_m)[None, :]
    dlat = np.degrees(d * np.cos(az) / EARTH_R)
    dlon = np.degrees(d * np.sin(az) / (EARTH_R * math.cos(math.radians(lat))))
    h = dem.sample(lat + dlat, lon + dlon)
    drop = d ** 2 / (2 * EARTH_R) * (1 - REFRACTION_K)
    angles = np.degrees(np.arctan2(h - drop - h0, d))
    return np.maximum(angles.max(axis=1), 0).round(1).tolist()


def horizon_at(mask, az_deg):
    """Horizon angle for any azimuth, interpolated between mask samples (works on arrays)."""
    mask = np.asarray(mask)
    f = np.nan_to_num(np.asarray(az_deg, dtype=float) % 360) / AZ_STEP  # NaN = failed orbit propagation
    i0 = f.astype(int) % len(mask)
    i1 = (i0 + 1) % len(mask)
    t = f - np.floor(f)
    return mask[i0] * (1 - t) + mask[i1] * t
