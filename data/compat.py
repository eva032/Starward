"""Verified phone/carrier compatibility for Starward check-in SMS.

Track C owns this module. Recommendation outcomes for verified ordinary-SMS
setups still call Track B's get_recommendation. Unknown/SOS-only paths stay
honest and never invent coverage.
"""
from __future__ import annotations

import json
from pathlib import Path

_DIR = Path(__file__).resolve().parent
_PHONES_PATH = _DIR / "phones.json"
_COMPAT_PATH = _DIR / "compatibility.json"

# Functionality Starward needs for "OK" check-ins to a phone number.
CHECKIN_FUNCTIONALITY = "ordinary_sms"


def _load(path: Path, default):
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


_PHONES_RAW = _load(_PHONES_PATH, {"manufacturers": [], "phones": [], "as_of": None})
_COMPAT_RAW = _load(_COMPAT_PATH, {"carriers": [], "services": {}, "records": [], "as_of": None})

MANUFACTURERS = list(_PHONES_RAW.get("manufacturers") or ["Apple", "Samsung", "Google", "Other"])
CARRIERS = list(_COMPAT_RAW.get("carriers") or ["T-Mobile", "Verizon", "AT&T", "Other"])
PHONES = list(_PHONES_RAW.get("phones") or [])
PHONES_BY_ID = {p["id"]: p for p in PHONES}
COMPAT_SERVICES = dict(_COMPAT_RAW.get("services") or {})
COMPAT_RECORDS = list(_COMPAT_RAW.get("records") or [])
COMPAT_AS_OF = _COMPAT_RAW.get("as_of") or _PHONES_RAW.get("as_of") or "2026-10-17"

# Map legacy demo profile phone names → catalog ids.
_NAME_TO_ID = {p["name"]: p["id"] for p in PHONES}
_NAME_TO_ID.update({
    "Pixel 9": "pixel_9",
    "Galaxy S25": "galaxy_s25",
    "iPhone 15": "iphone_15",
    "iPhone 13": "iphone_13",
})


def phone_by_id(phone_id: str | None):
    if phone_id and phone_id in PHONES_BY_ID:
        return PHONES_BY_ID[phone_id]
    return None


def resolve_phone_id(phone_id: str | None = None, phone_name: str | None = None):
    if phone_id and phone_id in PHONES_BY_ID:
        return phone_id
    if phone_name and phone_name in _NAME_TO_ID:
        return _NAME_TO_ID[phone_name]
    if phone_name:
        for p in PHONES:
            if p["name"].lower() == phone_name.lower():
                return p["id"]
    return None


def phones_for_manufacturer(manufacturer: str | None):
    if not manufacturer or manufacturer == "Other":
        return [p for p in PHONES if p["manufacturer"] == "Other"] or PHONES
    return [p for p in PHONES if p["manufacturer"] == manufacturer]


def matching_records(phone_id: str | None, carrier: str | None, functionality: str | None = None):
    if not phone_id:
        return []
    out = []
    for rec in COMPAT_RECORDS:
        if phone_id not in rec.get("phone_ids", []):
            continue
        carriers = rec.get("carriers") or []
        if carrier and carriers and carrier not in carriers:
            continue
        if functionality and rec.get("functionality") != functionality:
            continue
        out.append(rec)
    return out


def _best_sms_record(phone_id, carrier):
    """Prefer supported ordinary_sms, else unknown ordinary_sms."""
    sms = matching_records(phone_id, carrier, CHECKIN_FUNCTIONALITY)
    supported = [r for r in sms if r.get("status") == "supported"]
    if supported:
        # Prefer no-activation (e.g. Verizon Skylo) over add-on paths when both apply.
        supported.sort(key=lambda r: (
            0 if not r.get("requires_activation") else 1,
            0 if carrier in (r.get("carriers") or []) else 1,
        ))
        return supported[0]
    unknown = [r for r in sms if r.get("status") == "unknown"]
    if unknown:
        # Prefer carrier-specific rows (e.g. T-Mobile tutorial list) over broad Apple SMS notes.
        unknown.sort(key=lambda r: (
            0 if len(r.get("carriers") or []) == 1 else 1,
            0 if r.get("service") == "starlink" and carrier == "T-Mobile" else 1,
            0 if not r.get("requires_activation") else 1,
        ))
        return unknown[0]
    unsupported = [r for r in sms if r.get("status") == "unsupported"]
    return unsupported[0] if unsupported else None


