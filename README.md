# Learning notebook

Notes, links and interview questions per topic. Write locally, read-only on Render.

## Run locally (editing on)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
.\run_local.bat
```

Open http://127.0.0.1:8000. All data is saved to `data/notes.json`.

## Publish to Render

1. Add notes locally.
2. Commit and push the data file:

   ```powershell
   git add data/notes.json
   git commit -m "Update notes"
   git push
   ```
3. Render redeploys automatically and shows the new notes.

Render settings:

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn -w 2 -k uvicorn.workers.UvicornWorker main:app`

Do not set `APP_MODE` on Render. Without it the site is read-only.
