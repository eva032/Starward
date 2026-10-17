"""Starward Flask app."""
import os
from pathlib import Path

import folium
from flask import Flask, redirect, render_template, request, send_from_directory, session, url_for

from coverage import get_coverage, start_time_for_input, trip_month_label
from data import (
    CARRIER_CHOICES,
    HOUSEHOLDS,
    LINES,
    PHONE_CHOICES,
    PROFILES,
    SATELLITE_CHOICES,
    SERVICES,
    TRAIL,
    build_custom_line,
    empty_custom_household,
    line_as_profile,
)
from guardian import handle_checkin, share_plan, simulate_missed
from recommend import get_household_recommendation, get_recommendation

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "starward-dev-only-change-me")
_PITCH_DIR = Path(__file__).resolve().parent / "pitch"

DEFAULT_PROFILE = "verizon_pixel"
DEFAULT_HOUSEHOLD = "chen_family"
COLORS = {"green": "#1f9d55", "yellow": "#e0a800", "red": "#d64545"}
MAX_TRAVELERS = 6


def _build_map(coverage):
    points = TRAIL["points"]
    m = folium.Map(tiles="OpenTopoMap", control_scale=True)
    m.fit_bounds([[min(p["lat"] for p in points), min(p["lon"] for p in points)],
                  [max(p["lat"] for p in points), max(p["lon"] for p in points)]], padding=(40, 40))

    segs = coverage["segments"]
    folium.PolyLine([(s["lat"], s["lon"]) for s in segs], color="#ffffff", weight=11, opacity=0.9).add_to(m)
    for a, b in zip(segs, segs[1:]):
        folium.PolyLine(
            [(a["lat"], a["lon"]), (b["lat"], b["lon"])],
            color=COLORS[a["color"]], weight=6, opacity=0.95,
            tooltip=f"Sky openness {a['openness']:.2f} (estimate)",
        ).add_to(m)

    for i, c in enumerate(coverage["checkins"], 1):
        status = "Covered (estimate)" if c["covered"] else "Not covered (estimate)"
        windows = ", ".join(c["windows"]) or "none expected"
        popup = (f"<div style='font-family:system-ui,sans-serif;font-size:13px'><b>{c['name']}</b><br>"
                 f"Expected {c['time']}<br>Best-chance windows: {windows}<br>{status}</div>")
        badge = (f"<div style='width:26px;height:26px;border-radius:50%;background:{COLORS[c['color']]};"
                 f"color:#fff;border:3px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.35);display:flex;"
                 f"align-items:center;justify-content:center;font:700 13px system-ui,sans-serif'>{i}</div>")
        folium.Marker((c["lat"], c["lon"]), popup=folium.Popup(popup, max_width=260), tooltip=c["name"],
                      icon=folium.DivIcon(html=badge, icon_size=(32, 32), icon_anchor=(16, 16))).add_to(m)

    return m.get_root().render()


def _render(profile_id, notice=None, view="current"):
    if profile_id not in PROFILES:
        profile_id = DEFAULT_PROFILE
    profile = PROFILES[profile_id]
    rec = get_recommendation(TRAIL, profile)
    view = view if rec["outcome"] == "add_service" else "current"
    services = profile["services"] + ["starlink"] if view == "tsat" else None
    coverage = get_coverage(TRAIL, profile, services=services)
    return render_template(
        "index.html",
        trail=TRAIL,
        profiles=PROFILES,
        services=SERVICES,
        profile_id=profile_id,
        profile=profile,
        coverage=coverage,
        rec=rec,
        view=view,
        map_doc=_build_map(coverage),
        notice=notice,
    )


