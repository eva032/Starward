# Starward

Predicts where on a hike your phone can text by satellite, recommends the cheapest setup that covers your check-ins, and alerts an emergency contact if you miss one.

Runs on localhost; no hosting needed for the demo.

## Localhost setup

```bash
cd Starward
python -m venv venv
source venv/bin/activate        # Windows PowerShell: venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env            # optional; Demo Mode works with empty bridge keys
# One-time bridge setup (for live SMS): cd bridge && cp .env.example .env && npm install
./start.sh                      # Flask on :5001 + Photon bridge on :8787 (Ctrl+C stops both)
```

Or run services separately:

```bash
python app.py                   # http://127.0.0.1:5000
# If port 5000 is busy (common on macOS when AirPlay Receiver is on):
PORT=5001 python app.py         # http://127.0.0.1:5001
```

Open [http://127.0.0.1:5001](http://127.0.0.1:5001) when using `./start.sh`, or [http://127.0.0.1:5000](http://127.0.0.1:5000) for the default `python app.py`. You'll see a **Demo Mode** badge until `BRIDGE_URL` is set. In Demo Mode, **Share plan** and missed-check-in alerts are message previews only — no SMS is sent. With the Photon bridge running and `BRIDGE_URL` / `BRIDGE_TOKEN` configured, outbound texts are sent for real.

### Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `FLASK_SECRET_KEY` | No | Session signing (a default is used if unset) |
| `PORT` | No | Server port (default `5000`) |
| `BRIDGE_URL` | No | Photon bridge base URL (e.g. `http://127.0.0.1:8787`). Empty = Demo Mode |
| `BRIDGE_TOKEN` | No | Shared bearer token with `bridge/.env` |

Secrets belong in `.env` only (gitignored). Never commit API keys.

### Photon bridge (Track D / live SMS)

The `bridge/` app talks to Spectrum Cloud and exposes `POST /send`. Flask calls it for outbound texts; the bridge posts inbound texts to `POST /webhook/photon`. No ngrok needed on localhost.

```bash
cd bridge
cp .env.example .env   # set PROJECT_ID, PROJECT_SECRET, BRIDGE_TOKEN
npm install
npm run start          # http://127.0.0.1:8787
```

In the repo-root `.env`, set the same `BRIDGE_TOKEN` and `BRIDGE_URL=http://127.0.0.1:8787`. Recipients must be Spectrum users on your Photon project (`photon spectrum users add --phone +1…`).

## Demo script (about 2 minutes)

1. Open `http://127.0.0.1:5000` and point out the **Demo Mode** badge (no SMS sent until the bridge is configured).
2. Trail: **Lake Serene**. Date: tomorrow. Start: `09:00`.
3. Hiker: your name and a fake phone (`+1 555 111 2222`).
4. Phone: **Pixel 9**, carrier: **Verizon**. Click **Generate trip plan**.
5. Show the map: Mount Index can block Skylo (low in the southern sky) at some spots. The recommendation may suggest a T-Satellite month as an estimate — confirm eligibility before buying.
6. Toggle **+ T-Satellite** on the map to preview the difference (estimate only).
7. Switch to **Mount Si** or **Snow Lake** for a “good chance / don’t buy” style outcome when the estimate already covers check-ins.
8. **Share plan** — in Demo Mode, a message preview only; with the bridge live, the plan is sent to the contact. **Preview a missed check-in alert** drafts (or sends, if live) the alert to the contact (never emergency services).
9. Optional: add people under **Who's coming?** for a group recommendation on the same page; open `/pitch/tmobile` for the T-Mobile pitch.

## What's real and what's estimated

- **Trails** (`data/trails/*.json`, built by `tools/build_trail.py`): Colchuck Lake, Lake Serene, Mount Si, Snow Lake (Mailbox Peak once built). Real routes from OpenStreetMap; elevation and per-point terrain horizons from the Copernicus DEM. Tree canopy is a hand estimate.
- **Satellite windows** (`orbits.py`): real orbit data from CelesTrak (Starlink direct-to-cell satellites, Globalstar), cached in `data/tle/`; refresh with `python tools/fetch_tles.py` close to the trip. Skylo is modeled as one geostationary satellite near 98° W (an assumption).
- **Coverage** (`coverage.py`): sky openness from canopy and terrain; check-in times from a hiking-pace estimate; windows from orbits when a trip date is given.
- **Catalog and recommendation** (`data/*.json`, `recommend.py`): Track B's carrier catalog, situation inference from phone + carrier, per-phone and household recommendations, as of the catalog date.
- **Phones list and official sources** (`data/phones.json`, `data/compatibility.json`, `data/compat.py`): Track C's phone picker and source citations. Apple Messages via Satellite is not treated as verified Starward check-in SMS; T-Satellite purchase suggestions may ask you to confirm eligibility.
- **Guardian** (`guardian.py` + `bridge/`): in-memory plans; Demo Mode prints previews to the console; live mode sends via the Photon bridge when `BRIDGE_URL` is set.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Trip form; shows the plan if one is in session |
| `POST` | `/plan` | Validate inputs and generate the plan |
| `POST` | `/share` | Share the plan with the contact (preview in Demo Mode; live via bridge when configured) |
| `POST` | `/simulate/missed` | Preview or send a missed-check-in alert (same Demo/live rules) |
| `GET` | `/household` | Redirects to `/` (group planning is on the main form under **Who's coming?**) |
| `GET` | `/pitch/tmobile` | T-Mobile track pitch page |
| `POST` | `/webhook/photon` | Incoming SMS from the Photon bridge |
| `GET` | `/health` | Liveness + `fake_mode` / live flag |

## Tests

```bash
python -m pytest -q
```

## Owners

| Owner | Area | Files |
|---|---|---|
| A | Geo + space | `coverage.py`, `route.py`, `terrain.py`, `orbits.py`, `tools/`, `data/trails/`, `data/tle/` |
| B | Recommendation | `recommend.py`, `data/__init__.py`, `data/carriers.json` and other catalogs, `pitch/` |
| C | Web + localhost | `app.py`, `templates/index.html`, `data/phones.json`, `data/compatibility.json`, `data/compat.py` |
| D | Photon guardian | `guardian.py`, `bridge/` |

See `AGENTS.md` for contracts and product rules.
