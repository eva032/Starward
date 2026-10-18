"""Starward Flask app — Track C: trip inputs, map, share flow; Track B: per-hiker and group recommendations."""
from __future__ import annotations

import inspect
import json
import os
import re
from datetime import date, datetime

import folium
from pathlib import Path

from flask import Flask, redirect, render_template, request, send_from_directory, session, url_for

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from coverage import get_coverage, start_time_for_input, trip_month_label
from data import (
    COMPAT_AS_OF,
    MARKET_SOURCES,
    PHONES,
    PROFILES,
    SERVICES,
    TRAILS,
    activation_label,
    build_custom_line,
    build_situation_profile,
    build_sources,
    carrier_options,
    get_trail,
    line_as_profile,
    needs_activation_question,
    phone_by_id,
    resolve_phone_id,
)
from data.compat import tsat_addon_verified

OTHER_PHONE_ID = "other_phone"


def _phone_display_label(phone: dict) -> str:
    if phone.get("id") == OTHER_PHONE_ID:
        return "I can't find my phone"
    maker = phone.get("manufacturer") or ""
    name = phone.get("name") or ""
    if maker and name.startswith(maker):
        return name
    return f"{maker} {name}".strip()
from guardian import handle_checkin, photon_configured, share_plan, simulate_missed
from recommend import get_household_recommendation, get_recommendation

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "starward-demo-localhost-only")
_PITCH_DIR = Path(__file__).resolve().parent / "pitch"

DEFAULT_PROFILE = "verizon_pixel"
DEFAULT_PHONE_ID = "pixel_9"
DEFAULT_CARRIER = "Verizon"
COLORS = {"green": "#1f9d55", "yellow": "#e0a800", "red": "#d64545"}
PHONE_RE = re.compile(r"^\+?[\d\s().-]{7,20}$")
MAX_COMPANIONS = 5


def fake_mode():
    """Demo/Fake mode when Photon is not configured (or coverage is still simulated)."""
    return not photon_configured()


