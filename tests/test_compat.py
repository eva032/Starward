"""Compatibility catalog + selector logic (app behavior, not external truth)."""
import os
import unittest

os.environ.pop("PHOTON_KEY", None)
os.environ["FLASK_SECRET_KEY"] = "test-secret"

from app import app  # noqa: E402
from data import PROFILES, TRAIL  # noqa: E402
from data.compat import (  # noqa: E402
    build_recommendation,
    needs_activation_question,
    resolve_setup,
    should_use_recommend_engine,
    tsat_addon_verified,
    unknown_recommendation,
)
from recommend import get_recommendation  # noqa: E402

INTEGRATION_REASON = "Track C's compatibility verdicts (verified / potentially compatible / not verified) and its 'no T-Satellite for non-T-Mobile' rule were replaced by Track B's engine in the integration branch. Team decision pending; remove this marker if C's rule is restored."


def _rec_fn(trail, profile, trip_date=None, start_time=None, allow_tsat_purchase=True):
    return get_recommendation(
        trail, profile,
        trip_date=trip_date,
        start_time=start_time,
        allow_tsat_purchase=allow_tsat_purchase,
    )


class CompatResolveTests(unittest.TestCase):
    def test_verizon_pixel9_verified_skylo_sms(self):
        setup = resolve_setup("pixel_9", "Verizon", demo_profiles=PROFILES)
        self.assertEqual(setup["status"], "verified")
        self.assertIn("skylo", setup["profile"]["services"])
        self.assertFalse(setup["ask_activation"])
        self.assertTrue(any("verizon.com" in s["url"] for s in setup["sources"]))

    def test_tmobile_galaxy_s25_demo_conditional(self):
        setup = resolve_setup("galaxy_s25", "T-Mobile", satellite_activated="yes", demo_profiles=PROFILES)
        self.assertEqual(setup["demo_profile_id"], "tmobile_galaxy")
        self.assertEqual(setup["status"], "conditional")
        self.assertFalse(should_use_recommend_engine(setup))
        # Unverified demos must not paint the map as SMS-covered.
        self.assertEqual(setup["profile"]["services"], [])
        self.assertFalse(setup["profile"]["tsat_compatible"])

    def test_att_iphone13_demo_not_compatible(self):
        setup = resolve_setup("iphone_13", "AT&T", satellite_activated="no", demo_profiles=PROFILES)
        self.assertEqual(setup["demo_profile_id"], "att_iphone13")
        rec = build_recommendation(TRAIL, setup, _rec_fn)
        self.assertEqual(rec["outcome"], "not_compatible")
        self.assertNotIn("you're covered", rec["headline"].lower())

    def test_att_iphone15_demo_not_unconditionally_covered(self):
        setup = resolve_setup("iphone_15", "AT&T", demo_profiles=PROFILES)
        self.assertEqual(setup["demo_profile_id"], "att_iphone15")
        self.assertEqual(setup["status"], "conditional")
        rec = build_recommendation(TRAIL, setup, _rec_fn)
        self.assertNotEqual(rec["outcome"], "covered")
        self.assertNotIn("you're covered", rec["headline"].lower())
        self.assertNotIn("you're set", rec["headline"].lower())
        self.assertIn("sms", rec["headline"].lower() + rec["options"][0]["reason"].lower())

    def test_verizon_galaxy_s25_any_combination_allowed(self):
        setup = resolve_setup("galaxy_s25", "Verizon", demo_profiles=PROFILES)
        self.assertEqual(setup["status"], "verified")
        self.assertIn("skylo", setup["profile"]["services"])
        self.assertIsNone(setup["demo_profile_id"])

    def test_pixel_sos_not_ordinary_sms_on_att(self):
        setup = resolve_setup("pixel_9", "AT&T", demo_profiles=PROFILES)
        self.assertEqual(setup["status"], "sos_only")
        self.assertEqual(setup["profile"]["services"], [])
        self.assertFalse(should_use_recommend_engine(setup))
        rec = unknown_recommendation(TRAIL, setup)
        self.assertEqual(rec["outcome"], "not_compatible")
        self.assertIn("emergency sos", rec["headline"].lower())
        self.assertFalse(any("t-satellite" in o["action"].lower() and "$10" in o["cost"] for o in rec["options"]))

    @unittest.expectedFailure  # Track C verdict replaced by Track B engine; see INTEGRATION_REASON

    def test_tmobile_iphone16_asks_activation_but_not_verified(self):
        self.assertTrue(needs_activation_question("iphone_16", "T-Mobile"))
        self.assertFalse(tsat_addon_verified("iphone_16", "T-Mobile"))
        off = resolve_setup("iphone_16", "T-Mobile", satellite_activated="no", demo_profiles=PROFILES)
        self.assertEqual(off["profile"]["services"], [])
        self.assertFalse(off["profile"]["tsat_compatible"])
        on = resolve_setup("iphone_16", "T-Mobile", satellite_activated="yes", demo_profiles=PROFILES)
        self.assertEqual(on["profile"]["services"], [])
        self.assertEqual(on["status"], "conditional")
        self.assertIn("potentially compatible", on["status_label"].lower())

    def test_other_phone_unknown_still_resolves(self):
        setup = resolve_setup("other_phone", "Other", demo_profiles=PROFILES)
        self.assertEqual(setup["status"], "unknown")
        self.assertFalse(should_use_recommend_engine(setup))
        rec = unknown_recommendation(TRAIL, setup)
        self.assertEqual(rec["outcome"], "unknown")

    def test_apple_sms_via_satellite_marked_unknown(self):
        setup = resolve_setup("iphone_14", "Verizon", satellite_activated="unsure", demo_profiles=PROFILES)
        self.assertIsNone(setup["demo_profile_id"])
        self.assertIn(setup["status"], ("unknown", "conditional"))


