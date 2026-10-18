"""Build data/trails/<id>.json: real route, elevation, horizon masks, canopy estimates.

Run once per trail (needs internet; all sources are free and keyless):
    python tools/build_trail.py            # every trail in TRAILS
    python tools/build_trail.py mount_si   # just one
Re-running reuses the cached GPX and elevation grid in data/trails/.
"""
import heapq
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from orbits import geo_look_angle, SKYLO_SAT_LON  # noqa: E402
from route import TRAILS_DIR, haversine_m, parse_gpx, resample, write_gpx  # noqa: E402
from terrain import CLEARANCE_DEG, DemGrid, horizon_at, horizon_mask  # noqa: E402

OVERPASS = "https://overpass-api.de/api/interpreter"
STEP_M = 100
DEM_STEP_M = 300
PICK_RADIUS = 4  # check-ins move up to this many points (~400 m) toward a more open spot
SNAP_M = 25      # join trail pieces whose ends are this close

# Per trail: OSM trail names, search box (S, W, N, E), where the hike starts and ends,
# canopy estimates by km from the trailhead, and 2-3 check-ins (fraction of the route or a
# (lat, lon) landmark). Canopy is 0 = open sky, 1 = dense forest: hand estimates for the demo.
# TODO(A): replace canopy with USFS Tree Canopy Cover samples.
TRAILS = {
    "colchuck": {
        "name": "Colchuck Lake", "start_time": "9:00am",
        "osm_names": "Stuart Lake Trail|Colchuck Lake Trail", "bbox": (47.485, -120.850, 47.540, -120.800),
        "trailhead": (47.5278, -120.8208), "goal": (47.4975, -120.8337),  # Colchuck Lake's north shore
        "dem_margin": (0.055, 0.08),
        "cell_spots": ["Stuart Lake Trailhead", "Colchuck Lake shore"],
        "canopy": [(0.3, 0.45), (1.3, 0.75), (1.6, 0.35), (3.2, 0.75), (3.8, 0.40), (4.8, 0.60), (5.4, 0.30),
                   (99, 0.15)],
        "checkins": [("Mountaineer Creek", 0.25), ("Colchuck Lake junction", (47.5051, -120.8404)),
                     ("Upper switchbacks", 0.8)],
    },
    "mount_si": {
        "name": "Mount Si", "start_time": "9:00am",
        "osm_names": "Mount Si Trail", "bbox": (47.475, -121.760, 47.520, -121.700),
        "trailhead": (47.4882, -121.7231), "goal": (47.5068, -121.7380),  # Haystack Basin, below the summit block
        "dem_margin": (0.045, 0.065),
        "cell_spots": ["Mount Si Trailhead", "Haystack Basin (summit area)"],
        "canopy": [(0.2, 0.45), (2.6, 0.80), (3.2, 0.50), (5.6, 0.75), (99, 0.15)],
        # Forest between Snag Flats and Haystack Basin is too dense for a check-in, so only two.
        "checkins": [("Snag Flats", 0.47), ("Haystack Basin", 0.98)],
    },
    "lake_serene": {
        "name": "Lake Serene", "start_time": "9:00am",
        "osm_names": "Lake Serene Trail", "bbox": (47.770, -121.600, 47.820, -121.550),
        "trailhead": (47.8073, -121.5736), "goal": (47.78515, -121.57083),  # end of trail at the lake outlet
        "dem_margin": (0.045, 0.065),
        "cell_spots": ["Lake Serene Trailhead"],
        "canopy": [(2.3, 0.50), (2.7, 0.45), (4.3, 0.75), (99, 0.20)],
        # The forested switchbacks are too dense for a check-in, so only two.
        "checkins": [("Bridal Veil Falls junction", (47.7929, -121.5706)), ("Lake Serene", 0.98)],
    },
    "snow_lake": {
        "name": "Snow Lake", "start_time": "9:00am",
        "osm_names": "Snow Lake Trail", "bbox": (47.440, -121.470, 47.475, -121.410),
        "trailhead": (47.4454, -121.4235), "goal": (47.4638, -121.4455),  # Snow Lake shore, before Gem Lake
        "dem_margin": (0.045, 0.065),
        "cell_spots": ["Alpental parking lot"],
        "canopy": [(1.2, 0.60), (2.4, 0.25), (2.9, 0.15), (4.2, 0.50), (99, 0.30)],
        "checkins": [("Source Lake overlook junction", 0.4), ("Snow Lake saddle", (47.4581, -121.4479)),
                     ("Snow Lake shore", 0.97)],
    },
    "mailbox_peak": {
        "name": "Mailbox Peak", "start_time": "8:00am",
        # The new trail only ("Mailbox Peak Old Trail" is a separate, much steeper route).
        "osm_names": "Mailbox Peak Trail", "bbox": (47.455, -121.700, 47.500, -121.620),
        "trailhead": (47.4660, -121.6726), "goal": (47.4624, -121.6393),  # summit (the mailbox)
        "dem_margin": (0.045, 0.065),
        "cell_spots": ["Mailbox Peak Trailhead", "Mailbox Peak summit"],
        "canopy": [(0.2, 0.45), (6.2, 0.80), (7.0, 0.35), (99, 0.10)],
        "checkins": [("Lower switchbacks", 0.3), ("Upper forest", 0.65), ("Boulder field below the summit", 0.92)],
    },
}


