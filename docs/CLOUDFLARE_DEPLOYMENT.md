# Cloudflare deployment

## Current status

The APCLRWA Worker and D1 database were updated and verified on **October 23,
2026**. The existing GitHub Pages workflow is not used by this migration and
remains disabled.

- Worker: `apclrwa-community-portal`
- URL: `https://apclrwa-community-portal.apclrwa-community-portal.workers.dev`
- D1 database: `apclrwa-portal`
- D1 database ID: `4abbc8f9-2951-40a7-bdd5-25a2d21c7963`
- Deployment version ID: `2839f99a-2a7e-4436-885c-3d325956f6f5` (October 23, 2026)
- Applied migrations: `0001_initial.sql`, `0002_password_scheme.sql`, `0003_accounting.sql`

The public/static surface is live and independently checked. Remote D1 has an
active committee account (`abhilashhm`). Its password is not available from the
repository, and the existing account was left unchanged.

The implementation keeps local development unchanged:

- `backend/auth.py` and `backend/portal.py` remain the SQLite/FastAPI path.
- `cloudflare/app.py` exposes the same high-value API paths over async D1.
- `cloudflare/d1.py` stores portal collections as versioned JSON chunks below
  D1's per-row limit and uses D1 batch transactions for writes.
- `cloudflare/domain.py` contains the portable validation, resident binding,
  AMC transfer, payment, and receipt rules used by the Worker path.
- `cloudflare/worker.py` serves the FastAPI API first and proxies the Vite
  build through the `ASSETS` binding.
- Browser migration remains local-only in the Worker and returns an explicit
  `501`. Tally snapshots use a separate authenticated bounded JSON upload at
  `/api/admin/tally-import/upload` (the `/apply` alias accepts the same envelope)
  and do not require R2 for the current snapshot size.
- Normalized accounting endpoints and the **Accounting Controls** committee UI
  use `migrations/0003_accounting.sql`, which is now applied to remote D1 and
  deployed with Worker version `2839f99a-2a7e-4436-885c-3d325956f6f5`.

## Cloudflare shape

The Worker serves the Vite build through Workers Static Assets and handles
`/api/*` through a Python Worker FastAPI entry point. D1 is bound as `DB`; the
frontend assets are bound as `ASSETS`. This follows Cloudflare's documented
FastAPI/Python Workers and Static Assets pattern. The standard-library
`sqlite3` connection and local `data/` filesystem remain local-only.

Relevant Cloudflare documentation:

- Workers pricing: <https://developers.cloudflare.com/workers/platform/pricing/>
- Pages limits: <https://developers.cloudflare.com/pages/platform/limits/>
- Python Workers/FastAPI: <https://developers.cloudflare.com/workers/languages/python/packages/fastapi/>
- D1 from Python Workers: <https://developers.cloudflare.com/d1/worker-api/d1-database/>
- Workers Static Assets: <https://developers.cloudflare.com/workers/static-assets/>

## Published free-plan limits

The current Cloudflare documentation lists the following relevant allowances:

- Workers: 100,000 requests per day on Free; 10 ms CPU time per invocation.
- D1: 5 million rows read per day, 100,000 rows written per day, and 5 GB
  total storage on Free.
- Pages: 500 builds per month, one concurrent build, 20,000 files per site,
  25 MiB maximum per asset, and 100 custom domains per project on Free.
- Static assets are served through Cloudflare's asset network; Worker/API
  requests still count against Worker limits.

This portal's expected small-community traffic should be well below those
published limits if reports are not rebuilt with unbounded full-table scans and
images are kept small. That is an estimate, not an account-usage result.

## Configuration files

- `wrangler.jsonc`: Worker name, Python entrypoint, `dist/` assets, `ASSETS`,
  the created D1 binding, and production variables.
- `migrations/0001_initial.sql`: users, sessions, authentication attempts,
  portal revision/collection chunks, idempotency keys, and the database-side
  optimistic-concurrency/rate-limit guards.
- `pyproject.toml`: FastAPI/Pydantic runtime dependencies plus
  `workers-py`/`workers-runtime-sdk` development dependencies.
