"""Trail route, carrier catalog, market facts, and situation inference."""
import json
import re
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
_MARKET = _load(_DIR / "market.json")
TRAIL = _load(_DIR / "trails" / "colchuck.json")

CATALOG_AS_OF = _CARRIERS["as_of"]
PRICE_SOURCE_URL = _CARRIERS["price_source_url"]
DEVICES_SOURCE_URL = _CARRIERS["devices_source_url"]
MARKET_SOURCES = _MARKET["sources"]
SERVICES = _CARRIERS["services"]
# Keep Skylo cost_detail honest for more than Verizon.
SERVICES["skylo"]["cost_detail"] = (
    "On supported phones with Verizon, Spectrum Mobile, or Xfinity Mobile (Skylo). "
    "Pixel satellite SOS may work more widely; two-way texting is carrier-dependent."
)
SERVICES["skylo"]["source_url"] = _MARKET["sources"]["verizon_satellite"]

TSAT_COMPATIBLE_PHONES = _CARRIERS["tsat_compatible_phones"]

PLANS = _PLANS["plans"]
ADDONS = _PLANS["addons"]
DEVICES = _DEVICES["devices"]
TRADEIN_CURVES = _TRADEIN["curves"]
HOUSEHOLDS = _HOUSEHOLDS["households"]
LINES = _HOUSEHOLDS["lines"]
MARKET = _MARKET

CARRIER_CHOICES = [c["name"] for c in _MARKET["carriers"]]
PLAN_STATUS_CHOICES = [(p["id"], p["label"], p["hint"]) for p in _MARKET["plan_statuses"]]
SATELLITE_CHOICES = [(c["id"], c["label"]) for c in _MARKET["satellite_today_choices"]]
SKYLO_CARRIERS = set(_MARKET["skylo_carriers"])
SKYLO_PHONES = {p.lower() for p in _MARKET["skylo_phones"]}
SKYLO_EXCLUDED = {p.lower() for p in _MARKET["skylo_excluded_phones"]}


def _phone_choices():
    seen = set()
    out = []
    for phone in list(TSAT_COMPATIBLE_PHONES) + list(_MARKET["incompatible_example_phones"]):
        key = phone.strip().lower()
        if key in seen or not phone.strip():
            continue
        seen.add(key)
        out.append(phone.strip())
    # Prefer common models near the top for the datalist UX.
    preferred = [
        "iPhone 16", "iPhone 15", "iPhone 14", "iPhone 13", "iPhone 12",
        "Pixel 10", "Pixel 9", "Pixel 9a", "Pixel 8",
        "Galaxy S25", "Galaxy S24", "Galaxy A14", "Galaxy A32",
        "Other / not listed",
    ]
    head = [p for p in preferred if p in out or p == "Other / not listed"]
    tail = [p for p in out if p not in head]
    return head + tail


PHONE_CHOICES = _phone_choices()


def is_tsat_compatible(phone):
    """True if this phone model appears on T-Mobile's T-Satellite eligibility list."""
    needle = (phone or "").strip().lower()
    if not needle or needle.startswith("other"):
        return False
    for entry in TSAT_COMPATIBLE_PHONES:
        name = entry.strip().lower()
        if needle == name or name.endswith(needle) or needle.endswith(name):
            return True
    return False


def _iphone_major(phone):
    m = re.search(r"iphone\s*(\d{1,2})", (phone or "").lower())
    return int(m.group(1)) if m else None


def has_apple_messages_satellite(phone):
    """Apple Messages via Satellite: iPhone 14 and later (public Apple docs)."""
    n = _iphone_major(phone)
    return n is not None and n >= 14


def has_skylo_phone(phone):
    needle = (phone or "").strip().lower()
    if needle in SKYLO_EXCLUDED:
        return False
    if needle in SKYLO_PHONES:
        return True
    # Allow close matches like "Samsung Galaxy S25 Ultra"
    for model in SKYLO_PHONES:
        if model in needle or needle in model:
            return True
    return False


def carrier_supports_skylo_texting(carrier):
    name = (carrier or "").strip()
    return name in SKYLO_CARRIERS


def plan_includes_tsatellite(plan_status, plan_name="", carrier=""):
    if plan_status == "tsat_included":
        return True
    if plan_status == "cannot_add":
        return False
    text = f"{plan_name} {carrier}".lower()
    return any(k in text for k in _MARKET["tsat_included_plan_keywords"])