def _parse_custom_form(form):
    trip_date = (form.get("trip_date") or "").strip()
    start_time = (form.get("start_time") or "09:00").strip() or "09:00"
    trip_month = (form.get("trip_month") or "").strip()
    if not trip_month:
        trip_month = trip_month_label(trip_date, "this trip")
    names = form.getlist("display_name")
    phones = form.getlist("phone")
    carriers = form.getlist("carrier")
    plans = form.getlist("plan")
    sats = form.getlist("satellite")
    months = form.getlist("financing_months_left")
    balances = form.getlist("financing_balance_usd")
    n = max(len(names), len(phones), 1)
    lines = []
    for i in range(min(n, MAX_TRAVELERS)):
        lines.append(build_custom_line(
            i,
            names[i] if i < len(names) else "",
            phones[i] if i < len(phones) else PHONE_CHOICES[2],
            carriers[i] if i < len(carriers) else CARRIER_CHOICES[0],
            plans[i] if i < len(plans) else "My plan",
            sats[i] if i < len(sats) else "none",
            months[i] if i < len(months) else 0,
            balances[i] if i < len(balances) else 0,
        ))
    if not lines:
        return empty_custom_household(trip_month, trip_date, start_time)
    return {
        "id": "custom",
        "name": "Your group",
        "summary": f"{len(lines)} traveler{'s' if len(lines) != 1 else ''} you entered.",
        "carrier_home": "Mixed" if len({l['carrier'] for l in lines}) > 1 else lines[0]["carrier"],
        "trip_month": trip_month,
        "trip_date": trip_date,
        "start_time": start_time,
        "custom": True,
        "lines": lines,
    }


def _custom_household():
    hh = session.get("custom_household")
    if not hh or not hh.get("lines"):
        hh = empty_custom_household()
        session["custom_household"] = hh
        return hh
    # Migrate older sessions that predate trip fields.
    hh.setdefault("trip_date", "")
    hh.setdefault("start_time", "09:00")
    hh.setdefault("trip_month", trip_month_label(hh.get("trip_date"), "this trip"))
    session["custom_household"] = hh
    return hh


def _render_household(mode, household_id=None, view="current", traveler=None, notice=None,
                      trip_date=None, start_time=None):
    if mode == "custom":
        hh = _custom_household()
        hh["start_time"] = start_time_for_input(hh.get("start_time"), "09:00")
        rec = get_household_recommendation(TRAIL, household=hh)
        household_id = "custom"
        lines_by_id = {line["id"]: line for line in hh["lines"]}
        traveler_ids = [line["id"] for line in hh["lines"]]
    else:
        mode = "demo"
        if household_id not in HOUSEHOLDS:
            household_id = DEFAULT_HOUSEHOLD
        demo = HOUSEHOLDS[household_id]
        raw_start = start_time or demo.get("start_time") or TRAIL.get("start_time") or "09:00"
        hh = {
            **demo,
            "lines": [LINES[t] for t in demo["travelers"] if t in LINES],
            "trip_date": trip_date or demo.get("trip_date", ""),
            "start_time": start_time_for_input(raw_start, "09:00"),
        }
        hh["trip_month"] = trip_month_label(hh.get("trip_date"), demo.get("trip_month", "this trip"))
        rec = get_household_recommendation(TRAIL, household=hh)
        lines_by_id = {line["id"]: line for line in hh["lines"]}
        traveler_ids = list(lines_by_id)

    focus_id = next(
        (r["line_id"] for r in rec["recommendations"] if r.get("kind") == "addon" and r.get("line_id")),
        traveler_ids[0],
    )
    if traveler in traveler_ids:
        focus_id = traveler
    elif focus_id not in traveler_ids:
        focus_id = traveler_ids[0]

    focus_line = lines_by_id[focus_id]
    focus_profile = line_as_profile(focus_line)
    can_preview = any(r.get("line_id") == focus_id and r.get("kind") == "addon" for r in rec["recommendations"])
    view = view if can_preview and view == "tsat" else "current"
    services = focus_profile["services"] + ["starlink"] if view == "tsat" else None
    coverage = get_coverage(
        TRAIL, focus_profile, services=services,
        trip_date=hh.get("trip_date"),
        start_time=hh.get("start_time"),
    )
    primary = next((r for r in rec["recommendations"] if r["kind"] == "addon"), None)
    if primary is None:
        primary = rec["recommendations"][0] if rec["recommendations"] else None
    extras = [r for r in rec["recommendations"] if r is not primary]

    # Satellite choice for each custom line (for form defaults)
    sat_by_line = {}
    for line in hh["lines"]:
        services = line.get("services") or []
        sat_by_line[line["id"]] = services[0] if services else "none"

    return render_template(
        "household.html",
        trail=TRAIL,
        households=HOUSEHOLDS,
        household_id=household_id,
        hh=hh,
        rec=rec,
        primary=primary,
        extras=extras,
        focus_id=focus_id,
        focus_line=focus_line,
        coverage=coverage,
        map_doc=_build_map(coverage),
        view=view,
        can_preview=can_preview,
        mode=mode,
        notice=notice,
        phone_choices=PHONE_CHOICES,
        carrier_choices=CARRIER_CHOICES,
        satellite_choices=SATELLITE_CHOICES,
        sat_by_line=sat_by_line,
        max_travelers=MAX_TRAVELERS,
        start_time_value=start_time_for_input(hh.get("start_time"), "09:00"),
    )