def fetch_osm_route(cfg):
    s, w, n, e = cfg["bbox"]
    query = (f'[out:json][timeout:50];way["highway"~"path|footway|steps|track"]["name"~"^({cfg["osm_names"]})$"]'
             f"({s},{w},{n},{e});out geom;")
    req = urllib.request.Request(OVERPASS, data=urllib.parse.urlencode({"data": query}).encode(),
                                 headers={"User-Agent": "Starward-hackathon/0.1"})
    for attempt in range(4):  # Overpass is a shared free server and sometimes returns 502/504
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                ways = json.load(r)["elements"]
            break
        except urllib.error.HTTPError as e:
            if attempt == 3:
                raise
            print(f"[build] Overpass error {e.code}, retrying in {10 * (attempt + 1)}s")
            time.sleep(10 * (attempt + 1))

    # Graph of every node in the named trail ways, then shortest path trailhead -> goal.
    graph, ends = {}, set()
    for w in ways:
        pts = [(round(g["lat"], 7), round(g["lon"], 7)) for g in w["geometry"]]
        ends.update((pts[0], pts[-1]))
        for a, b in zip(pts, pts[1:]):
            d = haversine_m(a, b)
            graph.setdefault(a, []).append((b, d))
            graph.setdefault(b, []).append((a, d))
    # OSM pieces sometimes end a few meters apart instead of sharing a node; bridge small gaps.
    for a in ends:
        for b in graph:
            d = haversine_m(a, b)
            if 0 < d <= SNAP_M:
                graph[a].append((b, d))
                graph[b].append((a, d))
    start = min(graph, key=lambda n: haversine_m(n, cfg["trailhead"]))
    goal = min(graph, key=lambda n: haversine_m(n, cfg["goal"]))
    dist, prev, heap = {start: 0.0}, {}, [(0.0, start)]
    while heap:
        d, n = heapq.heappop(heap)
        if n == goal:
            break
        if d > dist[n]:
            continue
        for m, w in graph[n]:
            if d + w < dist.get(m, float("inf")):
                dist[m], prev[m] = d + w, n
                heapq.heappush(heap, (d + w, m))
    if goal not in dist:
        raise SystemExit(f"[build] no connected route from trailhead to goal for {cfg['name']}")
    path = [goal]
    while path[-1] != start:
        path.append(prev[path[-1]])
    return path[::-1]


def build(trail_id):
    cfg = TRAILS[trail_id]
    gpx_path = os.path.join(TRAILS_DIR, f"{trail_id}.gpx")
    dem_path = os.path.join(TRAILS_DIR, f"{trail_id}_dem.npz")
    os.makedirs(TRAILS_DIR, exist_ok=True)

    if not os.path.exists(gpx_path):
        print(f"[build] {trail_id}: fetching route from OpenStreetMap")
        write_gpx(gpx_path, cfg["name"], fetch_osm_route(cfg),
                  note=f"Route data (c) OpenStreetMap contributors, ODbL. {cfg['osm_names']}.")
    raw = parse_gpx(gpx_path)
    total_m = sum(haversine_m(a, b) for a, b in zip(raw, raw[1:]))
    points = resample(raw, STEP_M)

    if os.path.exists(dem_path):
        dem = DemGrid.load(dem_path)
    else:
        lats, lons = [p[0] for p in points], [p[1] for p in points]
        my, mx = cfg["dem_margin"]
        dem = DemGrid.fetch(min(lats) - my, min(lons) - mx, max(lats) + my, max(lons) + mx, DEM_STEP_M)
        dem.save(dem_path)

    skylo_az, skylo_el = geo_look_angle(points[0][0], points[0][1], SKYLO_SAT_LON)
    out_points = []
    for i, (lat, lon) in enumerate(points):
        dist = min(i * STEP_M, total_m)  # along the trail, not straight-line between samples
        mask = horizon_mask(dem, lat, lon)
        out_points.append({
            "lat": round(lat, 6), "lon": round(lon, 6),
            "dist_m": round(dist), "elev_m": round(float(dem.sample(lat, lon))),
            "canopy": next(c for end, c in cfg["canopy"] if dist / 1000 <= end),
            "south_blocked": bool(horizon_at(mask, skylo_az) + CLEARANCE_DEG >= skylo_el),
            "horizon": mask,
        })

    n = len(out_points)

    def most_open_near(target):
        lo, hi = max(0, target - PICK_RADIUS), min(n - 1, target + PICK_RADIUS)
        return min(range(lo, hi + 1), key=lambda i: (out_points[i]["canopy"], abs(i - target)))

    def spot_idx(where):
        if isinstance(where, tuple):
            target = min(range(n), key=lambda i: haversine_m((out_points[i]["lat"], out_points[i]["lon"]), where))
        else:
            target = round((n - 1) * where)
        return most_open_near(target)

    trail = {
        "id": trail_id,
        "name": cfg["name"],
        "start_time": cfg["start_time"],
        "cell_spots": cfg["cell_spots"],
        "sources": {
            "route": "OpenStreetMap contributors (ODbL)",
            "elevation": "Copernicus DEM via Open-Meteo",
            "canopy": "hand estimate (replace with USFS Tree Canopy Cover)",
        },
        "checkins": [{"name": name, "idx": spot_idx(where)} for name, where in cfg["checkins"]],
        "points": out_points,
    }
    with open(os.path.join(TRAILS_DIR, f"{trail_id}.json"), "w", encoding="utf-8") as f:
        json.dump(trail, f, separators=(",", ":"))
    blocked = sum(p["south_blocked"] for p in out_points)
    print(f"[build] {trail_id}: {n} points, {total_m / 1000:.2f} km, {out_points[0]['elev_m']} -> "
          f"{out_points[-1]['elev_m']} m, Skylo sat az {skylo_az:.0f} el {skylo_el:.0f}, "
          f"{blocked} points south-blocked, check-ins at {[c['idx'] for c in trail['checkins']]}")


def main():
    for trail_id in sys.argv[1:] or TRAILS:
        build(trail_id)


if __name__ == "__main__":
    main()
