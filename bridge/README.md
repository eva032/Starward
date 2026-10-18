# Starward Photon bridge

Spectrum Cloud iMessage bridge for Starward. Flask posts outbound SMS to `POST /send`; inbound texts are forwarded to Flask `POST /webhook/photon`.

## Setup

```bash
cp .env.example .env
# fill PROJECT_ID, PROJECT_SECRET, BRIDGE_TOKEN (same token as repo-root .env)
npm install
npm run start   # http://127.0.0.1:8787
```

In the repo-root `.env` set `BRIDGE_URL=http://127.0.0.1:8787` and the same `BRIDGE_TOKEN`.
