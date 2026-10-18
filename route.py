"""Trail routes: GPX parsing, resampling, and loading the prebuilt trail JSON."""
import json
import math
import os
import xml.etree.ElementTree as ET

TRAILS_DIR = os.path.join(os.path.dirname(__file__), "data", "trails")
EARTH_R = 6371000.0
GPX_NS = {"g": "http://www.topografix.com/GPX/1/1"}


def haversine_m(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(h))


def parse_gpx(path):
    """Return [(lat, lon), ...] from the first track (or route) in a GPX file."""
    root = ET.parse(path).getroot()
    pts = root.findall(".//g:trkpt", GPX_NS) or root.findall(".//g:rtept", GPX_NS)
    return [(float(p.get("lat")), float(p.get("lon"))) for p in pts]


def write_gpx(path, name, points, note=""):
    gpx = ET.Element("gpx", version="1.1", creator="Starward", xmlns=GPX_NS["g"])
    meta = ET.SubElement(gpx, "metadata")
    ET.SubElement(meta, "name").text = name
    if note:
        ET.SubElement(meta, "desc").text = note
    seg = ET.SubElement(ET.SubElement(gpx, "trk"), "trkseg")
    for lat, lon in points:
        ET.SubElement(seg, "trkpt", lat=f"{lat:.6f}", lon=f"{lon:.6f}")
    ET.indent(gpx)
    ET.ElementTree(gpx).write(path, encoding="utf-8", xml_declaration=True)


def resample(points, step_m):
    """Evenly spaced points every step_m along the line, always keeping both ends."""
    out = [points[0]]
    carry = 0.0
    for a, b in zip(points, points[1:]):
        seg = haversine_m(a, b)
        pos = step_m - carry
        while pos <= seg:
            f = pos / seg
            out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
            pos += step_m
        carry = (carry + seg) % step_m
    if haversine_m(out[-1], points[-1]) > step_m * 0.3:
        out.append(points[-1])
    return out


def load_trail(trail_id):
    """Load data/trails/<id>.json, built by tools/build_trail.py."""
    with open(os.path.join(TRAILS_DIR, f"{trail_id}.json"), encoding="utf-8") as f:
        return json.load(f)


def load_all_trails():
    """{id: trail} for every built trail, sorted by name."""
    ids = [f[:-5] for f in os.listdir(TRAILS_DIR) if f.endswith(".json")]
    trails = [load_trail(i) for i in ids]
    return {t["id"]: t for t in sorted(trails, key=lambda t: t["name"])}
