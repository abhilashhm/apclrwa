# Production readiness snapshot

Updated 2026-10-09 after importing the provided Tally exports locally.

## What is operational in this workspace

- The React/Vite frontend builds with TypeScript checks (`npm run build`).
- Committee and resident authentication and sessions run through the local FastAPI service and SQLite. Production cookie, HTTPS, explicit-origin, and SQLite login-throttling checks are enforced by configuration.
- Operational portal collections are stored in SQLite behind role-checked, revision-checked API endpoints. Resident data is server-filtered; passwords are hashed server-side and are never returned to the frontend.
- Resident payment claims use server-side idempotency keys. Committee approval creates the associated posted receipt atomically rather than writing browser-local records.
- Browser/localStorage data is available only through an explicit committee migration preview/import flow. The server validates the import, strips legacy credentials, rejects conflicts, and creates a private pre-import database backup.
- `backend/tally_import.py` reads the supplied Excel exports and produces `data/tally-import.json`; the private `data/` directory is excluded from Git.
- Locally, a committee user can explicitly apply the configured snapshot through `/api/admin/tally-import/apply`. In Cloudflare, the same normalized JSON is uploaded through `/api/admin/tally-import/upload`; the Worker merges imported rows by stable IDs and presents Tally cash/bank reconciliation and source-ledger control checks in Reports.
- The import is repeatable and does not edit source workbooks. Bank and cash book source totals reconcile to their reported closing balances.

## Not production-ready yet

- The SQLite portal store is authoritative for the portal, but it is still a JSON-collection store rather than a normalized immutable double-entry journal. It does not update Tally.
- The source workbooks and generated import JSON remain private local files and are not committed or deployed. The normalized JSON snapshot can be uploaded explicitly by a committee member to the Cloudflare Worker, which validates and appends it into D1 without requiring access to the local filesystem.
- Opening cash differs by ₹45 from the prior balance sheet dated 2026-03-29. The March 31 cash count/closing balance has not been supplied.
- AGM ledger voucher details omit ₹800 present in the cash book/closing balance. Do not infer its payee or purpose from the incomplete row.
- The current FY AMC detail exports only run through July and total ₹18,000, while the complete bank/cash books through 2026-10-04 show ₹41,000. This is an incomplete supporting-export gap, not a bank/cash roll-forward difference.
- Existing browser data may already contain manually entered items. The importer only deduplicates exact stable IDs and does not certify semantic duplicates against prior manual rows.
- Immutable double-entry journals, verified bank statement matching, append-only business audit logs, period closing, operational backup/restore procedures, deployment secrets, and production hosting remain outstanding. Database backups are currently created before explicit browser/Tally imports.

## Tally controls from supplied books

| Book | Opening | Receipts | Payments | Tally closing | Calculated closing | Difference |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Bank | ₹46,630 | ₹2,68,513 | ₹2,92,003 | ₹23,140 | ₹23,140 | ₹0 |
| Cash | ₹8,905 | ₹3,01,514 | ₹2,83,025 | ₹27,394 | ₹27,394 | ₹0 |

The data import contains 489 records (366 for FY 2026–27 and 123 supporting FY 2025–26 records). The standalone monthly and ledger exports are used only as control sources where they overlap the books; they are not double-imported as additional transactions.

## Production migration priorities

1. Establish and back up a canonical server-side accounting database; import previewed records with a recoverable batch ID and stable legacy IDs.
2. Resolve opening cash and the missing AGM voucher details with the source records; obtain the missing AMC support exports if needed.
3. Implement a chart of accounts, balanced immutable journal entries, reversals, posting permissions, and an append-only audit log.
4. Move residents, membership/AMC, donations, expenses, cash/bank, and fixed deposits into typed backend APIs in reviewable slices.
5. Add bank statement upload/matching, reconciliations, period/FY close controls, backup/restore, and reports derived from the journal.
6. Configure secure production hosting, secrets, TLS, cookie settings, monitoring, and documented recovery procedures before real operational deployment.

See [BACKEND_ACCOUNTING_MIGRATION_PLAN.md](BACKEND_ACCOUNTING_MIGRATION_PLAN.md) for the staged proposal and cutover controls.
