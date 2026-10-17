"""Recommendation engine: per-phone outcomes plus household Mix / Timekeeper / cart."""
from coverage import get_coverage, trip_month_label
from data import (
    ADDONS,
    CATALOG_AS_OF,
    DEVICES,
    PRICE_SOURCE_URL,
    SERVICES,
    TRADEIN_CURVES,
    get_household,
    is_tsat_compatible,
    line_as_profile,
)

# A check-in counts as group-covered when at least this many travelers can reach it.
# Solo / duo trips use 1; larger groups ask for a second phone (redundancy).
def _redundancy(n_travelers):
    return 2 if n_travelers >= 3 else 1


TSAT_USD = ADDONS["tsatellite"]["cost_usd"]
# Naive upsell: mid-range new phone + T-Satellite on every traveler for a year of months (demo figure).
NAIVE_PHONE_USD = 800
NAIVE_ADDON_MONTHS = 12


def _count(coverage):
    return sum(1 for c in coverage["checkins"] if c["covered"])


def _short(checkin):
    return "the " + checkin["name"].split(": ", 1)[-1].lower()


def _service_names(services):
    return " and ".join(SERVICES[s]["name"] for s in services)


def get_recommendation(trail, profile):
    """Per-phone recommendation. Contract unchanged; extra fields are additive."""
    current = get_coverage(trail, profile)
    total = len(current["checkins"])
    covered = _count(current)
    services = profile["services"]
    phone = profile["phone"]
    tsat_ok = profile.get("tsat_compatible", is_tsat_compatible(phone))
    tsat_cost = SERVICES["starlink"]["cost"]
    rec = {
        "as_of": CATALOG_AS_OF,
        "source_url": PRICE_SOURCE_URL,
        "current_covered": covered,
        "total": total,
    }

    if services and covered == total:
        if "starlink" in services:
            why = (f"Your {phone} already includes T-Satellite on your plan. "
                   f"Our estimate gives you a good chance to text at all {total} check-ins—no add-on needed.")
        else:
            why = (f"Your {phone} uses {_service_names(services)}. "
                   f"Our estimate gives you a good chance to text at all {total} check-ins on this route—"
                   f"so we won't recommend buying anything.")
        return {**rec, "outcome": "covered", "best_covered": covered,
                "headline": "You're set. Don't buy anything for this trip.",
                "options": [{
                    "action": "Keep your current setup", "cost": "$0",
                    "checkins_covered": covered, "total": total,
                    "reason": why,
                }]}

    if tsat_ok and "starlink" not in services:
        boosted = get_coverage(trail, profile, services=services + ["starlink"])
        with_tsat = _count(boosted)
        if with_tsat > covered:
            gaps = [c for c, b in zip(current["checkins"], boosted["checkins"])
                    if not c["covered"] and b["covered"]]
            blocked = [s for s in services if SERVICES[s]["blocked_by_south_ridge"]]
            if blocked:
                sat = SERVICES[blocked[0]]["constellation"]
                why = (f"Your {phone}'s {sat} link sits low in the southern sky. Near "
                       f"{_short(gaps[0])}, a ridge blocks that view—so our estimate shows a weak chance "
                       f"with your current setup. T-Satellite uses Starlink passes overhead, which gives "
                       f"you a better chance at those spots.")
            elif services:
                why = (f"Adding T-Satellite adds Starlink passes overhead, which our estimate says "
                       f"improves your chance at {_short(gaps[0])}.")
            else:
                why = (f"Your {phone} can use T-Satellite, but satellite texting isn't on yet. "
                       f"Turning it on for this trip gives you a better chance at the check-ins.")
            options = [{
                "action": "Add T-Satellite for the trip month only", "cost": tsat_cost,
                "checkins_covered": with_tsat, "total": total,
                "reason": why + f" It's {tsat_cost} per line—cancel in T-Life after the trip so you "
                          f"only pay for the month you need.",
            }]
            if profile.get("household_lines", 1) > 1:
                options.append({
                    "action": "Add it only for people on this hike",
                    "cost": f"{tsat_cost} per line",
                    "checkins_covered": with_tsat, "total": total,
                    "reason": "Skip lines for anyone staying home. Only add it for hikers who'll need "
                              "the check-in texts.",
                })
            missed = [c for c in current["checkins"] if not c["covered"]]
            options.append({
                "action": "Keep your current setup", "cost": "$0",
                "checkins_covered": covered, "total": total,
                "reason": f"Saves the add-on, but our estimate shows little or no signal at "
                          f"{', '.join(_short(c) for c in missed)}. Your contact may get a missed "
                          f"check-in alert there even when you're fine.",
            })
            return {**rec, "outcome": "add_service", "best_covered": with_tsat,
                    "headline": (f"A $10 add-on covers every check-in." if with_tsat == total
                                 else f"A $10 add-on covers {with_tsat} of {total} check-ins."),
                    "options": options}

    cell = " and ".join(trail["cell_spots"])
    if not tsat_ok:
        headline = "No add-on will help on this phone."
        phone_note = (f"T-Satellite isn't available on the {phone}, and we won't suggest buying a "
                      f"new phone for one hike.")
    else:
        headline = "No add-on will help on this route."
        phone_note = "An add-on wouldn't improve check-in coverage on this trail with your setup."
    return {**rec, "outcome": "not_compatible", "best_covered": covered,
            "headline": headline,
            "options": [
                {"action": "Plan check-ins where you'll have regular cell signal", "cost": "$0",
                 "checkins_covered": None, "total": total,
                 "reason": f"{phone_note} You should have regular cell signal at the {cell}. "
                           f"Tell your contact to expect texts from those spots and silence in between."},
                {"action": "Consider a dedicated satellite messenger", "cost": "About $200–$400 + subscription (estimate)",
                 "checkins_covered": None, "total": total,
                 "reason": "A separate messenger works with the phone you already have. Only worth it if "
                           "you often hike beyond cell coverage—not something we'd push for a single trip."},
            ]}


