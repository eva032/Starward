# AGENTS.md: Starward

Starward predicts where on a hike your phone can text by satellite, recommends the cheapest setup that covers your check-ins, builds a check-in plan around those spots, and alerts an emergency contact if a check-in is missed. Hackathon project. Tracks: SpaceXAI, Photon, T-Mobile (recommendations in wireless commerce).

## Current state
Coverage uses real routes, terrain and satellite orbits (canopy still estimated); catalogs are JSON. SMS is Demo Mode unless `BRIDGE_URL` points at `bridge/`. Remaining fakes are marked `TODO(<owner>)`. Replace fakes one at a time; keep signatures backward compatible (add optional kwargs only).

## Run (localhost — Track C)
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env   # optional; Demo Mode works without the bridge
python app.py   # http://127.0.0.1:5000

Live SMS (Track D): `cd bridge && npm install && npm run start`, with matching `BRIDGE_URL` / `BRIDGE_TOKEN` in the root `.env` and Spectrum creds in `bridge/.env`.

## Ownership: stay in your own files
| Owner | Area | Files |
|---|---|---|
| A | Geo + space: routes, terrain horizons, canopy, satellite passes, check-in spots | coverage.py, route.py, terrain.py, orbits.py, tools/, `data/trails/`, `data/tle/` |
| B | Recommendation: carrier catalog, prices, which services a phone + carrier has, outcomes and reasons, household | recommend.py, `data/__init__.py`, `data/*.json` catalogs, templates/household.html, pitch/ |
| C | Web app + localhost: trip form, map, phone picker, official source links | app.py, templates/index.html, `data/phones.json`, `data/compatibility.json`, `data/compat.py` |
| D | Photon guardian: plan sharing, check-ins, missed-check-in alerts | guardian.py, bridge/ |

Shared package: `data/` (`__init__.py` exports `TRAILS`, `TRAIL`, `get_trail`, `PROFILES`, `SERVICES`, `CATALOG_AS_OF`, `build_situation_profile`, `infer_services`, ...).
Which services a phone + carrier has is decided by Track B (`infer_services`). `data/compat.py` supplies the phone list and official source links; its own verdict/recommendation path is not used by the app.

## Contracts (don't change without telling the team)
- `get_coverage(trail, profile, services=None, trip_date=None, start_time=None) -> {"segments": [...], "checkins": [...], "confidence", ...}`
  - `services` overrides the profile's services for "what if" comparisons.
  - `trip_date` ("YYYY-MM-DD") turns on real satellite windows from cached orbit data; without it, windows are placeholders. `start_time` accepts "9:00am" or "09:00".
  - segment: `{"lat", "lon", "openness", "color"}`; check-in: `{"idx", "name", "lat", "lon", "time", "windows", "color", "covered"}`
- `get_recommendation(trail, profile, trip_date=None, start_time=None, allow_tsat_purchase=True) -> {"outcome", "headline", "options", "as_of", "current_covered", "best_covered", "total", ...}`
  - trip timing comes from the profile unless passed explicitly.
  - `outcome` is exactly one of `"covered"`, `"add_service"`, `"cannot_add"`, `"not_compatible"`.
  - option: `{"action", "cost", "checkins_covered", "total", "reason"}`, ranked, 1 to 3 of them. `checkins_covered` may be `None` when it doesn't apply.
- `share_plan(contact_number, trail, coverage, hiker=..., hiker_number=None)`, `handle_checkin(from_number, text)`, `simulate_missed(contact)`
If you need a new field, add it. Don't rename or remove existing ones.

## Rules for agents
- Keep changes small and scoped to the task and owner's files.
- Don't add dependencies without adding them to requirements.txt.
- Secrets go in `.env` only; never commit keys. Add new keys to `.env.example`.
- Keep it simple: no frameworks, databases, or build steps unless asked.
- Run `python -m pytest -q` and generate a plan for every trail with a few phones before calling a task done.

## Product rules (never break these)
- Never present a check-in spot or coverage as guaranteed; say "estimate" or "best chance."
- Never contact emergency services automatically. Alerts go to the user's contact and point to official emergency options.
- All analysis runs before the trip. On the trail, the hiker only sends a plain text.
- Show an as-of date on anything from the carrier catalog.
- Never push a phone upgrade. Recommend the cheapest thing that works, including "don't buy anything."
