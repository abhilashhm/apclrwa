# Current architecture and Phase 1 findings

## Scope and source of truth

This document describes the repository as inspected on branch `initial`. The app is a community portal with a React/Vite frontend and a local FastAPI/SQLite backend; it is not yet a deployed production accounting system. The implementation is concentrated in `src/App.tsx` and `src/styles.css`, with API/state modules in `src/api.ts`, `src/portalStore.ts`, `src/portalTypes.ts`, and `src/legacyMigration.ts`. The entry point is `src/main.tsx`, and `index.html` supplies the document metadata and `/logo1.svg` favicon. `package.json` defines a Vite development server and a production build (`tsc -b && vite build`). Dependencies are React 19, TypeScript, Vite, and `qrcode`.

The FastAPI service in `backend/auth.py` now provides SQLite users/sessions, committee and resident authentication, secure session-cookie policy, password-change handling, origin/transport checks, and durable SQLite-backed login throttling. `backend/portal.py` and `backend/portal_models.py` provide the authoritative operational portal API and bounded data contracts. `auth.py` includes the portal router and initializes its schema on startup. The UI has a public home page, backend login, resident portal, password-change view, committee portal, and explicit legacy-data migration flow.

`backend/tally_import.py` reads the Tally `.xls` exports from `C:\Tally.ERP9` without changing them, normalizes the bank/cash books, and writes a private `data/tally-import.json` snapshot. `data/` is gitignored. Locally, a committee user explicitly applies that snapshot through `/api/admin/tally-import/apply`. In Cloudflare, a committee user uploads the normalized snapshot through `/api/admin/tally-import/upload`; the Worker validates it, deduplicates stable IDs, preserves existing records, and stores the reconciliation in D1. The importer remains a historic ledger bridge. New verified postings can use the separate normalized journal/audit/period-control layer under `/api/admin/accounting/`; imported Tally rows are not silently converted into journals.

## UI and state organization

`src/App.tsx` contains the landing page, theme toggle, office-bearer display, events, login, resident workflows, admin forms, report generation, and the committee dashboard. `src/portalStore.ts` keeps the authenticated portal snapshot in memory, serializes mutations, handles stale revisions, and refreshes after conflicts. `src/styles.css` contains the app-wide visual system, responsive rules, admin/resident styles, and theme-specific overrides. The shared theme preference and selected financial year remain in `localStorage`; operational collections are read and written through the API.

The public page loads `/api/public/content`, whose server response excludes residents-only events and includes only explicitly consented professional-directory rows plus separately labeled official/public and association-maintained contacts. Resident portal snapshots are role-filtered on the server: residents receive their own profile, payment claims, posted receipt-like rows, rates, public/private authenticated updates, and office-bearers; committee users receive the full operational snapshot, including private profession and tenant property-owner fields. Committee login and resident login use an HTTP-only backend session cookie. Resident temporary passwords must be changed through `/api/auth/password` before portal access. Resident UPI payment claims are server-persisted with idempotency keys; committee review and posted receipt creation are atomic in one database transaction. Bank/UPI settlement is still a manual verification process.

## Persisted browser data

The app uses these keys (all scoped to one browser profile, without multi-user synchronization):

| Key | Contents / use |
| --- | --- |
| `apclrwa_residents` | Legacy resident records detected only by the explicit committee migration flow; no longer an authoritative source |
| `apclrwa_pending_payments` | Legacy payment claims detected only by explicit migration; server claims are stored in SQLite |
| `apclrwa_admin_ledger` | Legacy ledger rows detected only by explicit migration; server ledger rows are stored in SQLite |
| `apclrwa_fixed_deposits` | Legacy FD records detected only by explicit migration |
| `apclrwa_opening_balances` | Legacy opening balances detected only by explicit migration |
| `apclrwa_expense_types` | Legacy expense categories detected only by explicit migration |
| `apclrwa_events` | Legacy community updates detected only by explicit migration |
| `apclrwa_office_bearers` | Legacy office-bearer details detected only by explicit migration |
| `apclrwa_theme` | Shared light/dark preference |
| `apclrwa_selected_fy` | Committee portal's selected FY |
| `apclrwa_tally_import_id` | Legacy local Tally marker; excluded from browser migration |
| `apclrwa_tally_reconciliation` | Legacy local reconciliation; excluded from browser migration |
| `apclrwa_admin_session`, `apclrwa_resident_session`, `apclrwa_resident_username` | Old demo routing flags; no longer used for authentication |