def _tradein_at(device_id, months):
    curve = TRADEIN_CURVES.get(device_id) or {}
    if not curve:
        return 0
    keys = sorted(int(k) for k in curve)
    if months <= keys[0]:
        return curve[str(keys[0])]
    if months >= keys[-1]:
        return curve[str(keys[-1])]
    lo = max(k for k in keys if k <= months)
    hi = min(k for k in keys if k >= months)
    if lo == hi:
        return curve[str(lo)]
    frac = (months - lo) / (hi - lo)
    return round(curve[str(lo)] * (1 - frac) + curve[str(hi)] * frac)


def cost_now_vs_later(line):
    """Timekeeper: compare upgrading now vs waiting until financing payoff. Never required for the trip."""
    device_id = line.get("device_id")
    device = DEVICES.get(device_id) or {}
    upgrade_id = device.get("upgrade_phone")
    upgrade = DEVICES.get(upgrade_id) if upgrade_id else None
    months_left = int(line.get("financing_months_left") or 0)
    balance = float(line.get("financing_balance_usd") or 0)
    trade_now = _tradein_at(device_id, 0)
    trade_later = _tradein_at(device_id, months_left)

    if not upgrade:
        return {
            "applicable": False,
            "verdict": "n/a",
            "reason": "No upgrade path in the synthetic catalog for this device.",
            "chart": {"labels": [], "upgrade_now": [], "upgrade_later": []},
        }

    retail = float(upgrade["retail_usd"])
    cost_now = round(retail - trade_now + balance)
    cost_later = round(retail - trade_later)
    # Honest default: wait whenever there is remaining financing and waiting isn't wildly worse.
    verdict = "wait" if months_left > 0 and cost_later <= cost_now + 50 else "optional_later"
    labels, now_series, later_series = [], [], []
    for m in range(0, max(months_left, 1) + 1):
        labels.append(f"M{m}")
        t = _tradein_at(device_id, m)
        # Remaining balance declines roughly linearly for the chart.
        rem = max(0, balance * (1 - m / months_left)) if months_left else 0
        now_series.append(round(retail - t + rem))
        later_series.append(round(retail - _tradein_at(device_id, months_left)))

    who = line.get("display_name", line.get("phone"))
    if verdict == "wait":
        reason = (f"{who}: two paths—upgrade now (~${cost_now} after paying off ${int(balance)} "
                  f"and trading in) or wait ~{months_left} months to payoff (~${cost_later}). "
                  f"For this trip, wait. Others on the hike can cover check-ins.")
    else:
        reason = (f"{who}: financing is clear, but a new phone still isn't the cheapest fix for one hike. "
                  f"Revisit later if you wanted an upgrade anyway (~${cost_later} after trade-in).")

    return {
        "applicable": True,
        "verdict": verdict,
        "line_id": line["id"],
        "display_name": who,
        "months_left": months_left,
        "balance_usd": balance,
        "tradein_now_usd": trade_now,
        "tradein_at_payoff_usd": trade_later,
        "upgrade_model": upgrade["model"],
        "cost_now_usd": cost_now,
        "cost_later_usd": cost_later,
        "reason": reason,
        "chart": {
            "labels": labels,
            "upgrade_now": now_series,
            "upgrade_later": later_series,
        },
    }


