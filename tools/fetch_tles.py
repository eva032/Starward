"""Refresh cached orbit data from CelesTrak (free, no key). Run before planning a trip:
    python tools/fetch_tles.py
Skips groups downloaded in the last 2 hours, as CelesTrak asks.
"""
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from orbits import CELESTRAK, LEO, TLE_DIR, tle_path  # noqa: E402

MIN_AGE_S = 2 * 3600


def main():
    os.makedirs(TLE_DIR, exist_ok=True)
    for group in sorted({cfg["group"] for cfg in LEO.values()}):
        path = tle_path(group)
        if os.path.exists(path) and time.time() - os.path.getmtime(path) < MIN_AGE_S:
            print(f"[tle] {group}: fresh enough, skipping")
            continue
        req = urllib.request.Request(CELESTRAK.format(group=group), headers={"User-Agent": "Starward-hackathon/0.1"})
        with urllib.request.urlopen(req, timeout=60) as r:
            text = r.read().decode()
        if not text.startswith(("STARLINK", "GLOBALSTAR")) and "\n1 " not in text:
            print(f"[tle] {group}: unexpected response, keeping the old file")
            continue
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"[tle] {group}: {text.count(chr(10) + '1 ')} satellites saved")


if __name__ == "__main__":
    main()