def _sos_only(phone_id, carrier):
    sos = matching_records(phone_id, carrier, "emergency_sos")
    sms = matching_records(phone_id, carrier, CHECKIN_FUNCTIONALITY)
    has_supported_sos = any(r.get("status") == "supported" for r in sos)
    has_supported_sms = any(r.get("status") == "supported" for r in sms)
    return has_supported_sos and not has_supported_sms and not any(
        r.get("status") == "unknown" for r in sms
    )


def needs_activation_question(phone_id: str | None, carrier: str | None) -> bool:
    """Ask only when a T-Satellite / add-on path is the relevant SMS option."""
    for r in matching_records(phone_id, carrier, CHECKIN_FUNCTIONALITY):
        if r.get("service") != "starlink":
            continue
        if r.get("status") in ("supported", "unknown") and r.get("requires_activation"):
            return True
    sms = _best_sms_record(phone_id, carrier)
    return bool(sms and sms.get("status") == "supported" and sms.get("requires_activation"))


def activation_label(phone_id: str | None, carrier: str | None) -> str:
    sms = _best_sms_record(phone_id, carrier)
    if sms and sms.get("activation_label"):
        return sms["activation_label"]
    for r in matching_records(phone_id, carrier):
        if r.get("activation_label"):
            return r["activation_label"]
    return "satellite messaging"


def tsat_addon_verified(phone_id: str | None, carrier: str | None) -> bool:
    """True only when a catalog record both marks T-Satellite purchase-eligible and ordinary SMS supported."""
    return any(
        r.get("tsat_addon_verified") and r.get("status") == "supported"
        for r in matching_records(phone_id, carrier, CHECKIN_FUNCTIONALITY)
    )


def _tsat_potential_note(sms) -> str:
    if sms and sms.get("eligibility"):
        return sms["eligibility"]
    return (
        "Potentially compatible with T-Satellite. Confirm your device and plan eligibility "
        "with T-Mobile before relying on satellite SMS."
    )


def build_sources(phone_id: str | None, carrier: str | None):
    seen = set()
    sources = []
    for r in matching_records(phone_id, carrier):
        url = r.get("source_url")
        if not url or url in seen:
            continue
        seen.add(url)
        sources.append({
            "label": r.get("source_label") or url,
            "url": url,
            "verified_as_of": r.get("verified_as_of") or COMPAT_AS_OF,
            "functionality": r.get("functionality"),
            "status": r.get("status"),
        })
    return sources


