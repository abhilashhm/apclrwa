# APC Layout Residents Welfare Association

Community portal for APC Layout, Thindlu, Bengaluru – 560097.

## Local development

The frontend is a React/Vite app and the API is a FastAPI service backed by
SQLite. Run the API and frontend in separate terminals:

```powershell
$env:APCLRWA_ENV = "development"
$env:APCLRWA_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
python -m uvicorn backend.auth:app --host 127.0.0.1 --port 8000
```

If the local Python environment is not already provisioned, install the local
server dependencies from `requirements.local.txt`.

```powershell
npm install
npm run dev
```

Create the first committee account interactively. The password is never a
command-line argument:

```powershell
$env:APCLRWA_ENV = "development"
$env:APCLRWA_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
python -m backend.cli create-admin
```

For production, set `APCLRWA_ENV=production`, configure explicit HTTPS origins
with `APCLRWA_CORS_ORIGINS`, and run behind HTTPS with Uvicorn proxy settings
that trust only the real proxy addresses. Production startup rejects insecure
cookie configuration.

## Data migration

Operational data is server-backed in SQLite. Existing browser data is not
silently imported. After signing in as a committee user, open **Data
Migration**, preview the detected legacy collections, review validation
warnings, and explicitly confirm the import. The original browser data remains
until the separate cleanup action is confirmed.

The public endpoint returns only public events. Resident-only events are
filtered server-side and are available only through an authenticated portal
snapshot.

Resident records include owner/tenant status, an optional private profession,
and a private property-owner name for tenant records. A resident can be listed
on the public professional directory only when the committee records explicit
consent. The homepage also separates official/public emergency contacts from
association-maintained numbers.

## Checks

```powershell
npm run build
python -m compileall backend
```

`data/` and generated database backups are local operational data and are not
tracked by Git.

## Cloudflare Worker deployment

The repository includes a separate Cloudflare Worker + D1 path in
`cloudflare/`. Local development continues to use the SQLite FastAPI service;
the Worker path does not import `sqlite3` or read local Tally files. Build the
frontend before starting the Worker preview:

```powershell
npm run build
uv run pywrangler dev --local --port 8787 --var APCLRWA_ENV:development --var APCLRWA_COOKIE_SECURE:false
```

See [docs/CLOUDFLARE_DEPLOYMENT.md](docs/CLOUDFLARE_DEPLOYMENT.md) for D1
migrations, bindings, usage checks, and the Tally JSON upload workflow. The
older browser-data import still requires local SQLite development.

The committee portal includes **Accounting Controls** for the normalized
chart-of-accounts, journal, audit and financial-year close foundation. Its D1
tables are created by `migrations/0003_accounting.sql`; historic Tally rows
remain in the separate imported ledger until a later, explicitly approved
mapping.

The deployed Worker is available at
`https://apclrwa.apclrwa-community-portal.workers.dev`. The previous
`https://apclrwa-community-portal.apclrwa-community-portal.workers.dev` address
is retained temporarily as a fallback. A committee admin must be bootstrapped
into the remote D1 database once by following the private-password steps in the
deployment document.
