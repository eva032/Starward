"""Guardian: shares the plan, records check-ins, and sends missed-check-in alerts.

Live mode texts through the Photon bridge when BRIDGE_URL is set.
Demo mode (no BRIDGE_URL) prints instead and returns previews for the UI.
"""
from datetime import datetime
import os
import re

import requests

BRIDGE_URL = os.getenv("BRIDGE_URL", "").rstrip("/")
BRIDGE_TOKEN = os.getenv("BRIDGE_TOKEN", "")

DEFAULT_HIKER = "Sam"

# In-memory plans keyed by normalized contact number. Lost on restart.
PLANS = {}
# Normalized hiker number -> normalized contact number.
HIKER_TO_CONTACT = {}
_latest_contact = None


def is_live():
    """True when real texts are on. Use this for the Demo Mode badge."""
    return bool(BRIDGE_URL)


def photon_configured():
    """Backward-compatible alias for is_live()."""
    return is_live()


def normalize(number):
    digits = re.sub(r"\D", "", number or "")
    if len(digits) == 10:
        digits = "1" + digits
    return f"+{digits}" if digits else ""


def send_sms(to, text):
    """Send a text through the bridge. Prints instead when there is no bridge."""
    to = normalize(to)
    if not is_live():
        print(f"[guardian] (fake) would send to {to or 'unknown'}:\n{text}")
        return False
    if not to:
        print("[guardian] no recipient number, not sending")
        return False
    try:
        r = requests.post(
            f"{BRIDGE_URL}/send",
            json={"to": to, "text": text},
            headers={"authorization": f"Bearer {BRIDGE_TOKEN}"},
            timeout=10,
        )
        if not r.ok:
            print(f"[guardian] send to {to} failed: {r.status_code} {r.text}")
        return r.ok
    except requests.RequestException as e:
        print(f"[guardian] send to {to} failed: {e}")
        return False


def _now():
    return datetime.now().strftime("%I:%M%p").lstrip("0").lower()


def _find_plan(number):
    n = normalize(number)
    plan = PLANS.get(HIKER_TO_CONTACT.get(n)) or PLANS.get(n)
    if plan:
        return plan
    # Demo shortcut: one hiker at a time, fall back to the latest plan.
    if not is_live():
        return PLANS.get(_latest_contact)
    return None


def share_plan(contact_number, trail, coverage, hiker=DEFAULT_HIKER, hiker_number=None):
    """Share a trip plan with an emergency contact.

    hiker_number is optional; when set, check-ins from that number can match this plan.
    Without BRIDGE_URL, nothing is sent — text is printed and returned for the UI.
    """
    global _latest_contact
    contact = normalize(contact_number)
    hiker_num = normalize(hiker_number)
    trip_date = coverage.get("trip_date")
    start_line = f"Start: {coverage['start_time']} at the trailhead."
    if trip_date:
        start_line = f"Date: {trip_date}. {start_line}"
    lines = [
        f"Starward trip plan: {hiker} is hiking {trail['name']}.",
        start_line,
        "Check-ins (best-chance estimates, not guaranteed):",
    ]
    for c in coverage["checkins"]:
        note = "" if c["covered"] else " (low chance of signal; a skipped text here is expected)"
        lines.append(f"- {c['name']} around {c['time']}{note}")
    lines += [
        f"{hiker} will text OK to the Starward number at each spot. Satellite texts can arrive late.",
        "If a check-in is missed, Starward will text you. If you're worried, "
        "contact local emergency services or search and rescue. "
        "Starward never contacts emergency services automatically.",
    ]
    text = "\n".join(lines)
    PLANS[contact] = {
        "hiker": hiker,
        "hiker_number": hiker_num,
        "contact": contact,
        "trail": trail,
        "coverage": coverage,
        "next": 0,
        "text": text,
        "simulated": not is_live(),
    }
    if hiker_num:
        HIKER_TO_CONTACT[hiker_num] = contact
    _latest_contact = contact

    send_sms(contact, text)
    if hiker_num:
        send_sms(
            hiker_num,
            "Starward: text OK to this number at each check-in spot. "
            "That is all you need to do.",
        )
    return text


def handle_checkin(from_number, text):
    if not re.sub(r"[^A-Za-z]", "", text or "").upper().startswith("OK"):
        return "Reply OK to check in."
    plan = _find_plan(from_number)
    if not plan:
        return "No active trip plan found. Share a plan first."
    checkins = plan["coverage"]["checkins"]
    if plan["next"] >= len(checkins):
        return f"{plan['hiker']} has already checked in at every spot."
    c = checkins[plan["next"]]
    plan["next"] += 1
    reply = f"{plan['hiker']} checked in at {c['name']}, {_now()}"
    send_sms(plan["contact"], reply)
    print(f"[guardian] {reply} (from {from_number})")
    return reply


def simulate_missed(contact):
    """Send (or preview) the alert to the contact. Never contacts emergency services itself."""
    plan = _find_plan(contact)
    if not plan:
        return "No active trip plan found. Share a plan first."
    checkins = plan["coverage"]["checkins"]
    if plan["next"] >= len(checkins):
        return f"{plan['hiker']} has already checked in at every spot."
    missed = checkins[plan["next"]]
    if plan["next"] > 0:
        last = checkins[plan["next"] - 1]["name"]
    else:
        last = f"none yet (started at the trailhead around {plan['coverage']['start_time']})"
    after = checkins[plan["next"] + 1] if plan["next"] + 1 < len(checkins) else None
    next_spot = f"{after['name']} around {after['time']}" if after else f"the end of the {plan['trail']['name']} route"
    text = "\n".join([
        f"Starward alert: {plan['hiker']} hasn't checked in at {missed['name']} (expected around {missed['time']}).",
        f"Last check-in: {last}.",
        f"Route: {plan['trail']['name']} trail.",
        f"Next expected spot: {next_spot}.",
        "Satellite texts are often late, so this may not be an emergency.",
        "If you're worried, contact local emergency services or search and rescue.",
    ])
    send_sms(plan["contact"], text)
    return text