def _call_with_supported(fn, *args, **kwargs):
    """Call fn, dropping kwargs the callee does not accept (teammate lag-safe)."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return fn(*args, **{k: v for k, v in kwargs.items() if v is not None})
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        return fn(*args, **{k: v for k, v in kwargs.items() if v is not None})
    accepted = {k: v for k, v in kwargs.items() if k in sig.parameters and v is not None}
    return fn(*args, **accepted)


def _normalize_phone(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _valid_phone(value: str) -> bool:
    if not value or not PHONE_RE.match(value):
        return False
    digits = re.sub(r"\D", "", value)
    return 10 <= len(digits) <= 15


def _parse_trip_date(raw: str):
    raw = (raw or "").strip()
    if not raw:
        return None, "Trip date is required."
    try:
        return date.fromisoformat(raw), None
    except ValueError:
        return None, "Trip date must be YYYY-MM-DD."


def _default_form():
    profile = PROFILES[DEFAULT_PROFILE]
    phone = phone_by_id(DEFAULT_PHONE_ID) or {"id": DEFAULT_PHONE_ID, "name": profile["phone"],
                                              "manufacturer": "Google"}
    today = date.today().isoformat()
    return {
        "trail_id": "colchuck" if "colchuck" in TRAILS else next(iter(TRAILS)),
        "trip_date": today,
        "start_time": "09:00",
        "hiker_name": "",
        "hiker_number": "",
        "manufacturer": phone.get("manufacturer", "Google"),
        "phone_id": phone["id"],
        "phone": phone.get("name", profile["phone"]),
        "phone_label": _phone_display_label(phone),
        "carrier": DEFAULT_CARRIER,
        "satellite_activated": "",
        "contact": "",
        "profile_id": DEFAULT_PROFILE,
    }


def _form_from_request(src) -> dict:
    defaults = _default_form()
    phone_id = resolve_phone_id(
        phone_id=src.get("phone_id"),
        phone_name=src.get("phone"),
    ) or defaults["phone_id"]
    phone = phone_by_id(phone_id)
    if phone:
        manufacturer = phone["manufacturer"]
        phone_name = phone["name"]
        phone_label = _phone_display_label(phone)
    else:
        # Unlisted selection still continues with unknown compatibility.
        phone_id = OTHER_PHONE_ID
        phone = phone_by_id(OTHER_PHONE_ID)
        manufacturer = phone["manufacturer"] if phone else "Other"
        phone_name = phone["name"] if phone else "Other / not listed"
        phone_label = _phone_display_label(phone or {"id": OTHER_PHONE_ID, "name": phone_name,
                                                     "manufacturer": manufacturer})

    # Legacy ?profile= deeplink
    profile_id = src.get("profile") or src.get("profile_id") or ""
    if profile_id in PROFILES and not src.get("phone_id") and not src.get("phone"):
        p = PROFILES[profile_id]
        phone_id = resolve_phone_id(phone_name=p["phone"]) or phone_id
        phone = phone_by_id(phone_id)
        manufacturer = phone["manufacturer"] if phone else manufacturer
        phone_name = p["phone"]
        phone_label = _phone_display_label(phone) if phone else phone_name
        carrier = p["carrier"]
    else:
        carrier = (src.get("carrier") or defaults["carrier"]).strip()

    return {
        "companions": _companions_from(src),
        "trail_id": src.get("trail_id") or defaults["trail_id"],
        "trip_date": src.get("trip_date") or defaults["trip_date"],
        "start_time": src.get("start_time") or defaults["start_time"],
        "hiker_name": (src.get("hiker_name") or "").strip(),
        "hiker_number": _normalize_phone(src.get("hiker_number", "")),
        "manufacturer": manufacturer,
        "phone_id": phone_id,
        "phone": phone_name,
        "phone_label": phone_label,
        "carrier": carrier,
        "satellite_activated": (src.get("satellite_activated") or "").strip().lower(),
        "contact": _normalize_phone(src.get("contact", "")),
        "profile_id": profile_id or defaults["profile_id"],
    }


def _companions_from(src) -> list:
    """People hiking with the hiker: [{"name", "phone_id", "carrier"}], from the form or a saved trip."""
    if hasattr(src, "getlist"):
        rows = zip(src.getlist("companion_name"), src.getlist("companion_phone_id"),
                   src.getlist("companion_carrier"))
        people = [{"name": (n or "").strip(), "phone_id": (pid or "").strip(), "carrier": (c or "").strip()}
                  for n, pid, c in rows]
    else:
        people = [dict(p) for p in (src.get("companions") or [])]
    people = [p for p in people if p["name"] or p["phone_id"]][:MAX_COMPANIONS]
    for i, person in enumerate(people):
        person["name"] = person["name"] or f"Hiker {i + 2}"
    return people


def _validate_trip(form: dict):
    errors = []
    if form["trail_id"] not in TRAILS:
        errors.append("Select a valid trail.")
    trip_date, date_err = _parse_trip_date(form["trip_date"])
    if date_err:
        errors.append(date_err)
    if not form["start_time"]:
        errors.append("Start time is required.")
    if not form["hiker_name"]:
        errors.append("Hiker name is required.")
    if not _valid_phone(form["hiker_number"]):
        errors.append("Enter a valid hiker phone number.")
    if not phone_by_id(form.get("phone_id")):
        errors.append("Select a phone from the list, or choose “I can't find my phone”.")
    if form["carrier"] not in carrier_options():
        errors.append("Select a wireless carrier.")
    if needs_activation_question(form.get("phone_id"), form.get("carrier")):
        if form.get("satellite_activated") not in ("yes", "no", "unsure"):
            label = activation_label(form.get("phone_id"), form.get("carrier"))
            errors.append(f"Tell us whether {label} is already activated on this line.")
    if form["contact"] and not _valid_phone(form["contact"]):
        errors.append("Emergency contact phone looks invalid.")
    for person in form.get("companions", []):
        if not phone_by_id(person["phone_id"]):
            errors.append(f"Pick a phone for {person['name']}.")
        if person["carrier"] not in carrier_options():
            errors.append(f"Pick a carrier for {person['name']}.")
    return trip_date, errors


def _profile_for_starward_checkins(profile: dict) -> dict:
    """Exclude Apple Messages via Satellite from Starward check-in SMS services.

    Track B's infer_services may list globalstar (iMessage/SMS via satellite on iPhone 14+).
    That is not the same as verified ordinary SMS to Starward's number, so coverage and
    recommendations must not treat it as check-in coverage.
    """
    raw = list(profile.get("services") or [])
    out = dict(profile)
    out["services"] = [s for s in raw if s != "globalstar"]
    out["apple_messages_satellite"] = "globalstar" in raw
    return out


def _line_for_starward_checkins(line: dict) -> dict:
    """Same globalstar exclusion for household / companion lines."""
    raw = list(line.get("services") or [])
    out = dict(line)
    out["services"] = [s for s in raw if s != "globalstar"]
    out["apple_messages_satellite"] = "globalstar" in raw
    return out


def _setup_for(form: dict):
    """Phone + carrier answers -> Track B situation profile, plus official source links."""
    phone_id = form.get("phone_id")
    carrier = form.get("carrier")
    phone_row = phone_by_id(phone_id) or {}
    phone_name = phone_row.get("name") or form.get("phone") or "Other / not listed"
    # "Is T-Satellite already activated?" maps to Track B's plan status. The same question is
    # asked about other carriers' satellite features; only a T-Satellite "yes" means it's included.
    asked_tsat = activation_label(phone_id, carrier) == "T-Satellite"
    plan_status = "tsat_included" if asked_tsat and form.get("satellite_activated") == "yes" else "can_add_tsat"
    profile = build_situation_profile(
        phone=phone_name,
        carrier=carrier,
        plan_status=plan_status,
        satellite_choice="auto",
        display_name=form.get("hiker_name") or "You",
        trip_date=form.get("trip_date") or "",
        start_time=start_time_for_input(form.get("start_time"), "09:00"),
    )
    profile = _profile_for_starward_checkins(profile)
    return {
        "profile": profile,
        "phone": phone_row or {"id": phone_id, "name": phone_name},
        "ask_activation": needs_activation_question(phone_id, carrier),
        "sources": build_sources(phone_id, carrier),
        "as_of": COMPAT_AS_OF,
    }


def _recommendation_for(trail, setup):
    """Track B recommendation, with Track C eligibility caveats when purchase isn't catalog-verified."""
    rec = dict(get_recommendation(trail, setup["profile"]))
    phone_id = (setup.get("phone") or {}).get("id")
    carrier = setup["profile"].get("carrier")
    catalog_ok = bool(phone_id and tsat_addon_verified(phone_id, carrier))
    rec["tsat_catalog_verified"] = catalog_ok
    if rec.get("outcome") == "add_service" and not catalog_ok:
        # Keep B's outcome and ranking; mark purchase as needing confirmation (team: B owns final eligibility).
        headline = (rec.get("headline") or "").rstrip(".")
        rec["headline"] = (
            f"{headline}. Confirm device and plan eligibility before buying — "
            f"Starward has not independently verified T-Satellite for this line."
        )
        options = []
        for i, opt in enumerate(rec.get("options") or []):
            o = dict(opt)
            if i == 0:
                extra = (
                    "Confirm T-Satellite eligibility for this phone and account "
                    "(e.g. in T-Life) before purchasing."
                )
                o["caveat"] = f"{o['caveat']} {extra}".strip() if o.get("caveat") else extra
            options.append(o)
        rec["options"] = options
        rec["tsat_eligibility"] = "needs_confirmation"
    else:
        rec["tsat_eligibility"] = "catalog_verified" if catalog_ok else "not_applicable"
    return rec