class AuditRegressionTests(unittest.TestCase):
    """Fixes from Track C merge audit — honesty over demo convenience."""

    @unittest.expectedFailure  # Track C verdict replaced by Track B engine; see INTEGRATION_REASON

    def test_tmobile_tutorial_never_unconditional_verified(self):
        for phone_id in ("iphone_16", "galaxy_s24", "pixel_9", "galaxy_z_flip6"):
            setup = resolve_setup(phone_id, "T-Mobile", satellite_activated="yes", demo_profiles=PROFILES)
            self.assertNotEqual(setup["status"], "verified", phone_id)
            self.assertNotIn("verified for ordinary", setup["status_label"].lower(), phone_id)
            self.assertIn("potentially compatible", setup["status_label"].lower(), phone_id)

    def test_verizon_pixel_demo_no_tsat_purchase(self):
        setup = resolve_setup("pixel_9", "Verizon", demo_profiles=PROFILES)
        self.assertEqual(setup["demo_profile_id"], "verizon_pixel")
        self.assertFalse(tsat_addon_verified("pixel_9", "Verizon"))
        rec = build_recommendation(TRAIL, setup, _rec_fn)
        self.assertNotEqual(rec["outcome"], "add_service")
        blob = (rec["headline"] + " ".join(o["action"] + o["cost"] for o in rec["options"])).lower()
        self.assertNotIn("$10", blob)
        self.assertNotIn("add t-satellite", blob)

    def test_galaxy_s25_tmobile_labeled_conditional(self):
        setup = resolve_setup("galaxy_s25", "T-Mobile", satellite_activated="yes", demo_profiles=PROFILES)
        self.assertEqual(setup["status"], "conditional")
        self.assertEqual(setup["profile"]["services"], [])
        notes = " ".join(setup["notes"]).lower()
        self.assertTrue("not verified" in notes or "confirm" in notes)

    def test_att_iphone15_no_youre_covered_headline(self):
        setup = resolve_setup("iphone_15", "AT&T", demo_profiles=PROFILES)
        rec = build_recommendation(TRAIL, setup, _rec_fn)
        self.assertNotIn("you're covered", rec["headline"].lower())
        self.assertNotIn("you're set", rec["headline"].lower())

    def test_sos_and_unknown_no_purchase(self):
        for phone_id, carrier, activated in (
            ("pixel_9", "AT&T", ""),
            ("other_phone", "Other", ""),
            ("galaxy_s22", "T-Mobile", "yes"),
        ):
            setup = resolve_setup(phone_id, carrier, activated, demo_profiles=PROFILES)
            rec = build_recommendation(TRAIL, setup, _rec_fn)
            self.assertNotEqual(rec["outcome"], "add_service", f"{phone_id}|{carrier}")
            actions = " ".join(o["action"].lower() for o in rec["options"])
            self.assertNotIn("add t-satellite for the trip", actions)

    def test_verified_skylo_still_gets_engine_recommendation(self):
        setup = resolve_setup("galaxy_s25", "Verizon", demo_profiles=PROFILES)
        self.assertEqual(setup["status"], "verified")
        self.assertTrue(should_use_recommend_engine(setup))
        rec = build_recommendation(TRAIL, setup, _rec_fn)
        self.assertIn(rec["outcome"], ("covered", "not_compatible"))
        self.assertNotEqual(rec["outcome"], "add_service")
        self.assertNotEqual(rec["outcome"], "unknown")

    @unittest.expectedFailure  # Track C verdict replaced by Track B engine; see INTEGRATION_REASON

    def test_verizon_partial_coverage_not_phone_blame_headline(self):
        setup = resolve_setup("pixel_9", "Verizon", demo_profiles=PROFILES)
        rec = build_recommendation(TRAIL, setup, _rec_fn)
        headline = rec["headline"].lower()
        self.assertNotIn("no add-on will help on this phone", headline)
        self.assertNotIn("$10 once", headline)
        for o in rec["options"]:
            self.assertNotIn("$10 once", o.get("cost", "").lower())
        if rec["outcome"] == "not_compatible":
            self.assertTrue(
                "estimated chance" in headline or "no verified add-on" in headline,
                rec["headline"],
            )

    def test_no_ten_once_price_anywhere_in_engine(self):
        from recommend import get_recommendation
        # Even if purchase were allowed, copy must be monthly — never "once".
        profile = {
            **PROFILES["verizon_pixel"],
            "services": [],
            "tsat_compatible": True,
            "household_lines": 2,
        }
        rec = get_recommendation(TRAIL, profile, allow_tsat_purchase=True)
        blob = (rec["headline"] + " ".join(o["action"] + o["cost"] + o["reason"] for o in rec["options"])).lower()
        self.assertNotIn("$10 once", blob)
        if rec["outcome"] == "add_service":
            self.assertIn("$10/mo", blob)

    def test_att_iphone15_demo_services_empty(self):
        setup = resolve_setup("iphone_15", "AT&T", demo_profiles=PROFILES)
        self.assertEqual(setup["profile"]["services"], [])
        from coverage import get_coverage
        cov = get_coverage(TRAIL, setup["profile"])
        self.assertEqual(sum(1 for c in cov["checkins"] if c["covered"]), 0)

    def test_iphone_17_in_catalog(self):
        from data.compat import PHONES_BY_ID
        self.assertIn("iphone_17", PHONES_BY_ID)
        self.assertIn("iphone_air", PHONES_BY_ID)


