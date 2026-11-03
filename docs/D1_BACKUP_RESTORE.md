# D1 backup and restore drill

This procedure creates a point-in-time SQL export of the production D1 database,
restores it into a disposable local D1 store, and verifies the schema and core
portal/accounting rows. It does not modify the production database.

## Export

Run from the repository root with authenticated Wrangler access:

```powershell
$backupRoot = Join-Path $env:LOCALAPPDATA "Temp\opencode\apclrwa-d1-drill"
New-Item -ItemType Directory -Force $backupRoot | Out-Null
$backup = Join-Path $backupRoot "apclrwa-portal-$(Get-Date -Format yyyyMMdd-HHmmss).sql"
npx wrangler d1 export apclrwa-portal --remote --output $backup --skip-confirmation
```

Keep the export outside Git. It contains private resident, session, and
authentication data. Restrict access to the operator account and remove it when
the recovery exercise is complete.

## Restore into a disposable destination

Use a fresh persistence directory for every drill:

```powershell
$restoreRoot = Join-Path $backupRoot "restore-$(Get-Date -Format yyyyMMdd-HHmmss)"
$prepared = Join-Path $backupRoot "restore-input.sql"
python scripts/d1_restore_drill.py --input $backup --output $prepared
npx wrangler d1 execute apclrwa-portal --local --persist-to $restoreRoot --file $prepared --yes
```

The local destination is disposable and is not the production D1 binding. Do
not run a restore command with `--remote` unless an authorized recovery has been
approved and the destination has been explicitly confirmed. The preparation
step is needed when a portal collection chunk is larger than Wrangler's local
single-statement limit; it rewrites only that private SQL export and does not
alter production.

## Verification

```powershell
npx wrangler d1 execute apclrwa-portal --local --persist-to $restoreRoot --command "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name;" --json
npx wrangler d1 execute apclrwa-portal --local --persist-to $restoreRoot --command "SELECT COUNT(*) AS users FROM users; SELECT COUNT(*) AS portal_versions FROM portal_collection_versions; SELECT COUNT(*) AS periods FROM accounting_periods;" --json
```

Record the export timestamp, restore destination, row counts, and the operator
in the association's private operations log. A successful drill must show the
`users`, `portal_collection_versions`, and `accounting_periods` tables and the
expected non-zero production counts. The restored copy must never be exposed
through the public Worker.

## Recovery notes

- Export before schema changes, bulk imports, or an authorized recovery.
- Preserve the original export as evidence until the restored destination has
  been checked.
- D1 export/import is a database recovery copy; it does not separately archive
  Cloudflare Worker code, configuration, deployment secrets, or external Google
  Photos albums.
- After a real recovery, redeploy the intended Worker version, verify `/api/health`,
  sign in through the committee account, review Data Migration and Accounting
  Controls, and record the verification results.
