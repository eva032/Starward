# TODO(D): send/receive via Photon 2.0
"""Fake guardian: shares the plan, records check-ins, and drafts missed-check-in alerts."""
from datetime import datetime

DEFAULT_HIKER = "Sam"

# In-memory plans keyed by contact number. Lost on restart.
PLANS = {}
_latest_contact = None


def _now():
    return datetime.now().strftime("%I:%M%p").lstrip("0").lower()


def _find_plan(number):
    # Demo shortcut: one hiker at a time, so fall back to the most recent plan.
    return PLANS.get(number) or PLANS.get(_latest_contact)


def share_plan(contact_number, trail, coverage, hiker=DEFAULT_HIKER):
    global _latest_contact
    lines = [
        f"Starward trip plan: {hiker} is hiking {trail['name']}.",
        f"Start: {coverage['start_time']} at the trailhead.",
        "Check-ins (best-chance estimates, not guaranteed):",
    ]
    for c in coverage["checkins"]:
        note = "" if c["covered"] else " (low chance of signal; a skipped text here is expected)"
        lines.append(f"- {c['name']} around {c['time']}{note}")
    lines += [
        f"{hiker} will text OK at each spot. Satellite texts can arrive late.",
        "If a check-in is missed, Starward will text you. If you're worried, "
        "contact local emergency services or search and rescue.",
    ]
    text = "\n".join(lines)
    PLANS[contact_number] = {"hiker": hiker, "trail": trail, "coverage": coverage, "next": 0, "text": text}
    _latest_contact = contact_number
    print(f"[guardian] would send to {contact_number}:\n{text}")
    return text


def handle_checkin(from_number, text):
    if not text.strip().upper().startswith("OK"):
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
    print(f"[guardian] {reply} (from {from_number})")
    return reply


def simulate_missed(contact):
    """Draft the alert sent to the contact. Never contacts emergency services itself."""
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
    print(f"[guardian] missed check-in alert for {contact or 'latest contact'}:\n{text}")
    return text