def resolve_setup(
    phone_id: str | None,
    carrier: str | None,
    satellite_activated: str | None = None,
    demo_profiles: dict | None = None,
):
    """Resolve phone + carrier (+ activation) into a runtime profile + status.

    Returns dict with keys: profile, phone, carrier, status, status_label,
    ask_activation, sources, sms_record, demo_profile_id, notes.
    """
    phone = phone_by_id(phone_id) or {"id": phone_id or "unknown", "name": phone_id or "Unknown",
                                      "manufacturer": "Other"}
    carrier = carrier or "Other"
    activated = (satellite_activated or "").strip().lower()
    demo_profiles = demo_profiles or {}

    # Preserve exact demo profile behavior when names match.
    demo_id = None
    for pid, p in demo_profiles.items():
        if p.get("phone") == phone.get("name") and p.get("carrier") == carrier:
            demo_id = pid
            break

    sms = _best_sms_record(phone_id, carrier)
    sources = build_sources(phone_id, carrier)
    ask = needs_activation_question(phone_id, carrier)
    notes = []

    purchase_ok = tsat_addon_verified(phone_id, carrier)

    # Demo profiles: never invent verified SMS or purchases. Only paint map services when
    # ordinary SMS is catalog-verified (Verizon Skylo). Unverified demos keep services empty.
    if demo_id:
        profile = dict(demo_profiles[demo_id])
        # Do not surface unverified demo plan dollar amounts in the UI meta line.
        profile["monthly_cost"] = 0

        if demo_id == "verizon_pixel":
            status = "verified"
            notes.append(
                "Satellite texting supported on eligible Verizon plans (Skylo). "
                "T-Satellite purchase eligibility is not verified for this carrier/device."
            )
        elif demo_id == "tmobile_galaxy":
            status = "conditional"
            profile = {**profile, "services": []}
            notes.append(
                "Satellite texting compatibility not verified for Galaxy S25 + T-Mobile. "
                + _tsat_potential_note(sms)
            )
        elif demo_id == "att_iphone15":
            status = "conditional"
            # iMessage via satellite ≠ ordinary SMS check-ins — do not color the map as SMS-covered.
            profile = {**profile, "services": []}
            notes.append(
                "Apple Messages via satellite (iMessage) is documented for iPhone 14+. "
                "Ordinary satellite SMS to a Starward number is carrier-dependent and not confirmed. "
                "Carrier-provided satellite is a separate service."
            )
        elif demo_id == "att_iphone13":
            status = "unsupported"
            profile = {**profile, "services": []}
            notes.append("No ordinary satellite SMS path in the demo catalog for this phone.")
        else:
            status = "verified" if sms and sms.get("status") == "supported" else "unknown"

        if ask and activated == "no" and "starlink" in profile.get("services", []):
            profile = {**profile, "services": [s for s in profile["services"] if s != "starlink"]}
            notes.append("T-Satellite is not activated on this line, so check-in SMS is treated as inactive.")
        elif ask and activated == "unsure":
            notes.append("Satellite activation not confirmed — treat coverage as conditional.")

        # Purchase recommendations require verified T-Satellite eligibility — including demos.
        profile["tsat_compatible"] = purchase_ok
        return _pack(profile, phone, carrier, status, ask, sources, sms, demo_id, notes, activated)

    # Dynamic resolution from compatibility records.
    if _sos_only(phone_id, carrier):
        profile = _dynamic_profile(phone, carrier, services=[], tsat_compatible=False)
        notes.append("This device has verified emergency SOS via satellite, not ordinary SMS for Starward check-ins.")
        return _pack(profile, phone, carrier, "sos_only", ask, sources, sms, None, notes, activated)

    if not sms:
        profile = _dynamic_profile(phone, carrier, services=[], tsat_compatible=False)
        notes.append("Satellite texting compatibility not verified for this phone and carrier.")
        return _pack(profile, phone, carrier, "unknown", False, sources, None, None, notes, activated)

    status = sms.get("status") or "unknown"
    service = sms.get("service")
    requires = bool(sms.get("requires_activation"))

    # Active services for coverage only when ordinary SMS is supported and activated (if required).
    services = []
    if status == "supported" and service and service != "pixel_sos":
        if not requires or activated == "yes":
            services = [service]
        elif activated == "no":
            services = []
            notes.append(f"{sms.get('activation_label') or 'Satellite messaging'} is not activated.")
        else:
            services = []
            notes.append("Activation not confirmed — not treating satellite SMS as active.")
            status = "conditional"
    elif status == "unknown":
        if service == "starlink":
            notes.append(_tsat_potential_note(sms))
        else:
            notes.append("Satellite texting compatibility not verified for ordinary check-in SMS.")
        if requires and activated == "yes":
            notes.append("You reported the service is active, but device/carrier eligibility is still unverified.")
        services = []  # do not claim ordinary SMS coverage on unknown
    elif status == "unsupported":
        notes.append("Ordinary satellite SMS is documented as unsupported for this setup.")

    profile = _dynamic_profile(
        phone, carrier,
        services=services,
        tsat_compatible=purchase_ok,
        plan=_plan_label(carrier, service, requires, activated),
    )

    # Map status labels for UI.
    ui_status = status
    if status == "supported" and requires and activated != "yes":
        ui_status = "needs_activation" if activated == "no" else "conditional"
    elif status == "unknown" and service == "starlink":
        ui_status = "conditional"
    elif status == "unknown":
        ui_status = "unknown"

    return _pack(profile, phone, carrier, ui_status, ask, sources, sms, None, notes, activated)


