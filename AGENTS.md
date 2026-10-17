# AGENTS.md: Starward

Starward predicts where on a hike your phone can text by satellite, recommends the cheapest setup that covers your check-ins, builds a check-in plan around those spots, and alerts an emergency contact if a check-in is missed. Hackathon project. Tracks: SpaceXAI, Photon, T-Mobile (recommendations in wireless commerce).

## Current state
Bare-bones skeleton. **Everything is hardcoded.** Each fake piece is marked `TODO(<owner>)`. Replace fakes one at a time without changing function signatures.

## Run
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py   # http://localhost:5000

## Ownership: stay in your own files
| Owner | Area | Files |
|---|---|---|
| A | Geo + space: route sampling, SRTM horizon masks, USFS canopy, skyfield passes, check-in picker | coverage.py, data.py `TRAIL` (+ new route.py, terrain.py, orbits.py) |
| B | Recommendation: carrier catalog, prices, the three outcomes and their reasons | recommend.py, data.py `PROFILES` / `SERVICES` / `CATALOG_AS_OF` |
| C | Web app + deploy: Flask routes, map, UI | app.py, templates/ |
| D | Photon guardian: plan sharing, check-ins, missed-check-in alerts | guardian.py |

## Contracts (don't change without telling the team)
- `get_coverage(trail, profile, services=None) -> {"segments": [...], "checkins": [...], "confidence", ...}`
  - `services` overrides the profile's services for "what if" comparisons.
  - segment: `{"lat", "lon", "openness", "color"}`; check-in: `{"idx", "name", "lat", "lon", "time", "windows", "color", "covered"}`
- `get_recommendation(trail, profile) -> {"outcome", "headline", "options", "as_of", "current_covered", "best_covered", "total"}`
  - `outcome` is exactly one of `"covered"`, `"add_service"`, `"not_compatible"`.
  - option: `{"action", "cost", "checkins_covered", "total", "reason"}`, ranked, 1 to 3 of them. `checkins_covered` may be `None` when it doesn't apply.
- `share_plan(contact_number, trail, coverage, hiker=...)`, `handle_checkin(from_number, text)`, `simulate_missed(contact)`
If you need a new field, add it. Don't rename or remove existing ones.

## Rules for agents
- Keep changes small and scoped to the task and owner's files.
- Don't add dependencies without adding them to requirements.txt.
- Secrets go in `.env` only; never commit keys. Add new keys to `.env.example`.
- Keep it simple: no frameworks, databases, or build steps unless asked.
- Run the app and load `/` with every profile before calling a task done.

## Product rules (never break these)
- Never present a check-in spot or coverage as guaranteed; say "estimate" or "best chance."
- Never contact emergency services automatically. Alerts go to the user's contact and point to official emergency options.
- All analysis runs before the trip. On the trail, the hiker only sends a plain text.
- Show an as-of date on anything from the carrier catalog.
- Never push a phone upgrade. Recommend the cheapest thing that works, including "don't buy anything."
