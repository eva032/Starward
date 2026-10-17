# Starward

Predicts where on a hike your phone can text by satellite, recommends the cheapest setup that covers your check-ins, and alerts an emergency contact if you miss one.

## Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows PowerShell: venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py                   # http://localhost:5000
```

Copy `.env.example` to `.env` when real keys are needed. None are used yet.

## What's fake right now

Everything. No external APIs, no database.

- **Trail** (`data.py`): ~15 approximate points for Colchuck Lake, each with made-up elevation, canopy (0–1), and a `south_blocked` flag for the ridge in the middle.
- **Profiles and services** (`data.py`): 4 mock phone/carrier setups and 3 satellite services with fake prices, as of `CATALOG_AS_OF`.
- **Coverage** (`coverage.py`): openness = 1 − canopy, dropped to 0.1 under the ridge when every service is blocked by it. Check-ins sit at 1/4, 1/2, and 3/4 of the route with fake times and windows.
- **Recommendation** (`recommend.py`): picks one of `covered`, `add_service`, or `not_compatible` by rerunning coverage with T-Satellite added.
- **Guardian** (`guardian.py`): plans and check-ins live in memory and print to the console. Nothing is sent.

Endpoints: `GET /?profile=<id>`, `POST /share`, `POST /simulate/missed`, `POST /webhook/photon`, `GET /health`.

## Owners

| Owner | Area | Files |
|---|---|---|
| A | Geo + space | coverage.py, data.py `TRAIL` |
| B | Recommendation | recommend.py, data.py profiles/services |
| C | Web app + deploy | app.py, templates/ |
| D | Photon guardian + Grok | guardian.py |

See `AGENTS.md` for contracts and rules.