def _plan_label(carrier, service, requires, activated):
    if service == "skylo":
        return f"{carrier} · satellite messaging (no extra fee, when eligible)"
    if service == "starlink":
        if activated == "yes":
            return f"{carrier} · T-Satellite reported active"
        if requires:
            return f"{carrier} · T-Satellite may require plan/add-on"
        return f"{carrier} · T-Satellite"
    if service == "globalstar":
        return f"{carrier} · Apple Messages via satellite (SMS carrier-dependent)"
    return f"{carrier} plan"


def _dynamic_profile(phone, carrier, services, tsat_compatible, plan=None):
    return {
        "name": f"{carrier} {phone.get('name')}",
        "carrier": carrier,
        "phone": phone.get("name"),
        "services": list(services),
        "tsat_compatible": bool(tsat_compatible),
        "plan": plan or f"{carrier} plan",
        "monthly_cost": 0,
        "household_lines": 1,
    }


def _pack(profile, phone, carrier, status, ask, sources, sms, demo_id, notes, activated):
    if status == "supported":
        status = "verified"
    # Prefer the T-Mobile potential-compatibility wording when that is the SMS record.
    if status == "conditional" and sms and sms.get("service") == "starlink":
        status_label = (
            "Potentially compatible with T-Satellite — confirm with T-Mobile before relying on it."
        )
    else:
        labels = {
            "verified": "Satellite texting supported on eligible plans (see sources)",
            "needs_activation": "Activate satellite messaging before relying on check-ins",
            "conditional": "Satellite texting compatibility not fully verified",
            "unknown": "Satellite texting compatibility not verified",
            "sos_only": "Emergency SOS only — not ordinary check-in SMS",
            "unsupported": "Ordinary satellite SMS not supported",
        }
        status_label = labels.get(status, labels["unknown"])
    return {
        "profile": profile,
        "phone": phone,
        "carrier": carrier,
        "status": status,
        "status_label": status_label,
        "ask_activation": ask,
        "activation": activated or "",
        "sources": sources,
        "sms_record": sms,
        "demo_profile_id": demo_id,
        "notes": notes,
        "as_of": COMPAT_AS_OF,
        "allow_tsat_purchase": bool(profile.get("tsat_compatible")),
    }


