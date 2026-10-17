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


def _trip_kwargs(source=None, trail=None):
    """Trip timing for get_coverage from a profile or household; fall back to trail defaults."""
    src = source or {}
    return {
        "trip_date": src.get("trip_date") or (trail or {}).get("trip_date"),
        "start_time": src.get("start_time") or (trail or {}).get("start_time"),
    }


def _tsat_gap_why(phone, services, gaps):
    """Shared coverage-gap explanation for actionable and blocked add-on paths."""
    blocked = [s for s in services if SERVICES[s]["blocked_by_south_ridge"]]
    if blocked:
        sat = SERVICES[blocked[0]]["constellation"]
        return (f"Your {phone}'s {sat} link sits low in the southern sky. Near "
                f"{_short(gaps[0])}, a ridge blocks that view—so our estimate shows a weak chance "
                f"with your current setup. T-Satellite uses Starlink passes overhead, which gives "
                f"you a better chance at those spots.")
    if services:
        return (f"Adding T-Satellite adds Starlink passes overhead, which our estimate says "
                f"improves your chance at {_short(gaps[0])}.")
    return (f"Your {phone} can use T-Satellite, but satellite texting isn't on yet. "
            f"Turning it on for this trip gives you a better chance at the check-ins.")


def _gain_phrase(gain, *, verb="Adds"):
    if gain is None:
        return None
    if gain <= 0:
        return "No coverage gain"
    unit = "check-in" if gain == 1 else "check-ins"
    return f"{verb} {gain} more {unit}"


def _cost_per_month_label(cost):
    """Avoid '$10/mo/month' when SERVICES cost already includes /mo."""
    text = str(cost or "").strip()
    if not text:
        return text
    if text.endswith("/mo") or "month" in text.lower():
        return text
    return f"{text}/month"


_ACTION_LABELS = {
    "Add T-Satellite for the trip month only": "Add T-Satellite",
    "Add it only for people on this hike": "Add only for hikers",
    "Keep your current setup": "Keep your current setup",
    "Keep your current setup for now": "Keep your current setup for now",
    "T-Satellite (blocked on this line)": "T-Satellite",
    "Plan check-ins where you'll have regular cell signal": "Plan around cell signal",
    "Consider a dedicated satellite messenger": "Consider a satellite messenger",
}


def _option(action, cost, total, *, why, actionable, checkins_before=None, checkins_after=None,
            caveat=None, label=None):
    """One ranked recommendation option with structured explainability fields."""
    gain = None
    if checkins_before is not None and checkins_after is not None:
        gain = checkins_after - checkins_before
    covered_display = checkins_after if checkins_after is not None else None
    reason = why if not caveat else f"{why} {caveat}"
    return {
        "action": action,
        "label": label or _ACTION_LABELS.get(action, action),
        "cost": cost,
        "checkins_covered": covered_display,
        "total": total,
        "reason": reason,
        "why": why,
        "caveat": caveat,
        "actionable": bool(actionable),
        "checkins_before": checkins_before,
        "checkins_after": checkins_after,
        "coverage_gain": gain,
    }


def _impact_chips(top, *, total, outcome, best_covered=None):
    """Compact numbers for the primary card (check-ins + cost)."""
    chips = []
    before = top.get("checkins_before")
    after = top.get("checkins_after")
    gain = top.get("coverage_gain")
    if before is not None and after is not None and gain and gain > 0:
        unit = "check-in" if after == 1 else "check-ins"
        chips.append({"kind": "checkins", "text": f"{before} → {after} {unit}"})
        gunit = "check-in" if gain == 1 else "check-ins"
        chips.append({"kind": "gain", "text": f"+{gain} {gunit}"})
    elif top.get("checkins_covered") is not None:
        n = top["checkins_covered"]
        unit = "check-in" if n == 1 else "check-ins"
        if outcome == "covered" or (before is not None and gain == 0):
            chips.append({"kind": "checkins", "text": f"{n} of {total} {unit}"})
        else:
            chips.append({"kind": "checkins", "text": f"{n} of {total} {unit}"})
    cost = (top.get("cost") or "").strip()
    if cost in ("$0", "0", ""):
        chips.append({"kind": "cost", "text": "$0 change"})
    elif cost:
        chips.append({"kind": "cost", "text": cost})
    return chips[:3]