def _group_for(form, setup):
    """Hiker + companions as a Track B household; None when hiking alone."""
    if not form.get("companions"):
        return None
    trip_date = form.get("trip_date") or ""
    start = start_time_for_input(form.get("start_time"), "09:00")
    hiker = setup["profile"]
    lines = [build_custom_line(0, form.get("hiker_name") or "You", hiker["phone"], hiker["carrier"],
                               "My plan", "auto", plan_status=hiker["plan_status"])]
    for i, person in enumerate(form["companions"], 1):
        phone = (phone_by_id(person["phone_id"]) or {}).get("name") or "Other / not listed"
        lines.append(build_custom_line(i, person["name"], phone, person["carrier"], "My plan", "auto"))
    lines = [_line_for_starward_checkins(line) for line in lines]
    return {
        "id": "trip_group", "name": "Your group", "summary": "", "custom": True,
        "trip_date": trip_date, "start_time": start, "trip_month": trip_month_label(trip_date, "this trip"),
        "lines": lines,
    }


def _build_map(trail, coverage):
    points = trail["points"]
    m = folium.Map(tiles="OpenTopoMap", control_scale=True)
    m.fit_bounds(
        [[min(p["lat"] for p in points), min(p["lon"] for p in points)],
         [max(p["lat"] for p in points), max(p["lon"] for p in points)]],
        padding=(40, 40),
    )

    segs = coverage["segments"]
    folium.PolyLine([(s["lat"], s["lon"]) for s in segs], color="#ffffff", weight=11, opacity=0.9).add_to(m)
    for a, b in zip(segs, segs[1:]):
        folium.PolyLine(
            [(a["lat"], a["lon"]), (b["lat"], b["lon"])],
            color=COLORS[a["color"]], weight=6, opacity=0.95,
            tooltip=f"Sky openness {a['openness']:.2f} (estimate)",
        ).add_to(m)

    for i, c in enumerate(coverage["checkins"], 1):
        status = (
            "Estimated check-in opportunity — not guaranteed"
            if c["covered"] else
            "Low estimated chance — not guaranteed"
        )
        windows = ", ".join(c["windows"]) or "none expected"
        popup = (
            f"<div style='font-family:system-ui,sans-serif;font-size:13px'><b>{c['name']}</b><br>"
            f"Expected {c['time']}<br>Best-chance windows: {windows}<br>{status}</div>"
        )
        badge = (
            f"<div style='width:26px;height:26px;border-radius:50%;background:{COLORS[c['color']]};"
            f"color:#fff;border:3px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.35);display:flex;"
            f"align-items:center;justify-content:center;font:700 13px system-ui,sans-serif'>{i}</div>"
        )
        folium.Marker(
            (c["lat"], c["lon"]),
            popup=folium.Popup(popup, max_width=260),
            tooltip=c["name"],
            icon=folium.DivIcon(html=badge, icon_size=(32, 32), icon_anchor=(16, 16)),
        ).add_to(m)

    return m.get_root().render()


