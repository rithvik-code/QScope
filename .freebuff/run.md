# QScope frontend dev server

This thread's worktree is the main checkout (`C:\Users\Rithvik\OneDrive\Documents\QScope`), so there is nothing to copy from another worktree.

## Reproduce the artifacts

- Dependencies are already installed in this worktree: `frontend/package-lock.json` is present and `frontend/node_modules` exists.
- Built artifacts are already present: `frontend/dist/index.html` exists. The frontend was built from this worktree.
- No `.env.local` exists and none is needed for the frontend dev server. The Vite dev server proxies `/api` and `/ws` to the Python API target.

## Run the server

From `frontend/`:

```powershell
# default port 5173; the Python API must be reachable for /api and /ws to work
cd frontend
npm run dev
```

Useful overrides:

- Different port: `cd frontend && node node_modules/vite/bin/vite.js --port <port>`
- Python API not on the default `http://127.0.0.1:8000`: set `QSCOPE_API` in the environment before starting, or pass `--port` and adapt the proxy target. The Vite config reads `process.env.QSCOPE_API ?? "http://127.0.0.1:8000"`.

The frontend computes nothing; it renders what the Python engine returns. If the API is not running, the interface still opens but will show empty states and API errors for run-dependent panels.