Legacy values are preserved until a committee member explicitly previews, validates, imports, and separately confirms cleanup. The server strips password and token fields, creates a private pre-import SQLite backup, rejects conflicting identities, and never treats legacy approval flags as verified accounting. Images are currently bounded and may remain as data URLs in the server collection; a managed media store is still a later improvement. Browser storage is not a reliable backup or a shared source of truth.

## Financial behavior currently present

- Membership is represented primarily by fields on the resident (`initialCharge`, `initialChargePaid`, `membershipPayment`); it is not consistently represented as a financial ledger transaction.
- A resident AMC/UPI submission is a pending claim. On committee approval, a Maintenance ledger row is appended. Contribution approval similarly appends a Collections row. Duplicate checks exist for these approval paths.
- Admin-entered donations, expenses, maintenance, and bank/cash transfers are stored as rows in one ledger array. Receipt/voucher-looking IDs are generated in the browser using timestamps or prefixes; they are not durable independent sequences.
- Bank and cash balances are calculated by folding posted ledger rows over editable opening balances. Fixed deposits are also applied to these displayed balances. No balanced journal lines are produced, and these calculated figures are not an accounting ledger.
- FY values use a derived April–March year label (for example `2026–27`); saved ledger years are included in the admin selector. Resident dues still rely on the prototype’s fixed AMC business rule and resident/maintenance rows; this is not a complete multi-year ageing system.
- Reports include Profit & Loss, income by ledger, expenses by ledger, cash & bank book, and master audit report. They are calculated from local ledger rows, including imported Tally entries. The P&L recognizes prior-year Advance AMC on its April 1 transfer and excludes new Advance AMC receipts until transfer. These are not database-backed financial statements. CSV and browser print are available; the audit pack is an HTML download, not a ZIP.
- Fixed deposits have a record form, maturity date/value, maturity warning, and basic effect on displayed funds. The code does not yet implement the full confirmation, interest calculation, or journal posting lifecycle for maturity/early closure.

## Present limitations and risks

1. **Build baseline:** Before the Phase 1 fix, TypeScript rejected report-row unions because some synthesized rows did not expose optional `expenseType`/`donationType` properties. The report collection has now been explicitly typed as `LedgerEntry[]`; the local production build is the verification gate for this fix.
2. **Persistence and concurrency:** operational collections are now validated and revision-checked in SQLite with a pre-import backup path. The collection model is still JSON-in-SQLite rather than normalized accounting tables, and posted accounting rows are not yet immutable double-entry journals.
3. **Accounting integrity:** balances are derived from mutable records rather than balanced, immutable journal entries. UI statuses and approvals are not a substitute for settlement verification, audit logs, period locks, or reversal workflows.
4. **Authentication:** committee and resident authentication are server-side; resident passwords are hashed and never returned to the frontend. Login/password-change throttling is durable in SQLite. Production still requires deployment secrets, explicit HTTPS origins, trusted proxy configuration, and an operational password-reset process. Legacy plaintext passwords remain in a browser until the committee verifies the server import and explicitly cleans up that browser.
5. **Reporting semantics:** the local Tally books reconcile to their reported closing balances; the opening cash variance, missing AGM detail amount, and incomplete AMC support exports are shown in Reports. Historic reports still read the portal ledger collection, while the new normalized journal/audit layer has its own controlled UI and is not yet the source for all operational reports. Resident ageing and full journal-derived statements remain future slices.
6. **Large media:** event/office-bearer images can be held in browser storage as data URLs, which does not scale and is not a production file-storage strategy.

## Repository notes at inspection

The active branch is `initial`. The repository has a tracked `.github/workflows/deploy-pages.yml`, but GitHub Pages deployment does not host the FastAPI service, SQLite database, or private Tally data and is not the current deployment path. The local `data/` directory, source workbooks, build outputs, dependencies, generated database backups, and importer runtime are excluded from Git.
