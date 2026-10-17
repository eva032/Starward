# Starward

Predicts where on a hike your phone can text by satellite, recommends the cheapest setup that covers your check-ins, and alerts an emergency contact if you miss one.

**Track C runs on localhost** (no Render/Railway required for the demo).

## Localhost setup

```bash
cd Starward
python -m venv venv
source venv/bin/activate        # Windows PowerShell: venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env            # optional; Demo Mode works with empty Photon keys
python app.py                   # http://127.0.0.1:5000
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000). You should see a **Demo Mode** badge until `PHOTON_KEY` is set (coverage stays simulated until Track A ships real passes; SMS is not sent until Track D wires Photon delivery).

### Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `FLASK_SECRET_KEY` | No | Session signing (a default is used if unset) |
| `PORT` | No | Server port (default `5000`) |
| `PHOTON_KEY` | No | Track D: real SMS. Empty = Demo Mode |
| `BASE_URL` | No | Public URL for Photon webhooks |

Secrets belong in `.env` only (gitignored). Never commit API keys.

### Photon webhooks on localhost (Track D)

Incoming SMS hits `POST /webhook/photon`. Flask on `127.0.0.1` is not reachable from the public internet, so Track D needs a tunnel (e.g. `ngrok http 5000`) and `BASE_URL` pointed at that URL. Track C does not implement that tunnel; sharing and missed-alert preview work in Demo Mode without it.

## Demo script (≈2 minutes)

1. Open `http://127.0.0.1:5000` — confirm **Demo Mode** banner (simulated terrain; no SMS sent).
2. Trail: Colchuck Lake. Date: tomorrow. Start: `09:00`.
3. Hiker: your name + a fake phone (`+1 555 111 2222`).
4. Phone: **Pixel 9** / Carrier: **Verizon** (verified Skylo SMS; partial route estimate; no purchase push).
5. Emergency contact: `+1 555 123 4567`.
6. Click **Generate trip plan**.
7. Show map colors (demo / simulated), three check-ins + windows, recommendation + sources.
8. Click **Share plan** — notice says **Message preview only — no SMS sent**.
9. Click **Preview a missed check-in alert** — draft only; no emergency services.
10. Optional: **AT&T / iPhone 13** (unsupported SMS); **T-Mobile Galaxy S25** (compatibility not verified — empty map services).

## What's fake right now

Everything external. No live satellite API, no real SMS, no database.

- **Trails** (`data/trails/*.json`, fallback in `data/__init__.py`): approximate Colchuck points with canopy / ridge flags.
- **Carriers** (`data/carriers.json`): four demo profiles + satellite service defs, as of `as_of`.
- **Phones / compatibility** (`data/phones.json`, `data/compatibility.json`): selectable models and verified ordinary-SMS records from official sources. Unknown combinations still generate a trip plan with an honest “not verified” status. Emergency SOS alone is never treated as Starward check-in SMS.
- **Coverage** (`coverage.py`): openness from canopy; optional `trip_date` / `start_time` shift check-in clocks. Real orbits are Track A.
- **Recommendation** (`recommend.py`): `covered` / `add_service` / `not_compatible`. Catalog truth is Track B.
- **Guardian** (`guardian.py`): in-memory plans; prints to the console. Real Photon is Track D.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Trip form; shows plan if one is in session |
| `POST` | `/plan` | Validate inputs and generate plan |
| `POST` | `/share` | Share (or simulate) plan with contact |
| `POST` | `/simulate/missed` | Preview missed check-in alert |
| `POST` | `/webhook/photon` | Incoming SMS (Track D / tunnel) |
| `GET` | `/health` | Liveness + fake_mode flag |

## Tests

```bash
source venv/bin/activate
python -m unittest discover -s tests -v
```

## Owners

| Owner | Area | Files |
|---|---|---|
| A | Geo + space | `coverage.py`, trail JSON |
| B | Recommendation | `recommend.py`, `data/carriers.json` |
| C | Web + localhost | `app.py`, `templates/` |
| D | Photon guardian | `guardian.py` |

See `AGENTS.md` for contracts and product rules.
