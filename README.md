# Starward

Predicts where on a hike your phone can text by satellite, recommends the cheapest setup that covers your check-ins, and alerts an emergency contact if you miss one.

Runs on localhost; no hosting needed for the demo.

## Localhost setup

```bash
cd Starward
python -m venv venv
source venv/bin/activate        # Windows PowerShell: venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env            # optional; Demo Mode works with empty Photon keys
python app.py                   # http://127.0.0.1:5000
# If port 5000 is busy (common on macOS when AirPlay Receiver is on):
PORT=5001 python app.py         # http://127.0.0.1:5001
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000). You'll see a **Demo Mode** badge until `PHOTON_KEY` is set (SMS is not sent until Track D wires Photon delivery).

### Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `FLASK_SECRET_KEY` | No | Session signing (a default is used if unset) |
| `PORT` | No | Server port (default `5000`) |
| `PHOTON_KEY` | No | Track D: real SMS. Empty = Demo Mode |
| `BASE_URL` | No | Public URL for Photon webhooks |

Secrets belong in `.env` only (gitignored). Never commit API keys.

### Photon webhooks on localhost (Track D)

Incoming SMS hits `POST /webhook/photon`. Flask on `127.0.0.1` is not reachable from the internet, so Track D needs a tunnel (e.g. `ngrok http 5000`) and `BASE_URL` pointed at it. Sharing and the missed-alert preview work in Demo Mode without it.

## Demo script (about 2 minutes)

1. Open `http://127.0.0.1:5000` and point out the **Demo Mode** badge (no SMS sent).
2. Trail: **Lake Serene**. Date: tomorrow. Start: `09:00`.
3. Hiker: your name and a fake phone (`+1 555 111 2222`).
4. Phone: **Pixel 9**, carrier: **Verizon**. Click **Generate trip plan**.
5. Show the map: Mount Index blocks the Pixel's satellite (Skylo sits low in the southern sky) at the Bridal Veil Falls junction. The recommendation explains why and what a $10 T-Satellite month would add.
6. Toggle **+ T-Satellite** on the map to preview the difference.
7. Switch to **Mount Si** or **Snow Lake**: "You're set. Don't buy anything."
8. **Share plan** shows a message preview only; **Preview a missed check-in alert** drafts the alert to the contact (never emergency services).
9. Optional: **Whole household** (group recommendation and cart) and **T-Mobile pitch**.

## What's real and what's estimated

- **Trails** (`data/trails/*.json`, built by `tools/build_trail.py`): Colchuck Lake, Lake Serene, Mount Si, Snow Lake (Mailbox Peak once built). Real routes from OpenStreetMap; elevation and per-point terrain horizons from the Copernicus DEM. Tree canopy is a hand estimate.
- **Satellite windows** (`orbits.py`): real orbit data from CelesTrak (Starlink direct-to-cell satellites, Globalstar), cached in `data/tle/`; refresh with `python tools/fetch_tles.py` close to the trip. Skylo is modeled as one geostationary satellite near 98° W (an assumption).
- **Coverage** (`coverage.py`): sky openness from canopy and terrain; check-in times from a hiking-pace estimate; windows from orbits when a trip date is given.
- **Catalog and recommendation** (`data/*.json`, `recommend.py`): Track B's carrier catalog, situation inference from phone + carrier, per-phone and household recommendations, as of the catalog date.
- **Phones list and official sources** (`data/phones.json`, `data/compatibility.json`, `data/compat.py`): Track C's phone picker and source citations.
- **Guardian** (`guardian.py`): in-memory plans, printed to the console. Real Photon is Track D.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Trip form; shows the plan if one is in session |
| `POST` | `/plan` | Validate inputs and generate the plan |
| `POST` | `/share` | Share (preview) the plan with the contact |
| `POST` | `/simulate/missed` | Preview the missed check-in alert |
| `GET`/`POST` | `/household` | Whole-household recommendation and cart |
| `GET` | `/pitch/tmobile` | T-Mobile track pitch page |
| `POST` | `/webhook/photon` | Incoming SMS (Track D / tunnel) |
| `GET` | `/health` | Liveness + fake_mode flag |

## Tests

```bash
python -m pytest -q
```

## Owners

| Owner | Area | Files |
|---|---|---|
| A | Geo + space | `coverage.py`, `route.py`, `terrain.py`, `orbits.py`, `tools/`, `data/trails/`, `data/tle/` |
| B | Recommendation | `recommend.py`, `data/__init__.py`, `data/carriers.json` and other catalogs, `templates/household.html`, `pitch/` |
| C | Web + localhost | `app.py`, `templates/index.html`, `data/phones.json`, `data/compatibility.json`, `data/compat.py` |
| D | Photon guardian | `guardian.py` |

See `AGENTS.md` for contracts and product rules.
