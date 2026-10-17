"""Starward Flask app — Track C: trip inputs, map, recommendations, share flow."""
from __future__ import annotations

import inspect
import json
import os
import re
from datetime import date, datetime

import folium
from flask import Flask, render_template, request, session

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from coverage import get_coverage
from data import (
    PHONES,
    PROFILES,
    SERVICES,
    TRAILS,
    activation_label,
    carrier_options,
    get_trail,
    needs_activation_question,
    phone_by_id,
    resolve_phone_id,
    resolve_setup,
)
from data.compat import build_recommendation

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
from recommend import get_recommendation

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "starward-demo-localhost-only")

DEFAULT_PROFILE = "verizon_pixel"
DEFAULT_PHONE_ID = "pixel_9"
DEFAULT_CARRIER = "Verizon"
COLORS = {"green": "#1f9d55", "yellow": "#e0a800", "red": "#d64545"}
PHONE_RE = re.compile(r"^\+?[\d\s().-]{7,20}$")


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
    return trip_date, errors


def _setup_for(form: dict):
    return resolve_setup(
        phone_id=form.get("phone_id"),
        carrier=form.get("carrier"),
        satellite_activated=form.get("satellite_activated"),
        demo_profiles=PROFILES,
    )


def _recommendation_for(trail, setup, trip_date=None, start_time=None):
    def _rec(trail, profile, trip_date=None, start_time=None, allow_tsat_purchase=True):
        return _call_with_supported(
            get_recommendation,
            trail,
            profile,
            trip_date=trip_date,
            start_time=start_time,
            allow_tsat_purchase=allow_tsat_purchase,
        )

    return build_recommendation(
        trail, setup, _rec, trip_date=trip_date, start_time=start_time,
    )


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
        windows = ", ".join(c["windows"]) or "none expected (simulated)"
        popup = (
            f"<div style='font-family:system-ui,sans-serif;font-size:13px'><b>{c['name']}</b><br>"
            f"Expected {c['time']}<br>Demo pass windows: {windows}<br>{status}</div>"
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


def _render(form=None, notice=None, view="current", errors=None, show_plan=False):
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

    rec = _recommendation_for(trail, setup, trip_date=trip_date, start_time=start_time)
    view = view if rec.get("outcome") == "add_service" else "current"
    services = profile["services"] + ["starlink"] if view == "tsat" else None
    # Only pass known coverage services (skip pixel_sos etc.).
    if services is not None:
        services = [s for s in services if s in SERVICES]
    coverage = _call_with_supported(
        get_coverage,
        trail,
        profile,
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
        view=view,
        map_doc=_build_map(trail, coverage) if show_plan else None,
        notice=notice,
        errors=errors or [],
        show_plan=show_plan,
        fake_mode=fake_mode(),
        photon_ready=photon_configured(),
        ask_activation=setup.get("ask_activation"),
        activation_label_text=activation_label(form.get("phone_id"), form.get("carrier")),
    )


@app.get("/")
def index():
    view = request.args.get("view", "current")
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
        return _render(form=form, view=view, show_plan=True)
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


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=True)
