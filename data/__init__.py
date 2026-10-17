"""Trail route plus carrier catalog and synthetic commerce/customer data."""
import json
from pathlib import Path

_DIR = Path(__file__).resolve().parent


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


_CARRIERS = _load(_DIR / "carriers.json")
_PLANS = _load(_DIR / "plans.json")
_DEVICES = _load(_DIR / "devices.json")
_TRADEIN = _load(_DIR / "tradein.json")
_HOUSEHOLDS = _load(_DIR / "households.json")
TRAIL = _load(_DIR / "trails" / "colchuck.json")

CATALOG_AS_OF = _CARRIERS["as_of"]
PRICE_SOURCE_URL = _CARRIERS["price_source_url"]
DEVICES_SOURCE_URL = _CARRIERS["devices_source_url"]
SERVICES = _CARRIERS["services"]
TSAT_COMPATIBLE_PHONES = _CARRIERS["tsat_compatible_phones"]

PLANS = _PLANS["plans"]
ADDONS = _PLANS["addons"]
DEVICES = _DEVICES["devices"]
TRADEIN_CURVES = _TRADEIN["curves"]
HOUSEHOLDS = _HOUSEHOLDS["households"]
LINES = _HOUSEHOLDS["lines"]


def is_tsat_compatible(phone):
    """True if this phone model appears on T-Mobile's T-Satellite eligibility list."""
    needle = phone.strip().lower()
    for entry in TSAT_COMPATIBLE_PHONES:
        name = entry.strip().lower()
        if needle == name or name.endswith(needle) or needle.endswith(name):
            return True
    return False


def line_as_profile(line):
    """Adapt a household line to the profile shape get_coverage expects."""
    plan_name = line.get("plan") or PLANS.get(line.get("plan_id") or "", {}).get("name", "")
    return {
        "name": f"{line['display_name']} · {line['phone']}",
        "carrier": line["carrier"],
        "phone": line["phone"],
        "services": list(line.get("services") or []),
        "tsat_compatible": is_tsat_compatible(line["phone"]),
        "plan": plan_name,
        "monthly_cost": PLANS.get(line.get("plan_id") or "", {}).get("monthly_cost", 0),
        "household_lines": 1,
        "device_id": line.get("device_id"),
        "financing_balance_usd": line.get("financing_balance_usd", 0),
        "financing_months_left": line.get("financing_months_left", 0),
        "display_name": line.get("display_name", line["phone"]),
        "line_id": line["id"],
    }


PROFILES = {}
for pid, raw in _CARRIERS["profiles"].items():
    profile = dict(raw)
    profile["tsat_compatible"] = is_tsat_compatible(profile["phone"])
    PROFILES[pid] = profile


def get_household(household_id):
    hh = HOUSEHOLDS.get(household_id)
    if not hh:
        return None
    travelers = [LINES[tid] for tid in hh["travelers"] if tid in LINES]
    return {**hh, "lines": travelers}


# Curated phone list for the personal builder (compat checked via is_tsat_compatible).
PHONE_CHOICES = [
    "iPhone 17", "iPhone 16", "iPhone 15", "iPhone 14", "iPhone 13", "iPhone 12",
    "Pixel 10", "Pixel 9", "Pixel 9a", "Pixel 8",
    "Galaxy S25", "Galaxy S24", "Galaxy A14", "Galaxy A32",
]
CARRIER_CHOICES = ["T-Mobile", "Verizon", "AT&T", "Other"]
SATELLITE_CHOICES = [
    ("none", "None yet"),
    ("globalstar", "Apple Messages via Satellite"),
    ("skylo", "Google / Verizon satellite (Skylo)"),
    ("starlink", "T-Satellite (Starlink) — already on"),
]


def device_id_for_phone(phone):
    needle = (phone or "").strip().lower()
    for did, device in DEVICES.items():
        if device["model"].strip().lower() == needle:
            return did
    # Soft fallbacks so Timekeeper still works for common personal entries.
    aliases = {
        "iphone 12": "iphone_12",
        "iphone 13": "iphone_13",
        "iphone 15": "iphone_15",
        "iphone 16": "iphone_16",
        "pixel 9": "pixel_9",
        "pixel 10": "pixel_10",
        "galaxy s25": "galaxy_s25",
        "galaxy s24": "galaxy_s24",
        "galaxy a14": "galaxy_a14",
        "galaxy a32": "older_android",
        "pixel 8": "older_android",
    }
    return aliases.get(needle)


def services_from_choice(choice):
    if choice in SERVICES:
        return [choice]
    return []


def build_custom_line(index, display_name, phone, carrier, plan_name, satellite_choice,
                      financing_months_left=0, financing_balance_usd=0):
    """Build a household line from user-entered fields (not synthetic IDs)."""
    name = (display_name or "").strip() or f"Traveler {index + 1}"
    phone = (phone or "").strip() or "iPhone 15"
    carrier = (carrier or "").strip() or "Other"
    plan_name = (plan_name or "").strip() or "Custom plan"
    months = max(0, int(financing_months_left or 0))
    balance = max(0, float(financing_balance_usd or 0))
    return {
        "id": f"custom_{index}",
        "display_name": name,
        "carrier": carrier,
        "phone": phone,
        "device_id": device_id_for_phone(phone),
        "plan_id": None,
        "plan": plan_name,
        "services": services_from_choice(satellite_choice),
        "device_age_months": 12,
        "financing_balance_usd": balance,
        "financing_months_left": months,
        "tenure_months": 12,
        "existing_addons": ["tsatellite"] if satellite_choice == "starlink" else [],
    }


def empty_custom_household(trip_month="this trip", trip_date="", start_time="09:00"):
    return {
        "id": "custom",
        "name": "Your group",
        "summary": "Travelers you entered for this trip.",
        "carrier_home": "Mixed",
        "trip_month": trip_month,
        "trip_date": trip_date,
        "start_time": start_time or "09:00",
        "custom": True,
        "lines": [
            build_custom_line(0, "You", "iPhone 15", "T-Mobile", "My plan", "none"),
        ],
    }