def _with_explain(rec, outcome, headline, options, *, best_covered, why_this, vs_alternative=None,
                  would_help=None, block_kind=None, blocked_insight=None):
    """Attach outcome plus compact ranking explanation (deterministic, no scoring dump)."""
    top = options[0] if options else {}
    out = {
        **rec,
        "outcome": outcome,
        "best_covered": best_covered,
        "headline": headline,
        "options": options,
        "why_this": why_this[:3],
        "vs_alternative": vs_alternative,
        "impact": _impact_chips(top, total=rec["total"], outcome=outcome, best_covered=best_covered),
    }
    if would_help is not None:
        out["would_help"] = would_help
    if block_kind is not None:
        out["block_kind"] = block_kind
    if blocked_insight is not None:
        out["blocked_insight"] = blocked_insight
    return out


def get_recommendation(trail, profile):
    """Per-phone recommendation. Contract unchanged; extra fields are additive."""
    trip = _trip_kwargs(profile, trail)
    current = get_coverage(trail, profile, **trip)
    total = len(current["checkins"])
    covered = _count(current)
    services = profile["services"]
    phone = profile["phone"]
    # Device list vs account/lock: keep these separate (plan_status cannot_add ≠ incompatible phone).
    device_ok = is_tsat_compatible(phone)
    account_blocked = profile.get("plan_status") == "cannot_add"
    tsat_cost = SERVICES["starlink"]["cost"]
    rec = {
        "as_of": CATALOG_AS_OF,
        "source_url": PRICE_SOURCE_URL,
        "current_covered": covered,
        "total": total,
        "situation_summary": profile.get("summary") or f"{phone} · {profile.get('carrier', '')}",
        "inferred": bool(profile.get("inferred")),
        "device_tsat_ok": device_ok,
        "account_blocked": account_blocked,
    }

    if services and covered == total:
        if "starlink" in services:
            why = (f"Your current setup already covers the planned check-ins. "
                   f"Your {phone} already includes T-Satellite on your plan.")
        else:
            why = (f"Your current setup already covers the planned check-ins. "
                   f"Your {phone} uses {_service_names(services)} on this route.")
        opt = _option(
            "Keep your current setup", "$0", total,
            why=why, actionable=True,
            checkins_before=covered, checkins_after=covered,
            caveat="No purchase needed for this trip.",
        )
        return _with_explain(
            rec, "covered", "You're set. Don't buy anything for this trip.", [opt],
            best_covered=covered,
            why_this=[
                f"Already covers all {total} planned check-ins",
                "No add-on cost",
                "Your current satellite setup is enough on this route",
            ],
            vs_alternative="Buying T-Satellite would not improve check-ins further on this trip.",
        )

    # Theoretical T-Satellite gain (device must support the radio; account may still block adding it).
    with_tsat = covered
    gaps = []
    if device_ok and "starlink" not in services:
        boosted = get_coverage(trail, profile, services=services + ["starlink"], **trip)
        with_tsat = _count(boosted)
        if with_tsat > covered:
            gaps = [c for c, b in zip(current["checkins"], boosted["checkins"])
                    if not c["covered"] and b["covered"]]

    if device_ok and "starlink" not in services and with_tsat > covered:
        why = _tsat_gap_why(phone, services, gaps)
        gain = with_tsat - covered
        gain_txt = _gain_phrase(gain)
        if not account_blocked:
            # Rank: actionable add-on first, then keep-as-is (cheaper but weaker coverage).
            options = [_option(
                "Add T-Satellite for the trip month only", tsat_cost, total,
                why=why, actionable=True,
                checkins_before=covered, checkins_after=with_tsat,
                caveat=(f"It's {tsat_cost} per line—cancel in T-Life after the trip so you "
                        f"only pay for the month you need."),
            )]
            if profile.get("household_lines", 1) > 1:
                options.append(_option(
                    "Add it only for people on this hike", f"{tsat_cost} per line", total,
                    why="Skip lines for anyone staying home. Only add it for hikers who'll need "
                        "the check-in texts.",
                    actionable=True,
                    checkins_before=covered, checkins_after=with_tsat,
                ))
            missed = [c for c in current["checkins"] if not c["covered"]]
            options.append(_option(
                "Keep your current setup", "$0", total,
                why=(f"Saves the add-on, but our estimate shows little or no signal at "
                     f"{', '.join(_short(c) for c in missed)}."),
                actionable=True,
                checkins_before=covered, checkins_after=covered,
                caveat="Your contact may get a missed check-in alert there even when you're fine.",
            ))
            headline = (f"A $10 add-on covers every check-in." if with_tsat == total
                        else f"A $10 add-on covers {with_tsat} of {total} check-ins.")
            cost_label = _cost_per_month_label(tsat_cost)
            return _with_explain(
                rec, "add_service", headline, options,
                best_covered=with_tsat,
                why_this=[
                    f"{gain_txt} ({covered} → {with_tsat} of {total})",
                    f"Costs {cost_label} for the trip month",
                    "You can add it on this phone and line",
                ],
                vs_alternative=(f"{gain_txt} for {cost_label}. "
                                f"Keeping your setup costs $0 but does not improve the uncovered segment."),
            )

        # Compatible device, material gain, but line cannot add the service yet.
        # Rank usable steps first; blocked theoretical add-on is secondary and not actionable.
        cell = " and ".join(trail["cell_spots"])
        block_caveat = (f"This line can't add T-Satellite right now—usually a carrier-locked phone, "
                        f"no eSIM, or an account restriction. Unlock the phone, move to an eSIM-capable "
                        f"setup, or clear the account limit before “Add T-Satellite” becomes an option.")
        options = [
            _option(
                "Keep your current setup for now", "$0", total,
                why=why, actionable=True,
                checkins_before=covered, checkins_after=covered,
                caveat=block_caveat,
            ),
            _option(
                "T-Satellite (blocked on this line)", tsat_cost, total,
                why=why, actionable=False,
                checkins_before=covered, checkins_after=with_tsat,
                caveat=block_caveat,
            ),
            _option(
                "Plan check-ins where you'll have regular cell signal", "$0", total,
                why=(f"Until the line can add the service, lean on regular cell at the {cell}. "
                     f"Tell your contact to expect texts from those spots and silence in between."),
                actionable=True,
            ),
            _option(
                "Consider a dedicated satellite messenger",
                "About $200–$400 + subscription (estimate)", total,
                why="A separate messenger works without adding T-Satellite to this line. "
                    "Only worth it if you often hike beyond cell coverage.",
                actionable=True,
            ),
        ]
        could_gain = _gain_phrase(gain, verb="add")
        cost_label = _cost_per_month_label(tsat_cost)
        gunit = "check-in" if gain == 1 else "check-ins"
        return _with_explain(
            rec, "cannot_add",
            "T-Satellite could help, but you can't add it on this line yet.",
            options,
            best_covered=with_tsat,
            would_help=True,
            block_kind="account",
            why_this=[
                f"T-Satellite could {could_gain} ({covered} → {with_tsat} of {total})",
                "Blocked on this line (lock, eSIM, or account restriction)—not a device incompatibility",
                "Do not buy the add-on until the line can actually use it",
            ],
            vs_alternative=(f"T-Satellite would {could_gain} for {cost_label}, but it is not "
                            f"usable yet. Keeping your setup is the actionable choice today."),
            blocked_insight={
                "title": "T-Satellite could help — not available on this line",
                "checkins": f"{covered} → {with_tsat} check-ins",
                "gain": f"+{gain} {gunit}",
                "cost": cost_label,
                "status": "Not available yet",
                "reason": ("Usually a carrier-locked phone, no eSIM, or an account restriction. "
                           "Unlock, enable eSIM, or clear the account limit before this becomes an option."),
            },
        )

    cell = " and ".join(trail["cell_spots"])
    if not device_ok:
        headline = "Your phone does not support this satellite service."
        phone_note = (f"The {phone} isn't on T-Mobile's T-Satellite list, so we won't suggest adding "
                      f"that service—or buying a new phone for one hike.")
        block_kind = "device"
        why_this = [
            f"{phone} cannot use T-Satellite",
            "No actionable phone add-on for this trip",
            "Plan around regular cell or a separate messenger",
        ]
        vs = "A phone add-on is not available on this device; cell planning is the practical next step."
    else:
        headline = "No add-on will meaningfully improve this route."
        phone_note = "An add-on wouldn't improve check-in coverage on this trail with your setup."
        block_kind = "no_gain"
        why_this = [
            "No available add-on improves check-in coverage here",
            f"Current estimate stays at {covered} of {total} check-ins",
            "Focus on cell-covered spots instead of buying a service",
        ]
        vs = "Paying for an add-on would not cover additional check-ins on this route."
    options = [
        _option(
            "Plan check-ins where you'll have regular cell signal", "$0", total,
            why=f"{phone_note} You should have regular cell signal at the {cell}. "
                f"Tell your contact to expect texts from those spots and silence in between.",
            actionable=True,
            checkins_before=covered, checkins_after=covered,
        ),
        _option(
            "Consider a dedicated satellite messenger",
            "About $200–$400 + subscription (estimate)", total,
            why="A separate messenger works with the phone you already have. Only worth it if "
                "you often hike beyond cell coverage—not something we'd push for a single trip.",
            actionable=True,
        ),
    ]
    return _with_explain(
        rec, "not_compatible", headline, options,
        best_covered=covered,
        block_kind=block_kind,
        why_this=why_this,
        vs_alternative=vs,
    )


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