def unknown_recommendation(trail, setup, as_of=None):
    """Informational recommendation when ordinary SMS is not verified for Starward check-ins."""
    total = 3
    cell = " and ".join(trail.get("cell_spots") or ["trailhead areas with cell signal"])
    status = setup["status"]
    phone = setup["phone"].get("name")
    notes = " ".join(setup.get("notes") or [])
    sms = setup.get("sms_record") or {}

    if status == "sos_only":
        headline = "Emergency SOS only — not enough for Starward check-ins."
        reason = (
            f"{phone} has verified emergency satellite SOS, which is not the same as sending "
            f"an ordinary OK text. {notes}"
        ).strip()
        outcome = "not_compatible"
    elif status == "unsupported":
        headline = "Ordinary satellite SMS is not supported on this setup."
        reason = notes or f"No verified ordinary SMS path for {phone} on {setup['carrier']}."
        outcome = "not_compatible"
    elif status == "needs_activation":
        label = activation_label(setup["phone"].get("id"), setup["carrier"])
        headline = f"Confirm and activate {label} before relying on satellite check-ins."
        reason = notes or f"Eligibility for {label} is not fully verified for purchase recommendations."
        outcome = "unknown"
    elif status == "conditional" and setup.get("demo_profile_id") == "att_iphone15":
        headline = "Satellite check-in SMS is not confirmed on this phone."
        reason = (
            "Apple Messages via satellite can send iMessage off-grid on iPhone 14+, but Starward "
            "check-ins need ordinary SMS to a phone number. SMS via satellite depends on your carrier. "
            "Carrier-provided satellite (e.g. T-Satellite) is separate and not verified here."
        )
        outcome = "unknown"
    elif status == "conditional" and (sms.get("service") == "starlink" or setup.get("demo_profile_id") == "tmobile_galaxy"):
        headline = "Potentially compatible with T-Satellite — confirm before you rely on it."
        reason = notes or _tsat_potential_note(sms)
        outcome = "unknown"
    else:
        headline = "Satellite texting compatibility not verified."
        reason = notes or (
            f"We could not verify ordinary satellite SMS for {phone} on {setup['carrier']}. "
            "You can still build a check-in plan using estimated sky openness."
        )
        outcome = "unknown"

    options = [{
        "action": "Continue with an estimated check-in plan",
        "cost": "$0",
        "checkins_covered": None,
        "total": total,
        "reason": reason,
    }, {
        "action": "Plan check-ins where you'll have regular cell signal",
        "cost": "$0",
        "checkins_covered": None,
        "total": total,
        "reason": f"You should have regular signal at the {cell}. Tell your contact to expect "
                  f"texts from those spots and silence in between.",
    }]

    # Never insert a buy/add-on option unless T-Satellite eligibility is catalog-verified.
    if tsat_addon_verified(setup["phone"].get("id"), setup["carrier"]):
        options.insert(0, {
            "action": "Confirm T-Satellite eligibility, then add it if needed",
            "cost": "$10/mo (if not included on your plan)",
            "checkins_covered": None,
            "total": total,
            "reason": (
                "Ordinary SMS eligibility for T-Satellite is verified in our catalog for this "
                "device class. Still confirm your plan in T-Life before purchase."
            ),
        })

    return {
        "outcome": outcome,
        "headline": headline,
        "options": options,
        "as_of": as_of or COMPAT_AS_OF,
        "current_covered": 0,
        "best_covered": 0,
        "total": total,
        "compatibility_status": status,
        "compatibility_label": setup["status_label"],
        "sources": setup.get("sources") or [],
        "notes": setup.get("notes") or [],
    }


def should_use_recommend_engine(setup) -> bool:
    """True only when ordinary SMS is verified (or verified T-Satellite activation path)."""
    status = setup["status"]
    phone_id = setup["phone"].get("id")
    carrier = setup["carrier"]
    if status == "verified":
        return True
    if status == "needs_activation" and tsat_addon_verified(phone_id, carrier):
        return True
    return False


def build_recommendation(trail, setup, get_recommendation_fn, trip_date=None, start_time=None):
    """Central eligibility gate for Track B outcomes + honest fallbacks."""
    allow_purchase = tsat_addon_verified(setup["phone"].get("id"), setup["carrier"])
    # Keep profile flag aligned so recommend.py and UI stay consistent.
    setup["profile"]["tsat_compatible"] = allow_purchase

    if should_use_recommend_engine(setup):
        rec = get_recommendation_fn(
            trail,
            setup["profile"],
            trip_date=trip_date,
            start_time=start_time,
            allow_tsat_purchase=allow_purchase,
        )
        # Belt-and-suspenders: never surface a purchase outcome without verified eligibility.
        if rec.get("outcome") == "add_service" and not allow_purchase:
            rec = unknown_recommendation(trail, setup)
        else:
            rec = dict(rec)
    else:
        rec = unknown_recommendation(trail, setup)

    rec["compatibility_status"] = setup["status"]
    rec["compatibility_label"] = setup["status_label"]
    rec["sources"] = setup.get("sources") or []
    rec["notes"] = setup.get("notes") or []
    return rec