def _trip_from_session():
    return session.get("trip")


def _save_trip(form, trip_date):
    session["trip"] = {
        **form,
        "trip_date": trip_date.isoformat() if trip_date else form["trip_date"],
    }


def _trip_label(trip_date):
    """'Sat, Oct 18' from an ISO date; the raw value if it doesn't parse."""
    try:
        d = date.fromisoformat(str(trip_date))
    except ValueError:
        return trip_date or ""
    return f"{d:%a}, {d:%b} {d.day}"


def _phones_by_maker():
    """[(manufacturer, [phone, ...]), ...] for the companions' phone dropdowns."""
    groups = {}
    for p in PHONES:
        groups.setdefault(p.get("manufacturer") or "Other", []).append(p)
    order = ["Apple", "Samsung", "Google"]
    return sorted(groups.items(), key=lambda kv: (order.index(kv[0]) if kv[0] in order else len(order), kv[0]))


def _activation_map():
    """{carrier: {phone_id: question label}} for every pair where the server asks about activation."""
    return {
        carrier: {p["id"]: activation_label(p["id"], carrier)
                  for p in PHONES if needs_activation_question(p["id"], carrier)}
        for carrier in carrier_options()
    }


def _render(form=None, notice=None, view="current", errors=None, show_plan=False, person=0):
    form = form or _default_form()
    setup = _setup_for(form)
    profile = setup["profile"]
    form["profile_id"] = setup.get("demo_profile_id") or form.get("profile_id") or ""
    form["phone"] = setup["phone"].get("name") or form.get("phone")
    phone_row = phone_by_id(form.get("phone_id"))
    form["phone_label"] = form.get("phone_label") or (
        _phone_display_label(phone_row) if phone_row else form.get("phone", "")
    )
    form["manufacturer"] = (phone_row or {}).get("manufacturer") or form.get("manufacturer") or "Other"

    trail = get_trail(form.get("trail_id"))
    trip_date = form.get("trip_date")
    start_time = form.get("start_time")

    rec = _recommendation_for(trail, setup)
    household = _group_for(form, setup) if show_plan else None
    group = get_household_recommendation(trail, household=household) if household else None

    # The map shows the hiker by default, or another person in the group.
    person = person if household and 0 <= person < len(household["lines"]) else 0
    map_profile = line_as_profile(household["lines"][person]) if person else profile
    view = view if person == 0 and rec.get("outcome") == "add_service" else "current"
    services = profile["services"] + ["starlink"] if view == "tsat" else None
    # Only pass known coverage services (skip pixel_sos etc.).
    if services is not None:
        services = [s for s in services if s in SERVICES]
    coverage = _call_with_supported(
        get_coverage,
        trail,
        map_profile,
        services=services,
        trip_date=trip_date,
        start_time=start_time,
    )

    phones_payload = [
        {
            "id": p["id"],
            "name": p["name"],
            "manufacturer": p["manufacturer"],
            "label": _phone_display_label(p),
        }
        for p in PHONES
    ]

    return render_template(
        "index.html",
        trail=trail,
        trails=TRAILS,
        profiles=PROFILES,
        services=SERVICES,
        carriers=carrier_options(),
        phones_json=json.dumps(phones_payload),
        form=form,
        setup=setup,
        profile_id=form.get("profile_id"),
        profile=profile,
        coverage=coverage,
        rec=rec,
        group=group,
        household=household,
        person=person,
        trip_label=_trip_label(trip_date),
        phones_by_maker=_phones_by_maker(),
        map_name=household["lines"][person]["display_name"] if household else form.get("hiker_name"),
        max_companions=MAX_COMPANIONS,
        view=view,
        map_doc=_build_map(trail, coverage) if show_plan else None,
        notice=notice,
        errors=errors or [],
        show_plan=show_plan,
        fake_mode=fake_mode(),
        photon_ready=photon_configured(),
        ask_activation=setup.get("ask_activation"),
        activation_label_text=activation_label(form.get("phone_id"), form.get("carrier")),
        market_sources=MARKET_SOURCES,
        activation_json=json.dumps(_activation_map()),
    )