- `cloudflare/bootstrap_admin.py`: generates a PBKDF2-hashed committee-admin
  INSERT without writing the password to the SQL file or terminal output.
  The Worker-compatible PBKDF2 profile uses 100,000 SHA-256 iterations.

## One-time remote committee bootstrap

First inspect the remote users table so you do not create a duplicate account:

```powershell
npx wrangler d1 execute apclrwa-portal --remote --command "SELECT username, role, active FROM users;"
```

Only run the bootstrap when you have confirmed that no authorized committee
account exists. Enter the chosen password directly in a terminal (do not paste
it into chat or commit the generated file):

```powershell
python cloudflare/bootstrap_admin.py > cloudflare-admin.sql
npx wrangler d1 execute apclrwa-portal --remote --file cloudflare-admin.sql
Remove-Item cloudflare-admin.sql
```

The generated file contains only the salted password hash and the account
INSERT. It is ignored by Git and should be deleted immediately after the
remote D1 command succeeds.

## Local Worker checks

Install `uv` and Node.js, then run:

```powershell
npm install
npm run build
uv run pywrangler dev --local --port 8787 --var APCLRWA_ENV:development --var APCLRWA_COOKIE_SECURE:false
```

The Worker dev server is expected at `http://localhost:8787`. A local D1
binding is created by Wrangler from the migration files. Before using a real
database, verify:

```powershell
curl http://localhost:8787/api/health
curl http://localhost:8787/api/public/content
```

The local SQLite FastAPI checks remain required as well:

```powershell
python -m compileall backend cloudflare
git diff --check
```

## Usage check and deployment record

Cloudflare's published documentation does not expose this account's current
month consumption. An authenticated Cloudflare dashboard or API connection is
required to check actual Workers, D1, Pages, R2, and account/project quotas.
That access was not available in this workspace, so no claim is made that the
account is currently below its free-tier usage.

The deployment gate was completed before resource creation. The account had
authenticated Wrangler access, the D1 database and migrations were created,
and the Worker preview passed its public and protected smoke checks. The
following commands remain useful for a future redeploy:

1. Check current-month usage and the account's existing Pages/Workers/D1
   project counts against the published limits.
2. Apply pending migrations and run the Worker local/preview smoke tests.
3. Enable/configure R2 only if future raw workbook retention or larger import
   batches require it; the current normalized `data/tally-import.json` snapshot
   is uploaded directly by a committee member and is not committed or deployed.

The deployed homepage menu was verified in the browser in this order: Home,
Our Community, Directory, Contacts, Updates, Transparency. The public page
loads, `/api/health` returns `ok`, and the HTML references the built frontend
asset. Remote D1 still contains Tally import `TALLY-2026-10-04-v1` (489 source
rows; 608 ledger rows including transfers). The October 23 frontend deployment
did not modify D1. The committee-only workflows were not re-tested in this
browser session because it was not signed in.

The Worker/D1 deployment is complete. The Worker accepts the normalized Tally
snapshot through the authenticated JSON upload route, and the normalized
accounting endpoints are available to committee sessions. Only the old
browser migration routes remain unavailable in production.

## Tally snapshot upload

With the current Worker deployed and the `abhilashhm` committee account
available:

1. Open the deployed Worker URL, not the localhost development URL.
2. Sign in as a committee member.
3. Open **Data Migration**.
4. Choose **Upload JSON to Cloudflare**.
5. Select the existing local file `data/tally-import.json`.
6. Confirm the success message and review **Reports** for the imported ledger,
   opening balances, and Tally reconciliation.

The separate **Accounting Controls** section is for new verified journal
postings, audit events, and annual period controls. It is not a conversion tool
for historic Tally rows.

The Data Migration panel detects the deployment through the same-origin
`/api/admin/tally-import` capability response. The local API exposes that route
(including a 404 when its snapshot file is absent), while the Cloudflare Worker
returns 501 because it cannot read the local filesystem. The panel therefore
keeps **Apply Tally import** available on localhost and hides it on the Worker;
the JSON upload action remains available in both environments.

The upload validates the snapshot server-side, accepts only posted book ledger
entries, appends new stable IDs without overwriting existing records, rejects
conflicts, preserves the original local file, and treats a repeated identical
`importId` as idempotent.
