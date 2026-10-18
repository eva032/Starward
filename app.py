"""Starward Flask app."""
import folium
from flask import Flask, render_template, request

from coverage import get_coverage
from data import PROFILES, SERVICES, TRAIL
from guardian import handle_checkin, share_plan, simulate_missed
from recommend import get_recommendation
from guardian import handle_checkin, share_plan, simulate_missed, is_live, BRIDGE_TOKEN
app = Flask(__name__)

DEFAULT_PROFILE = "verizon_pixel"
COLORS = {"green": "#1f9d55", "yellow": "#e0a800", "red": "#d64545"}


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
    # T-Satellite "what if" preview is only offered when it's the recommended add-on.
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
        fake_mode=not is_live(),
    )


@app.get("/")
def index():
    return _render(request.args.get("profile", DEFAULT_PROFILE), view=request.args.get("view", "current"))


@app.post("/share")
def share():
    profile_id = request.form.get("profile", DEFAULT_PROFILE)
    contact = request.form.get("contact", "").strip()
    hiker_name = request.form.get("hiker_name", "").strip() or "Sam"
    hiker_phone = request.form.get("hiker_phone", "").strip()
    trip_date = request.form.get("trip_date", "").strip() or None
    start_time = request.form.get("start_time", "").strip() or None

    profile = PROFILES.get(profile_id, PROFILES[DEFAULT_PROFILE])
    coverage = get_coverage(TRAIL, profile, trip_date=trip_date, start_time=start_time)

    share_plan(contact, TRAIL, coverage, hiker=hiker_name, hiker_number=hiker_phone)

    mode = "" if is_live() else " (fake)"
    return _render(profile_id, notice=f"Plan sent to {contact}{mode}")


@app.post("/simulate/missed")
def missed():
    if request.is_json:
        return {"alert": simulate_missed((request.get_json(silent=True) or {}).get("contact", ""))}
    alert = simulate_missed(request.form.get("contact", ""))
    return _render(request.form.get("profile", DEFAULT_PROFILE), notice=f"Alert drafted (fake, not sent):\n{alert}")

@app.get("/health")
def health():
    return "ok"

@app.post("/webhook/photon")
def photon_webhook():
    if BRIDGE_TOKEN and request.headers.get("authorization") != f"Bearer {BRIDGE_TOKEN}":
        return "", 401
    data = request.get_json(silent=True) or {}
    handle_checkin(data.get("from", ""), data.get("text", ""))
    return "", 200

if __name__ == "__main__":
    app.run(port=5000, debug=True)
