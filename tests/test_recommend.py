"""Focused Track B tests for get_recommendation and situation profiles."""
from coverage import get_coverage
from data import TRAIL, build_situation_profile, infer_services, is_tsat_compatible
from recommend import _trip_kwargs, get_recommendation

DENSE_TRAIL = {
    "cell_spots": ["lot", "ridge"],
    "start_time": "9:00am",
    "points": [
        {"lat": 47.5, "lon": -120.8, "canopy": 0.95, "south_blocked": False}
        for _ in range(8)
    ],
}


def _rec(phone, carrier, *, plan_status="can_add_tsat", satellite_choice="auto",
         plan_name="My plan", trip_date="", start_time="09:00", trail=TRAIL):
    profile = build_situation_profile(
        phone, carrier,
        plan_name=plan_name,
        plan_status=plan_status,
        satellite_choice=satellite_choice,
        trip_date=trip_date,
        start_time=start_time,
    )
    return profile, get_recommendation(trail, profile)


def test_already_covered_does_not_upsell():
    profile, rec = _rec("iPhone 15", "T-Mobile", plan_status="tsat_included", plan_name="Go5G Next")
    assert rec["outcome"] == "covered"
    assert rec["options"][0]["action"].startswith("Keep")
    assert "Add T-Satellite" not in rec["options"][0]["action"]
    assert rec["current_covered"] == rec["total"]
    assert rec["options"][0]["actionable"] is True
    assert rec["options"][0]["coverage_gain"] == 0


def test_compatible_can_add_primary_is_actionable():
    profile, rec = _rec("Pixel 9", "Verizon", plan_status="can_add_tsat")
    assert profile["tsat_compatible"] is True
    assert rec["outcome"] == "add_service"
    top = rec["options"][0]
    assert top["action"].startswith("Add T-Satellite")
    assert top["actionable"] is True
    assert rec["best_covered"] > rec["current_covered"]
    assert top["coverage_gain"] == rec["best_covered"] - rec["current_covered"]
    assert top["checkins_before"] == rec["current_covered"]
    assert top["checkins_after"] == rec["best_covered"]
    assert top["why"]
    assert rec["why_this"]
    assert len(rec["why_this"]) <= 3


def test_compatible_cannot_add_is_blocked_not_upsold():
    profile, rec = _rec("Pixel 9", "Verizon", plan_status="cannot_add")
    assert profile["tsat_compatible"] is True
    assert profile["plan_status"] == "cannot_add"
    assert rec["outcome"] == "cannot_add"
    assert rec.get("would_help") is True
    assert rec.get("block_kind") == "account"
    assert "Add T-Satellite" not in rec["options"][0]["action"]
    assert rec["options"][0]["actionable"] is True
    assert rec["best_covered"] > rec["current_covered"]
    blocked = [o for o in rec["options"] if o["actionable"] is False]
    assert blocked, "blocked theoretical option should be listed"
    assert blocked[0]["coverage_gain"] > 0
    assert "lock" in (rec["options"][0]["caveat"] or "").lower() or "eSIM" in (rec["options"][0]["caveat"] or "")
    assert any("blocked" in p.lower() or "lock" in p.lower() for p in rec["why_this"])


def test_unsupported_device_block_kind_device():
    profile, rec = _rec("iPhone 12", "T-Mobile", plan_status="can_add_tsat", satellite_choice="none")
    assert profile["tsat_compatible"] is False
    assert rec["outcome"] == "not_compatible"
    assert rec["block_kind"] == "device"
    assert "Add T-Satellite" not in rec["options"][0]["action"]
    assert any("cannot use" in p.lower() or "not" in p.lower() for p in rec["why_this"])


def test_compatible_no_meaningful_gain_block_kind_no_gain():
    profile, rec = _rec(
        "Pixel 9", "T-Mobile",
        plan_status="can_add_tsat",
        satellite_choice="none",
        trail=DENSE_TRAIL,
    )
    assert profile["tsat_compatible"] is True
    assert rec["outcome"] == "not_compatible"
    assert rec["block_kind"] == "no_gain"
    assert "Add T-Satellite" not in rec["options"][0]["action"]
    assert any("would not" in (rec.get("vs_alternative") or "").lower()
               or "not improve" in p.lower()
               or "no available add-on" in p.lower()
               for p in rec["why_this"] + [rec.get("vs_alternative") or ""])