@app.get("/")
def index():
    view = request.args.get("view", "current")
    try:
        person = int(request.args.get("person", 0))
    except ValueError:
        person = 0
    saved = _trip_from_session()
    if saved:
        form = _form_from_request(saved)
        if request.args.get("profile") in PROFILES:
            p = PROFILES[request.args["profile"]]
            form["phone_id"] = resolve_phone_id(phone_name=p["phone"])
            phone = phone_by_id(form["phone_id"])
            form["manufacturer"] = phone["manufacturer"] if phone else form["manufacturer"]
            form["phone"] = p["phone"]
            form["phone_label"] = _phone_display_label(phone) if phone else p["phone"]
            form["carrier"] = p["carrier"]
            form["profile_id"] = request.args["profile"]
        return _render(form=form, view=view, show_plan=True, person=person)
    form = _default_form()
    if request.args.get("profile") in PROFILES:
        p = PROFILES[request.args["profile"]]
        form["phone_id"] = resolve_phone_id(phone_name=p["phone"])
        phone = phone_by_id(form["phone_id"])
        form["manufacturer"] = phone["manufacturer"] if phone else form["manufacturer"]
        form["phone"] = p["phone"]
        form["phone_label"] = _phone_display_label(phone) if phone else p["phone"]
        form["carrier"] = p["carrier"]
        form["profile_id"] = request.args["profile"]
    return _render(form=form, view=view, show_plan=False)