@app.get("/")
def index():
    return _render(request.args.get("profile", DEFAULT_PROFILE), view=request.args.get("view", "current"))


@app.post("/share")
def share():
    profile_id = request.form.get("profile", DEFAULT_PROFILE)
    contact = request.form.get("contact", "").strip()
    profile = PROFILES.get(profile_id, PROFILES[DEFAULT_PROFILE])
    share_plan(contact, TRAIL, get_coverage(TRAIL, profile))
    return _render(profile_id, notice=f"Plan sent to {contact} (fake)")


@app.post("/simulate/missed")
def missed():
    if request.is_json:
        return {"alert": simulate_missed((request.get_json(silent=True) or {}).get("contact", ""))}
    alert = simulate_missed(request.form.get("contact", ""))
    return _render(request.form.get("profile", DEFAULT_PROFILE), notice=f"Alert drafted (fake, not sent):\n{alert}")


@app.post("/webhook/photon")
def photon_webhook():
    body = request.get_json(silent=True) or {}
    print(f"[webhook] {body}")
    reply = handle_checkin(body.get("from", ""), body.get("text", ""))
    return {"reply": reply}, 200


@app.get("/health")
def health():
    return "ok"


@app.get("/pitch/tmobile")
def pitch_tmobile():
    return send_from_directory(_PITCH_DIR, "tmobile.html")


@app.get("/household")
def household():
    # Prefer the personalized builder; demo families stay one click away.
    mode = request.args.get("mode", "custom")
    return _render_household(
        mode=mode,
        household_id=request.args.get("id", DEFAULT_HOUSEHOLD),
        view=request.args.get("view", "current"),
        traveler=request.args.get("traveler"),
        trip_date=request.args.get("trip_date"),
        start_time=request.args.get("start_time"),
    )


@app.post("/household")
def household_save():
    """Save a user-built household (session) or switch back to a demo family."""
    mode = request.form.get("mode", "custom")
    if mode == "demo":
        session.pop("custom_household", None)
        return redirect(url_for("household", mode="demo", id=request.form.get("id", DEFAULT_HOUSEHOLD)))

    action = request.form.get("action", "save")
    hh = _parse_custom_form(request.form)
    hh["start_time"] = start_time_for_input(hh.get("start_time"), "09:00")

    if action == "add" and len(hh["lines"]) < MAX_TRAVELERS:
        hh["lines"].append(build_custom_line(
            len(hh["lines"]), "", "Pixel 9", "Verizon", "My plan", "skylo",
        ))
        hh["summary"] = f"{len(hh['lines'])} travelers you entered."
    elif action == "remove":
        try:
            idx = int(request.form.get("remove_index", -1))
        except ValueError:
            idx = -1
        if 0 <= idx < len(hh["lines"]) and len(hh["lines"]) > 1:
            hh["lines"].pop(idx)
            # Re-id lines so indexes stay stable.
            hh["lines"] = [
                build_custom_line(
                    i, line["display_name"], line["phone"], line["carrier"],
                    line.get("plan", "My plan"),
                    (line.get("services") or ["none"])[0] if line.get("services") else "none",
                    line.get("financing_months_left", 0),
                    line.get("financing_balance_usd", 0),
                )
                for i, line in enumerate(hh["lines"])
            ]
            hh["summary"] = f"{len(hh['lines'])} traveler{'s' if len(hh['lines']) != 1 else ''} you entered."

    session["custom_household"] = hh
    return redirect(url_for("household", mode="custom", traveler=request.form.get("traveler")))


if __name__ == "__main__":
    app.run(port=5000, debug=True)