def test_trip_start_time_afternoon_passed_into_coverage(monkeypatch):
    seen = []
    real = get_coverage

    def spy(trail, profile, services=None, trip_date=None, start_time=None):
        seen.append({"trip_date": trip_date, "start_time": start_time, "services": services})
        return real(trail, profile, services=services, trip_date=trip_date, start_time=start_time)

    monkeypatch.setattr("recommend.get_coverage", spy)
    profile, rec = _rec(
        "Pixel 9", "Verizon",
        plan_status="can_add_tsat",
        trip_date="2026-06-12",
        start_time="14:00",
    )
    assert rec["outcome"] == "add_service"
    assert seen, "get_recommendation should call get_coverage"
    assert all(c["start_time"] == "14:00" for c in seen)
    assert all(c["trip_date"] == "2026-06-12" for c in seen)
    cov = get_coverage(TRAIL, profile, **_trip_kwargs(profile, TRAIL))
    assert cov["start_time"] == "2:00pm"
    assert [c["time"] for c in cov["checkins"]] == ["3:30pm", "5:00pm", "6:30pm"]


def test_trip_timing_defaults_when_unset():
    profile, rec = _rec("Pixel 9", "Verizon", plan_status="can_add_tsat", trip_date="", start_time="")
    cov = get_coverage(TRAIL, profile, **_trip_kwargs(profile, TRAIL))
    default = get_coverage(TRAIL, profile)
    assert cov["start_time"] == default["start_time"] == "9:00am"
    assert [c["time"] for c in cov["checkins"]] == [c["time"] for c in default["checkins"]]
    assert rec["outcome"] in ("add_service", "covered", "cannot_add", "not_compatible")


def test_multi_service_iphone15_att_stays_covered_via_apple_satellite():
    profile, rec = _rec("iPhone 15", "AT&T", plan_status="can_add_tsat")
    assert "globalstar" in profile["services"]
    assert rec["outcome"] == "covered"
    assert "Add T-Satellite" not in rec["options"][0]["action"]
    assert rec["current_covered"] == rec["total"]
    blob = " ".join(rec["why_this"] + [rec["options"][0]["why"], rec.get("vs_alternative") or ""])
    assert "Add T-Satellite" not in blob
    assert "already" in blob.lower() or "enough" in blob.lower()


def test_cannot_add_does_not_clear_device_compatibility():
    profile = build_situation_profile(
        "Pixel 9", "Verizon",
        plan_status="cannot_add",
        satellite_choice="auto",
    )
    assert is_tsat_compatible("Pixel 9") is True
    assert profile["tsat_compatible"] is True
    assert profile["plan_status"] == "cannot_add"
    assert "starlink" not in infer_services(
        "Pixel 9", "Verizon", "auto", plan_status="cannot_add"
    )


def test_infer_services_auto_iphone15_att_includes_apple_not_tsat_by_default():
    services = infer_services("iPhone 15", "AT&T", "auto", plan_status="can_add_tsat")
    assert "globalstar" in services
    assert "starlink" not in services


def test_deterministic_option_ordering():
    _, a = _rec("Pixel 9", "Verizon", plan_status="can_add_tsat")
    _, b = _rec("Pixel 9", "Verizon", plan_status="can_add_tsat")
    assert [o["action"] for o in a["options"]] == [o["action"] for o in b["options"]]
    assert a["why_this"] == b["why_this"]
    assert a["vs_alternative"] == b["vs_alternative"]


def test_actionable_add_ranks_above_blocked_equivalent():
    _, can_add = _rec("Pixel 9", "Verizon", plan_status="can_add_tsat")
    _, blocked = _rec("Pixel 9", "Verizon", plan_status="cannot_add")
    assert can_add["outcome"] == "add_service"
    assert blocked["outcome"] == "cannot_add"
    assert can_add["options"][0]["actionable"] is True
    assert can_add["options"][0]["action"].startswith("Add T-Satellite")
    assert blocked["options"][0]["actionable"] is True
    assert not blocked["options"][0]["action"].startswith("Add T-Satellite")
    assert any(o["actionable"] is False and o["coverage_gain"] for o in blocked["options"])


def test_actionable_recommendation_has_structured_fields():
    _, rec = _rec("Pixel 9", "Verizon", plan_status="can_add_tsat")
    top = rec["options"][0]
    for key in ("coverage_gain", "checkins_before", "checkins_after", "cost",
                "actionable", "why", "caveat", "label"):
        assert key in top
    assert top["actionable"] is True
    assert top["coverage_gain"] > 0
    assert top["label"] == "Add T-Satellite"
    assert rec["vs_alternative"]
    assert "for" in rec["vs_alternative"].lower() or "$" in rec["vs_alternative"]
    assert rec["impact"]
    assert any(c["kind"] == "gain" for c in rec["impact"])
    assert any("check-in" in c["text"] for c in rec["impact"])


def test_cannot_add_exposes_blocked_insight_for_ui():
    _, rec = _rec("Pixel 9", "Verizon", plan_status="cannot_add")
    assert rec["blocked_insight"]
    assert rec["blocked_insight"]["status"] == "Not available yet"
    assert "→" in rec["blocked_insight"]["checkins"]
    assert rec["options"][0]["label"].startswith("Keep")