def infer_services(phone, carrier, satellite_choice="auto", plan_status="can_add_tsat", plan_name=""):
    """
    Grounded defaults from public carrier/OEM docs.
    User overrides win; 'auto' estimates built-in services from phone + carrier.
    """
    choice = (satellite_choice or "auto").strip().lower()
    if choice in SERVICES:
        services = [choice]
    elif choice in ("none", ""):
        services = []
    else:  # auto
        services = []
        if has_apple_messages_satellite(phone):
            services.append("globalstar")
        if has_skylo_phone(phone) and carrier_supports_skylo_texting(carrier):
            services.append("skylo")
        if plan_includes_tsatellite(plan_status, plan_name, carrier):
            services.append("starlink")

    # Included plan always implies T-Satellite available on a compatible phone.
    if plan_includes_tsatellite(plan_status, plan_name, carrier) and "starlink" not in services:
        if is_tsat_compatible(phone):
            services.append("starlink")

    # De-dupe, preserve order
    seen = set()
    ordered = []
    for s in services:
        if s not in seen and s in SERVICES:
            seen.add(s)
            ordered.append(s)
    return ordered


def situation_summary(phone, carrier, services, plan_status):
    bits = []
    if "starlink" in services:
        bits.append("T-Satellite on")
    if "globalstar" in services:
        bits.append("Apple satellite")
    if "skylo" in services:
        bits.append("Skylo satellite")
    if not bits:
        bits.append("no day-to-day satellite texting yet")
    compat = "T-Satellite compatible" if is_tsat_compatible(phone) else "not on T-Satellite list"
    return f"{phone} · {carrier} · {', '.join(bits)} · {compat}"


def build_situation_profile(
    phone,
    carrier,
    plan_name="",
    plan_status="can_add_tsat",
    satellite_choice="auto",
    display_name="You",
    financing_months_left=0,
    financing_balance_usd=0,
    trip_date="",
    start_time="09:00",
):
    """User-entered situation → profile shape used by coverage + recommend."""
    phone = (phone or "").strip() or "Other / not listed"
    carrier = (carrier or "").strip() or "Other / not listed"
    plan_name = (plan_name or "").strip() or "My plan"
    services = infer_services(phone, carrier, satellite_choice, plan_status, plan_name)
    return {
        "id": "situation",
        "name": f"{display_name} · {phone}",
        "display_name": display_name or "You",
        "carrier": carrier,
        "phone": phone,
        "services": services,
        # Device capability only — account/lock restrictions live in plan_status.
        "tsat_compatible": is_tsat_compatible(phone),
        "plan": plan_name,
        "plan_status": plan_status,
        "satellite_choice": satellite_choice,
        "monthly_cost": 0,
        "household_lines": 1,
        "device_id": device_id_for_phone(phone),
        "financing_balance_usd": max(0, float(financing_balance_usd or 0)),
        "financing_months_left": max(0, int(financing_months_left or 0)),
        "summary": situation_summary(phone, carrier, services, plan_status),
        "inferred": satellite_choice == "auto",
        "trip_date": trip_date or "",
        "start_time": start_time or "09:00",
        "custom": True,
    }


def line_as_profile(line):
    """Adapt a household line to the profile shape get_coverage expects."""
    plan_name = line.get("plan") or PLANS.get(line.get("plan_id") or "", {}).get("name", "")
    services = list(line.get("services") or [])
    if line.get("satellite_choice") == "auto" or line.get("infer_services"):
        services = infer_services(
            line["phone"], line["carrier"],
            line.get("satellite_choice", "auto"),
            line.get("plan_status", "can_add_tsat"),
            plan_name,
        )
    return {
        "name": f"{line['display_name']} · {line['phone']}",
        "carrier": line["carrier"],
        "phone": line["phone"],
        "services": services,
        "tsat_compatible": is_tsat_compatible(line["phone"]),
        "plan_status": line.get("plan_status", "can_add_tsat"),
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


def device_id_for_phone(phone):
    needle = (phone or "").strip().lower()
    for did, device in DEVICES.items():
        if device["model"].strip().lower() == needle:
            return did
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


def build_custom_line(index, display_name, phone, carrier, plan_name, satellite_choice,
                      financing_months_left=0, financing_balance_usd=0,
                      plan_status="can_add_tsat"):
    """Build a household line from user-entered fields."""
    name = (display_name or "").strip() or f"Traveler {index + 1}"
    phone = (phone or "").strip() or "iPhone 15"
    carrier = (carrier or "").strip() or "Other / not listed"
    plan_name = (plan_name or "").strip() or "My plan"
    months = max(0, int(financing_months_left or 0))
    balance = max(0, float(financing_balance_usd or 0))
    services = infer_services(phone, carrier, satellite_choice, plan_status, plan_name)
    return {
        "id": f"custom_{index}",
        "display_name": name,
        "carrier": carrier,
        "phone": phone,
        "device_id": device_id_for_phone(phone),
        "plan_id": None,
        "plan": plan_name,
        "plan_status": plan_status,
        "satellite_choice": satellite_choice,
        "services": services,
        "device_age_months": 12,
        "financing_balance_usd": balance,
        "financing_months_left": months,
        "tenure_months": 12,
        "existing_addons": ["tsatellite"] if "starlink" in services else [],
        "infer_services": satellite_choice == "auto",
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
            build_custom_line(0, "You", "iPhone 15", "T-Mobile", "My plan", "auto", plan_status="can_add_tsat"),
        ],
    }