@app.post("/plan")
def plan():
    form = _form_from_request(request.form)
    trip_date, errors = _validate_trip(form)
    if errors:
        return _render(form=form, errors=errors, show_plan=False), 400
    _save_trip(form, trip_date)
    form["trip_date"] = trip_date.isoformat()
    return _render(form=form, show_plan=True, view=request.form.get("view", "current"))


@app.post("/share")
def share():
    form = _form_from_request(request.form)
    saved = _trip_from_session()
    if saved:
        for key in (
            "trail_id", "trip_date", "start_time", "hiker_name", "hiker_number",
            "manufacturer", "phone_id", "phone", "carrier", "satellite_activated",
        ):
            if not form.get(key) and saved.get(key):
                form[key] = saved[key]
        form["companions"] = form["companions"] or saved.get("companions", [])
    contact = form["contact"] or _normalize_phone(request.form.get("contact", ""))
    form["contact"] = contact

    errors = []
    if not form.get("hiker_name"):
        errors.append("Generate a trip plan with a hiker name before sharing.")
    if not _valid_phone(contact):
        errors.append("Enter a valid emergency contact phone number.")
    if errors:
        return _render(form=form, errors=errors, show_plan=bool(saved)), 400

    setup = _setup_for(form)
    trail = get_trail(form.get("trail_id"))
    coverage = _call_with_supported(
        get_coverage,
        trail,
        setup["profile"],
        trip_date=form.get("trip_date"),
        start_time=form.get("start_time"),
    )
    plan_text = _call_with_supported(
        share_plan,
        contact,
        trail,
        coverage,
        hiker=form["hiker_name"],
        hiker_number=form.get("hiker_number"),
    )
    _save_trip(form, date.fromisoformat(form["trip_date"]) if form.get("trip_date") else None)

    # Guardian does not call Photon send yet (Track D). Never claim SMS was sent or delivered.
    notice = (
        f"Message preview only — no SMS sent.\n"
        f"Draft for {contact}:\n{plan_text}"
    )
    return _render(form=form, notice=notice, show_plan=True)


@app.post("/simulate/missed")
def missed():
    if request.is_json:
        return {"alert": simulate_missed((request.get_json(silent=True) or {}).get("contact", ""))}

    form = _form_from_request(request.form)
    saved = _trip_from_session()
    if saved:
        for key, value in saved.items():
            form.setdefault(key, value)
        form["companions"] = form["companions"] or saved.get("companions", [])
        if not form.get("contact"):
            form["contact"] = saved.get("contact", "")

    contact = form.get("contact") or ""
    alert = simulate_missed(contact)
    notice = f"Message preview only — no SMS sent.\n{alert}"
    return _render(form=form, notice=notice, show_plan=True)


@app.post("/webhook/photon")
def photon_webhook():
    """Incoming Photon SMS. On localhost, expose this URL with a public tunnel (Track D)."""
    body = request.get_json(silent=True) or {}
    print(f"[webhook] {body}")
    reply = handle_checkin(body.get("from", ""), body.get("text", ""))
    return {"reply": reply}, 200


@app.get("/health")
def health():
    return {
        "ok": True,
        "fake_mode": fake_mode(),
        "photon": photon_configured(),
        "time": datetime.now().isoformat(timespec="seconds"),
    }


@app.get("/pitch/tmobile")
def pitch_tmobile():
    return send_from_directory(_PITCH_DIR, "tmobile.html")


@app.get("/household")
def household():
    """The group planner now lives on the main page ("Who's coming?")."""
    return redirect(url_for("index"))


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=True)
