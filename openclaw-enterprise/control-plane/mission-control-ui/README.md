# Mission Control UI

Pixel-art office canvas for OpenClaw agents.

## Run locally

Option 1:
- Open `index.html` directly in browser.

Option 2 (recommended):
- Start a static server from this folder.
- Example: `python -m http.server 4173`
- Open `http://127.0.0.1:4173`

## API

- Default API base: `http://127.0.0.1:8000`
- Editable in top-right control bar.
- Polling interval: every 5 seconds.

Expected endpoints:
- `GET /runtime/permission/stats`
- `GET /runtime/permission/recent?limit=20`
