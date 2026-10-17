"""Hardcoded trail, user profiles, and satellite services."""

CATALOG_AS_OF = "2026-10-17"


def _pt(lat, lon, elev_m, canopy, south_blocked=False):
    return {"lat": lat, "lon": lon, "elev_m": elev_m, "canopy": canopy, "south_blocked": south_blocked}


TRAIL = {
    "id": "colchuck",
    "name": "Colchuck Lake",
    "start_time": "9:00am",
    # Places with regular cell signal (used when no satellite option helps).
    "cell_spots": ["Stuart Lake Trailhead", "Colchuck Lake shore"],
    # Approximate route, trailhead -> lake. TODO(A): replace with real GPX, SRTM elevation, USFS canopy.
    # canopy: 0 = open sky, 1 = dense forest. south_blocked: a ridge hides the southern sky.
    "points": [
        _pt(47.5280, -120.8210, 1036, 0.30),
        _pt(47.5262, -120.8222, 1070, 0.80),
        _pt(47.5241, -120.8238, 1110, 0.85),
        _pt(47.5222, -120.8250, 1150, 0.55),  # forest junction
        _pt(47.5200, -120.8262, 1200, 0.75),
        _pt(47.5180, -120.8275, 1260, 0.70),
        _pt(47.5160, -120.8283, 1320, 0.18, south_blocked=True),
        _pt(47.5138, -120.8292, 1380, 0.15, south_blocked=True),  # ridge viewpoint
        _pt(47.5115, -120.8300, 1430, 0.12, south_blocked=True),
        _pt(47.5092, -120.8311, 1480, 0.65),
        _pt(47.5070, -120.8320, 1530, 0.35),  # boulder field
        _pt(47.5048, -120.8326, 1580, 0.80),
        _pt(47.5025, -120.8332, 1630, 0.85),
        _pt(47.5000, -120.8337, 1670, 0.40),
        _pt(47.4970, -120.8340, 1690, 0.10),
    ],
}

PROFILES = {
    "verizon_pixel": {
        "name": "Verizon Pixel 9", "carrier": "Verizon", "phone": "Pixel 9",
        "services": ["skylo"], "tsat_compatible": True,
        "plan": "Unlimited Plus", "monthly_cost": 90, "household_lines": 3,
    },
    "tmobile_galaxy": {
        "name": "T-Mobile Galaxy S25", "carrier": "T-Mobile", "phone": "Galaxy S25",
        "services": ["starlink"], "tsat_compatible": True,
        "plan": "Experience Beyond (T-Satellite included)", "monthly_cost": 100, "household_lines": 2,
    },
    "att_iphone15": {
        "name": "AT&T iPhone 15", "carrier": "AT&T", "phone": "iPhone 15",
        "services": ["globalstar"], "tsat_compatible": True,
        "plan": "Unlimited Starter", "monthly_cost": 65, "household_lines": 1,
    },
    "att_iphone13": {
        "name": "AT&T iPhone 13", "carrier": "AT&T", "phone": "iPhone 13",
        "services": [], "tsat_compatible": False,
        "plan": "Unlimited Starter", "monthly_cost": 65, "household_lines": 1,
    },
}

SERVICES = {
    "starlink": {"name": "T-Mobile T-Satellite", "constellation": "Starlink",
                 "cost": "$10/mo add-on", "blocked_by_south_ridge": False},
    "globalstar": {"name": "Apple Messages via Satellite", "constellation": "Globalstar",
                   "cost": "Free", "blocked_by_south_ridge": False},
    "skylo": {"name": "Google/Verizon satellite", "constellation": "Skylo",
              "cost": "Free", "blocked_by_south_ridge": True},
}
