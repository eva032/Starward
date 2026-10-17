# TODO(B): load real carriers.json catalog + prices
"""Recommendation engine: covered, add_service, or not_compatible."""
from coverage import get_coverage
from data import CATALOG_AS_OF, SERVICES


def _count(coverage):
    return sum(1 for c in coverage["checkins"] if c["covered"])


def _short(checkin):
    return "the " + checkin["name"].split(": ", 1)[-1].lower()


def _service_names(services):
    return " and ".join(SERVICES[s]["name"] for s in services)


def get_recommendation(trail, profile):
    current = get_coverage(trail, profile)
    total = len(current["checkins"])
    covered = _count(current)
    services = profile["services"]
    phone = profile["phone"]
    rec = {"as_of": CATALOG_AS_OF, "current_covered": covered, "total": total}

    if services and covered == total:
        included = " (already in your plan)" if "starlink" in services else ""
        return {**rec, "outcome": "covered", "best_covered": covered,
                "headline": "You're set. Don't buy anything for this trip.",
                "options": [{
                    "action": "Keep your current setup", "cost": "$0",
                    "checkins_covered": covered, "total": total,
                    "reason": f"Your {phone} uses {_service_names(services)}{included}. "
                              f"Our estimate gives you a good chance to text at all {total} check-ins.",
                }]}

    if profile["tsat_compatible"] and "starlink" not in services:
        boosted = get_coverage(trail, profile, services=services + ["starlink"])
        with_tsat = _count(boosted)
        if with_tsat > covered:
            gaps = [c for c, b in zip(current["checkins"], boosted["checkins"])
                    if not c["covered"] and b["covered"]]
            blocked = [s for s in services if SERVICES[s]["blocked_by_south_ridge"]]
            if blocked:
                sat = SERVICES[blocked[0]]["constellation"]
                why = (f"Your {phone} uses {sat}, which sits low in the southern sky; the ridge near "
                       f"{_short(gaps[0])} blocks it. Starlink satellites pass overhead, so you get a better chance there.")
            elif services:
                why = f"Starlink adds passes overhead, which gives you a better chance at {_short(gaps[0])}."
            else:
                why = "Your phone has no satellite texting turned on yet. T-Satellite adds it for this trip."
            options = [{
                "action": "Add T-Satellite for the trip month only", "cost": "$10 once",
                "checkins_covered": with_tsat, "total": total,
                "reason": why + " We'll remind you to turn it off after the trip.",
            }]
            if profile["household_lines"] > 1:
                options.append({
                    "action": "Add it for family members coming with you", "cost": "$10 per line",
                    "checkins_covered": with_tsat, "total": total,
                    "reason": "Only for people on your plan who'll be on this hike. Skip it for anyone staying home.",
                })
            missed = [c for c in current["checkins"] if not c["covered"]]
            options.append({
                "action": "Keep your current setup", "cost": "$0",
                "checkins_covered": covered, "total": total,
                "reason": f"No extra cost, but our estimate shows little or no signal at "
                          f"{', '.join(_short(c) for c in missed)}. Your contact may see a missed check-in "
                          f"there that isn't an emergency.",
            })
            return {**rec, "outcome": "add_service", "best_covered": with_tsat,
                    "headline": (f"A $10 add-on covers every check-in." if with_tsat == total
                                 else f"A $10 add-on covers {with_tsat} of {total} check-ins."),
                    "options": options}

    cell = " and ".join(trail["cell_spots"])
    headline = ("No add-on will help on this phone." if not profile["tsat_compatible"]
                else "No add-on will help on this route.")
    return {**rec, "outcome": "not_compatible", "best_covered": covered,
            "headline": headline,
            "options": [
                {"action": "Plan check-ins where you'll have regular cell signal", "cost": "$0",
                 "checkins_covered": None, "total": total,
                 "reason": f"You should have regular signal at the {cell}. Tell your contact to expect "
                           f"texts from those two spots and silence in between."},
                {"action": "Consider a dedicated satellite messenger", "cost": "About $200–$400 + subscription (estimate)",
                 "checkins_covered": None, "total": total,
                 "reason": "A separate device works with the phone you have. Worth it only if you often hike out of signal."},
            ]}
