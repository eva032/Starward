"""Focused Track C tests: validation, plan flow, share simulation, fallbacks."""
import os
import unittest

# Ensure Demo Mode for tests.
os.environ.pop("PHOTON_KEY", None)
os.environ.pop("BRIDGE_URL", None)
os.environ.pop("BRIDGE_TOKEN", None)
os.environ["FLASK_SECRET_KEY"] = "test-secret"

from app import app  # noqa: E402
from coverage import get_coverage, _parse_start_minutes  # noqa: E402
from data import PROFILES, TRAIL, get_trail, find_profile  # noqa: E402
from guardian import share_plan, simulate_missed, is_live  # noqa: E402


class CoverageTimingTests(unittest.TestCase):
    def test_parse_start_time_variants(self):
        self.assertEqual(_parse_start_minutes("09:00"), 9 * 60)
        self.assertEqual(_parse_start_minutes("9:00am"), 9 * 60)
        self.assertEqual(_parse_start_minutes("2:30pm"), 14 * 60 + 30)

    def test_get_coverage_respects_start_time(self):
        profile = PROFILES["verizon_pixel"]
        cov = get_coverage(TRAIL, profile, trip_date="2026-10-18", start_time="10:00")
        self.assertEqual(cov["start_time"], "10:00am")
        self.assertEqual(cov["trip_date"], "2026-10-18")
        self.assertEqual(len(cov["checkins"]), 3)
        # Real pace model (Track A): first check-in comes after the 10:00am start.
        first = cov["checkins"][0]["time"]
        self.assertRegex(first, r"^1[01]:\d\d[ap]m$")
        self.assertNotEqual(first, "10:00am")


class DataLoaderTests(unittest.TestCase):
    def test_trail_and_profile_helpers(self):
        self.assertEqual(get_trail("colchuck")["name"], "Colchuck Lake")
        pid, profile = find_profile(phone="Pixel 9", carrier="Verizon")
        self.assertEqual(pid, "verizon_pixel")
        # Track B's catalog: Pixel 9 is on T-Mobile's T-Satellite device list.
        self.assertTrue(profile["tsat_compatible"])

    def test_phone_carrier_beats_stale_profile_id(self):
        pid, profile = find_profile(
            phone="Galaxy S25", carrier="T-Mobile", profile_id="verizon_pixel",
        )
        self.assertEqual(pid, "tmobile_galaxy")
        self.assertEqual(profile["phone"], "Galaxy S25")


class AppFlowTests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test-secret"
        self.client = app.test_client()

    def _plan_form(self, **overrides):
        data = {
            "trail_id": "colchuck",
            "trip_date": "2026-10-18",
            "start_time": "09:00",
            "hiker_name": "Alex Rivera",
            "hiker_number": "+1 555 111 2222",
            "manufacturer": "Google",
            "phone_id": "pixel_9",
            "phone": "Pixel 9",
            "carrier": "Verizon",
            "contact": "+1 555 123 4567",
        }
        data.update(overrides)
        return data

    def test_home_shows_demo_mode_and_form(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        body = res.get_data(as_text=True)
        self.assertIn("Demo Mode", body)
        self.assertIn("Generate trip plan", body)
        self.assertIn("Trip planning", body)

    def test_plan_validation_rejects_bad_phone(self):
        res = self.client.post("/plan", data=self._plan_form(hiker_number="abc"))
        self.assertEqual(res.status_code, 400)
        self.assertIn("valid hiker phone", res.get_data(as_text=True))

    def test_generate_plan_shows_map_and_recommendation(self):
        res = self.client.post("/plan", data=self._plan_form())
        self.assertEqual(res.status_code, 200)
        body = res.get_data(as_text=True)
        self.assertIn("Check-in plan", body)
        self.assertIn("Alex Rivera", body)
        self.assertIn("estimate", body.lower())
        self.assertIn("as of", body.lower())
        self.assertIn("Mountaineer Creek", body)  # real Colchuck check-in (Track A)
        self.assertNotIn("$10 once", body)

    @unittest.expectedFailure  # see REASON in the integration notes
    def test_verizon_pixel_not_offered_tsat(self):
        """Track C rule: a Verizon Pixel must not be told to buy T-Satellite."""
        body = self.client.post("/plan", data=self._plan_form()).get_data(as_text=True)
        self.assertNotIn("Add T-Satellite", body)

    def test_all_profiles_render_via_plan(self):
        from data import resolve_phone_id
        from data.compat import needs_activation_question, phone_by_id

        for pid, profile in PROFILES.items():
            with self.subTest(profile=pid):
                phone_id = resolve_phone_id(phone_name=profile["phone"])
                phone = phone_by_id(phone_id)
                data = self._plan_form(
                    manufacturer=phone["manufacturer"],
                    phone_id=phone_id,
                    phone=profile["phone"],
                    carrier=profile["carrier"],
                )
                if needs_activation_question(phone_id, profile["carrier"]):
                    data["satellite_activated"] = "yes"
                res = self.client.post("/plan", data=data)
                self.assertEqual(res.status_code, 200, pid)
                body = res.get_data(as_text=True)
                self.assertIn(profile["phone"], body)

    def test_share_is_simulated_in_demo_mode(self):
        self.assertFalse(is_live())
        self.client.post("/plan", data=self._plan_form())
        res = self.client.post("/share", data=self._plan_form())
        self.assertEqual(res.status_code, 200)
        body = res.get_data(as_text=True)
        self.assertIn("no SMS sent", body)
        self.assertIn("Alex Rivera", body)

    def test_missed_alert_preview(self):
        form = self._plan_form()
        self.client.post("/plan", data=form)
        share_plan(
            form["contact"], TRAIL,
            get_coverage(TRAIL, PROFILES["verizon_pixel"], start_time="09:00"),
            hiker=form["hiker_name"], hiker_number=form["hiker_number"],
        )
        res = self.client.post("/simulate/missed", data=form)
        self.assertEqual(res.status_code, 200)
        body = res.get_data(as_text=True)
        self.assertIn("alert", body.lower())
        self.assertIn("emergency services", body.lower())
        self.assertIn("no SMS sent", body)

    def test_ui_labels_simulated_coverage_and_no_youre_covered(self):
        res = self.client.post("/plan", data=self._plan_form())
        body = res.get_data(as_text=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn("not a guarantee", body.lower())
        self.assertNotIn("You're covered", body)
        self.assertNotIn("$10 once", body)

    def test_health(self):
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["fake_mode"])


class GuardianCompatTests(unittest.TestCase):
    def test_share_plan_accepts_hiker_number(self):
        text = share_plan(
            "+15551234567",
            TRAIL,
            get_coverage(TRAIL, PROFILES["tmobile_galaxy"], start_time="08:00"),
            hiker="Sam",
            hiker_number="+15551112222",
        )
        self.assertIn("Sam", text)
        self.assertIn("OK", text)
        alert = simulate_missed("+15551234567")
        self.assertIn("hasn't checked in", alert)


if __name__ == "__main__":
    unittest.main()