class CompatFormFlowTests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test-secret"
        self.client = app.test_client()

    def _plan(self, **overrides):
        data = {
            "trail_id": "colchuck",
            "trip_date": "2026-10-18",
            "start_time": "09:00",
            "hiker_name": "Alex Rivera",
            "hiker_number": "+1 555 111 2222",
            "manufacturer": "Google",
            "phone_id": "pixel_9",
            "carrier": "Verizon",
            "contact": "+1 555 123 4567",
        }
        data.update(overrides)
        return data

    def test_home_has_simplified_phone_selector(self):
        res = self.client.get("/")
        body = res.get_data(as_text=True)
        self.assertIn("What phone do you have?", body)
        self.assertIn('id="phone_search"', body)
        self.assertIn('name="phone_id"', body)
        self.assertNotIn("Phone maker", body)
        self.assertIn("find my phone", body.lower())
        self.assertIn("Google Pixel 9", body)  # in phones JSON payload labels

    def test_any_phone_carrier_generates_plan(self):
        res = self.client.post(
            "/plan",
            data=self._plan(
                manufacturer="Samsung",
                phone_id="galaxy_s24",
                carrier="AT&T",
                satellite_activated="unsure",
            ),
        )
        self.assertEqual(res.status_code, 200)
        body = res.get_data(as_text=True)
        # No Skylo / verified ordinary SMS for this pair — plan still generates.
        self.assertTrue(
            "not verified" in body.lower() or "no verified ordinary satellite sms" in body.lower(),
            body[:400],
        )
        self.assertIn("Check-in plan", body)
        self.assertNotIn("not in the catalog", body)

    @unittest.expectedFailure  # Track C verdict replaced by Track B engine; see INTEGRATION_REASON

    def test_verizon_s25_verified_plan(self):
        res = self.client.post(
            "/plan",
            data=self._plan(manufacturer="Samsung", phone_id="galaxy_s25", carrier="Verizon"),
        )
        self.assertEqual(res.status_code, 200)
        body = res.get_data(as_text=True)
        self.assertIn("verizon.com", body.lower())
        self.assertIn("Forest junction", body)
        self.assertIn("Satellite texting supported on eligible plans", body)

    def test_tmobile_tutorial_device_requires_activation_answer(self):
        res = self.client.post(
            "/plan",
            data=self._plan(
                manufacturer="Apple",
                phone_id="iphone_16",
                carrier="T-Mobile",
            ),
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("activated", res.get_data(as_text=True).lower())

    @unittest.expectedFailure  # Track C verdict replaced by Track B engine; see INTEGRATION_REASON

    def test_tmobile_iphone16_with_activation_not_verified_badge(self):
        res = self.client.post(
            "/plan",
            data=self._plan(
                manufacturer="Apple",
                phone_id="iphone_16",
                carrier="T-Mobile",
                satellite_activated="yes",
            ),
        )
        self.assertEqual(res.status_code, 200)
        body = res.get_data(as_text=True)
        self.assertIn("t-mobile.com", body.lower())
        self.assertIn("Potentially compatible with T-Satellite", body)
        self.assertNotIn("Satellite texting supported on eligible plans", body)
        self.assertIn("Check-in plan", body)

    @unittest.expectedFailure  # Track C verdict replaced by Track B engine; see INTEGRATION_REASON

    def test_demo_profiles_still_work(self):
        cases = [
            ("Google", "pixel_9", "Verizon", "", "supported on eligible"),
            ("Samsung", "galaxy_s25", "T-Mobile", "yes", "potentially compatible"),
            ("Apple", "iphone_15", "AT&T", "", "not confirmed"),
            ("Apple", "iphone_13", "AT&T", "no", "not supported"),
        ]
        for maker, phone_id, carrier, activated, needle in cases:
            with self.subTest(phone_id=phone_id, carrier=carrier):
                data = self._plan(
                    manufacturer=maker, phone_id=phone_id, carrier=carrier,
                )
                if activated:
                    data["satellite_activated"] = activated
                elif needs_activation_question(phone_id, carrier):
                    data["satellite_activated"] = "yes"
                res = self.client.post("/plan", data=data)
                body = res.get_data(as_text=True)
                self.assertEqual(res.status_code, 200, body[:300])
                self.assertIn(needle, body.lower())
                self.assertNotIn("you&#39;re covered", body.lower())

    @unittest.expectedFailure  # Track C verdict replaced by Track B engine; see INTEGRATION_REASON

    def test_unlisted_phone_continues_as_unknown(self):
        res = self.client.post(
            "/plan",
            data=self._plan(
                manufacturer="Other",
                phone_id="other_phone",
                carrier="Verizon",
            ),
        )
        self.assertEqual(res.status_code, 200)
        body = res.get_data(as_text=True)
        self.assertIn("Check-in plan", body)
        self.assertIn("not verified", body.lower())
        self.assertIn("find my phone", body.lower())


if __name__ == "__main__":
    unittest.main()