def _trip_kwargs(household=None, trail=None):
    hh = household or {}
    return {
        "trip_date": hh.get("trip_date") or (trail or {}).get("trip_date"),
        "start_time": hh.get("start_time") or (trail or {}).get("start_time"),
    }


def _line_coverage(trail, line, services=None, household=None):
    profile = line_as_profile(line)
    return get_coverage(trail, profile, services=services, **_trip_kwargs(household, trail))


def get_household_recommendation(trail, household_id=None, household=None):
    """
    Household Mix + Timekeeper + Cart Whisperer.
    Finds the cheapest setup so the group can reach help at every check-in (estimate).
    Pass household_id for a demo family, or household= for a user-built group.
    """
    hh = household if household is not None else get_household(household_id)
    if not hh:
        return None

    lines = hh.get("lines") or []
    if not lines:
        return None
    n = len(lines)
    need = _redundancy(n)
    trip_month = trip_month_label(
        hh.get("trip_date"),
        hh.get("trip_month") or "the trip month",
    )

    per_line = []
    cover_matrix = []  # cover_matrix[line_idx][checkin_idx] -> bool
    checkins = None
    for line in lines:
        cov = _line_coverage(trail, line, household=hh)
        if checkins is None:
            checkins = cov["checkins"]
        flags = [c["covered"] for c in cov["checkins"]]
        cover_matrix.append(flags)
        per_line.append({
            "line_id": line["id"],
            "display_name": line["display_name"],
            "phone": line["phone"],
            "carrier": line["carrier"],
            "services": list(line.get("services") or []),
            "covered": sum(flags),
            "total": len(flags),
            "tsat_compatible": is_tsat_compatible(line["phone"]),
            "checkins": flags,
        })

    total = len(checkins)
    group_covered = [
        sum(cover_matrix[li][ci] for li in range(n)) >= need
        for ci in range(total)
    ]

    recommendations = []
    timing = []
    # Working copy of who covers what after proposed add-ons.
    effective = [row[:] for row in cover_matrix]

    def group_ok(matrix):
        return all(sum(matrix[li][ci] for li in range(n)) >= need for ci in range(total))

    # Step 1: already covered by phones the group has?
    if group_ok(effective):
        recommendations.append({
            "line_id": None,
            "display_name": "Everyone",
            "action": "You're covered. Buy nothing.",
            "kind": "nothing",
            "cost_usd": 0,
            "cost": "$0",
            "reason": (f"With at least {need} reachable phone(s) at every check-in (estimate), "
                       f"this household doesn't need an add-on or upgrade for {trail['name']}."),
        })
    else:
        # Step 2: cheapest add-ons — try one line at a time, pick the $10 fixes that close gaps.
        candidates = []
        for i, line in enumerate(lines):
            if "starlink" in (line.get("services") or []):
                continue
            if not is_tsat_compatible(line["phone"]):
                continue
            boosted = _line_coverage(
                trail, line,
                services=list(line.get("services") or []) + ["starlink"],
                household=hh,
            )
            boost_flags = [c["covered"] for c in boosted["checkins"]]
            # Does this line newly cover any currently under-covered check-in?
            gain = 0
            trial = [row[:] for row in effective]
            trial[i] = boost_flags
            before = sum(1 for ci in range(total) if sum(effective[li][ci] for li in range(n)) >= need)
            after = sum(1 for ci in range(total) if sum(trial[li][ci] for li in range(n)) >= need)
            gain = after - before
            if gain > 0 or (not group_ok(effective) and _count(boosted) > per_line[i]["covered"]):
                gaps = [checkins[ci]["name"] for ci in range(total)
                        if sum(effective[li][ci] for li in range(n)) < need and boost_flags[ci]]
                candidates.append((TSAT_USD, -gain, i, boost_flags, gaps))

        candidates.sort()  # cheapest first, then most gain
        for cost, neg_gain, i, boost_flags, gaps in candidates:
            if group_ok(effective):
                break
            line = lines[i]
            effective[i] = boost_flags
            gap_names = ["the " + g.split(": ", 1)[-1].lower() for g in gaps[:2]]
            gap_txt = ", ".join(gap_names) if gap_names else "the remaining gaps"
            blocked = [s for s in (line.get("services") or []) if SERVICES[s]["blocked_by_south_ridge"]]
            if blocked:
                why = (f"{line['display_name']}'s {SERVICES[blocked[0]]['constellation']} link is easy to "
                       f"block near {gap_txt}. T-Satellite (Starlink overhead) gives the group a better "
                       f"chance there—without upgrading a phone.")
            else:
                why = (f"Add T-Satellite on {line['display_name']}'s {line['phone']} for {trip_month} only "
                       f"so the group has enough reachable phones at {gap_txt} (estimate).")
            recommendations.append({
                "line_id": line["id"],
                "display_name": line["display_name"],
                "action": f"Add T-Satellite to {line['display_name']}'s line, {trip_month} only",
                "kind": "addon",
                "cost_usd": cost,
                "cost": f"${cost}",
                "service": "starlink",
                "start_month": trip_month,
                "stop_after_trip": True,
                "reason": why + f" ${cost}/mo—cancel after the trip.",
            })

        # Per-line "nothing" cards for people who don't need a purchase.
        for i, line in enumerate(lines):
            if any(r.get("line_id") == line["id"] for r in recommendations):
                continue
            recommendations.append({
                "line_id": line["id"],
                "display_name": line["display_name"],
                "action": f"Nothing for {line['display_name']}",
                "kind": "nothing",
                "cost_usd": 0,
                "cost": "$0",
                "reason": (f"{line['display_name']} reaches {per_line[i]['covered']} of {total} check-ins "
                           f"on their current setup (estimate). Others cover the rest—no purchase needed."),
            })

    # Step 3: Timekeeper — never push an upgrade for the trip; emit wait guidance when relevant.
    for line in lines:
        tsat_ok = is_tsat_compatible(line["phone"])
        has_sat = bool(line.get("services"))
        if tsat_ok and has_sat:
            continue
        if tsat_ok and any(r.get("line_id") == line["id"] and r["kind"] == "addon" for r in recommendations):
            continue
        timing_info = cost_now_vs_later(line)
        if not timing_info["applicable"]:
            continue
        if line.get("financing_months_left", 0) > 0 or not tsat_ok:
            timing.append(timing_info)
            if timing_info["verdict"] == "wait":
                # Replace a generic nothing card with wait guidance when this line can't help via add-on.
                recommendations = [r for r in recommendations
                                   if not (r.get("line_id") == line["id"] and r["kind"] == "nothing")]
                recommendations.append({
                    "line_id": line["id"],
                    "display_name": line["display_name"],
                    "action": f"Don't upgrade {line['display_name']} for this trip; revisit at payoff",
                    "kind": "wait",
                    "cost_usd": 0,
                    "cost": "$0 now",
                    "reason": timing_info["reason"],
                    "timing": timing_info,
                })

    # Cap visible purchase recommendations; keep wait/nothing for explainability (max ~5 cards).
    purchase = [r for r in recommendations if r["kind"] == "addon"][:3]
    other = [r for r in recommendations if r["kind"] != "addon"]
    recommendations = (purchase + other)[:5]

    our_cost = sum(r["cost_usd"] for r in recommendations if r["kind"] == "addon")
    naive_cost = n * NAIVE_PHONE_USD + n * TSAT_USD * NAIVE_ADDON_MONTHS
    savings = max(0, naive_cost - our_cost)

    if our_cost == 0:
        headline = "You're covered. Buy nothing."
        outcome = "covered"
    else:
        headline = f"This household needs ${our_cost} for the trip—not new phones."
        outcome = "add_service"

    final_group = [
        sum(effective[li][ci] for li in range(n)) >= need
        for ci in range(total)
    ]

    cart = build_cart(recommendations, hh)

    sample = _line_coverage(trail, lines[0], household=hh)
    return {
        "household_id": hh["id"],
        "household_name": hh["name"],
        "summary": hh.get("summary", ""),
        "as_of": CATALOG_AS_OF,
        "source_url": PRICE_SOURCE_URL,
        "outcome": outcome,
        "headline": headline,
        "redundancy": need,
        "current_group_covered": sum(group_covered),
        "best_group_covered": sum(final_group),
        "total": total,
        "per_line": per_line,
        "recommendations": recommendations,
        "timing": timing,
        "cart": cart,
        "trip_date": hh.get("trip_date") or sample.get("trip_date"),
        "start_time": sample.get("start_time"),
        "trip_month": trip_month,
        "savings": {
            "our_cost_usd": our_cost,
            "naive_upsell_usd": naive_cost,
            "savings_usd": savings,
            "naive_label": f"New phone + year of T-Satellite on all {n} lines",
            "our_label": "Cheapest honest setup for this trip",
        },
        "checkin_names": [c["name"] for c in checkins],
    }


def build_cart(recommendations, household):
    """Cart Whisperer: 0–3 explained items. Empty cart is a valid outcome."""
    items = []
    for r in recommendations:
        if r["kind"] == "addon":
            items.append({
                "type": "addon",
                "sku": "tsatellite",
                "title": r["action"],
                "line_id": r.get("line_id"),
                "cost_usd": r["cost_usd"],
                "cost": r["cost"],
                "start_month": r.get("start_month"),
                "stop_after_trip": True,
                "why": r["reason"],
            })
        elif r["kind"] == "wait":
            items.append({
                "type": "reminder",
                "sku": "upgrade_payoff_reminder",
                "title": r["action"],
                "line_id": r.get("line_id"),
                "cost_usd": 0,
                "cost": "$0",
                "why": r["reason"],
            })
    purchase_items = [i for i in items if i["type"] == "addon"]
    return {
        "household_id": household["id"],
        "line_items": items[:3],
        "empty": len(purchase_items) == 0,
        "total_usd": sum(i["cost_usd"] for i in purchase_items),
        "celebration": "Nothing to buy—you're covered." if not purchase_items else None,
    }
