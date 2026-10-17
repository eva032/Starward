"""Trail, profile, and satellite-service catalogs.

Loads JSON when present (`trails/*.json`, `carriers.json`); falls back to the
hardcoded catalogs below so the demo still runs if files are missing.
"""
from __future__ import annotations

import json
from pathlib import Path

from data.compat import (  # re-export for app/tests
    CARRIERS as COMPAT_CARRIERS,
    MANUFACTURERS,
    PHONES,
    PHONES_BY_ID,
    activation_label,
    build_recommendation,
    needs_activation_question,
    phone_by_id,
    phones_for_manufacturer,
    resolve_phone_id,
    resolve_setup,
    should_use_recommend_engine,
    tsat_addon_verified,
    unknown_recommendation,
)

_DIR = Path(__file__).resolve().parent
_TRAILS_DIR = _DIR / "trails"
_CARRIERS_PATH = _DIR / "carriers.json"

CATALOG_AS_OF = "2026-10-17"


def _pt(lat, lon, elev_m, canopy, south_blocked=False):
    return {"lat": lat, "lon": lon, "elev_m": elev_m, "canopy": canopy, "south_blocked": south_blocked}


# Fallback catalogs (same content as the JSON files). TODO(A)/(B): replace fakes.
_FALLBACK_TRAIL = {
    "id": "colchuck",
    "name": "Colchuck Lake",
    "start_time": "9:00am",
    "cell_spots": ["Stuart Lake Trailhead", "Colchuck Lake shore"],
    "points": [
        _pt(47.5280, -120.8210, 1036, 0.30),
        _pt(47.5262, -120.8222, 1070, 0.80),
        _pt(47.5241, -120.8238, 1110, 0.85),
        _pt(47.5222, -120.8250, 1150, 0.55),
        _pt(47.5200, -120.8262, 1200, 0.75),
        _pt(47.5180, -120.8275, 1260, 0.70),
        _pt(47.5160, -120.8283, 1320, 0.18, south_blocked=True),
        _pt(47.5138, -120.8292, 1380, 0.15, south_blocked=True),
        _pt(47.5115, -120.8300, 1430, 0.12, south_blocked=True),
        _pt(47.5092, -120.8311, 1480, 0.65),
        _pt(47.5070, -120.8320, 1530, 0.35),
        _pt(47.5048, -120.8326, 1580, 0.80),
        _pt(47.5025, -120.8332, 1630, 0.85),
        _pt(47.5000, -120.8337, 1670, 0.40),
        _pt(47.4970, -120.8340, 1690, 0.10),
    ],
}

_FALLBACK_PROFILES = {
    "verizon_pixel": {
        "name": "Verizon Pixel 9", "carrier": "Verizon", "phone": "Pixel 9",
        "services": ["skylo"], "tsat_compatible": False,
        "plan": "Verizon · satellite messaging (no extra fee when eligible)",
        "monthly_cost": 0, "household_lines": 1,
    },
    "tmobile_galaxy": {
        "name": "T-Mobile Galaxy S25", "carrier": "T-Mobile", "phone": "Galaxy S25",
        "services": ["starlink"], "tsat_compatible": False,
        "plan": "T-Mobile · T-Satellite may require plan/add-on",
        "monthly_cost": 0, "household_lines": 1,
    },
    "att_iphone15": {
        "name": "AT&T iPhone 15", "carrier": "AT&T", "phone": "iPhone 15",
        "services": ["globalstar"], "tsat_compatible": False,
        "plan": "AT&T · Apple Messages via satellite (SMS carrier-dependent)",
        "monthly_cost": 0, "household_lines": 1,
    },
    "att_iphone13": {
        "name": "AT&T iPhone 13", "carrier": "AT&T", "phone": "iPhone 13",
        "services": [], "tsat_compatible": False,
        "plan": "AT&T plan", "monthly_cost": 0, "household_lines": 1,
    },
}

_FALLBACK_SERVICES = {
    "starlink": {"name": "T-Mobile T-Satellite", "constellation": "Starlink",
                 "cost": "$10/mo add-on (or included on qualifying plans)",
                 "blocked_by_south_ridge": False},
    "globalstar": {"name": "Apple Messages via Satellite", "constellation": "Globalstar",
                   "cost": "Free for two years after iPhone 14+ activation (region-limited)",
                   "blocked_by_south_ridge": False},
    "skylo": {"name": "Verizon satellite messaging (Skylo)", "constellation": "Skylo",
              "cost": "No extra fee when eligible", "blocked_by_south_ridge": True},
}


def _load_json(path: Path):
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _load_trails():
    trails = {}
    if _TRAILS_DIR.is_dir():
        for path in sorted(_TRAILS_DIR.glob("*.json")):
            trail = _load_json(path)
            if trail and trail.get("id"):
                trails[trail["id"]] = trail
    if not trails:
        trails[_FALLBACK_TRAIL["id"]] = _FALLBACK_TRAIL
    return trails


def _load_carriers():
    raw = _load_json(_CARRIERS_PATH) if _CARRIERS_PATH.is_file() else None
    if not raw:
        return CATALOG_AS_OF, dict(_FALLBACK_PROFILES), dict(_FALLBACK_SERVICES)
    as_of = raw.get("as_of") or CATALOG_AS_OF
    profiles = raw.get("profiles") or dict(_FALLBACK_PROFILES)
    services = raw.get("services") or dict(_FALLBACK_SERVICES)
    return as_of, profiles, services


TRAILS = _load_trails()
TRAIL = TRAILS.get("colchuck") or next(iter(TRAILS.values()))
CATALOG_AS_OF, PROFILES, SERVICES = _load_carriers()


def get_trail(trail_id: str | None):
    """Return a trail by id, defaulting to Colchuck / first available."""
    if trail_id and trail_id in TRAILS:
        return TRAILS[trail_id]
    return TRAIL


def find_profile(phone: str | None = None, carrier: str | None = None, profile_id: str | None = None):
    """Resolve a phone + carrier (or legacy profile id) to (profile_id, profile).

    Phone + carrier win when both are provided so the trip form is authoritative.
    """
    if phone and carrier:
        for pid, p in PROFILES.items():
            if p.get("phone") == phone and p.get("carrier") == carrier:
                return pid, p
    if profile_id and profile_id in PROFILES:
        return profile_id, PROFILES[profile_id]
    if phone:
        for pid, p in PROFILES.items():
            if p.get("phone") == phone:
                return pid, p
    default_id = "verizon_pixel" if "verizon_pixel" in PROFILES else next(iter(PROFILES))
    return default_id, PROFILES[default_id]


def phone_options():
    """Legacy helper: demo profile phone names (prefer PHONES / phones.json)."""
    seen = []
    for p in PROFILES.values():
        if p["phone"] not in seen:
            seen.append(p["phone"])
    return seen


def carrier_options():
    """Carriers shown in the trip form (compatibility catalog + Other)."""
    return list(COMPAT_CARRIERS) if COMPAT_CARRIERS else ["T-Mobile", "Verizon", "AT&T", "Other"]
