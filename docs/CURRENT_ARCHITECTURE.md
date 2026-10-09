# Current architecture and Phase 1 findings

## Scope and source of truth

This document describes the repository as inspected on branch `initial`. The app is a client-side community portal prototype, not a deployed accounting system. The implementation is concentrated in `src/App.tsx` and `src/styles.css`; the entry point is `src/main.tsx`, and `index.html` supplies the document metadata and `/logo1.svg` favicon. `package.json` defines a Vite development server and a production build (`tsc -b && vite build`). Dependencies are React 19, TypeScript, Vite, and `qrcode`.

The repository now includes a small FastAPI service in `backend/auth.py`, with SQLite users/sessions, server-side committee authentication, and a protected endpoint for the private Tally import snapshot. It does not yet store day-to-day financial records or provide a financial API. Operational portal data remains in browser `localStorage`. The UI has a public home page, backend login, resident portal placeholder, password-change view, and committee portal selected by in-app state in `App`.

`backend/tally_import.py` reads the Tally `.xls` exports from `C:\Tally.ERP9` without changing them, normalizes the bank/cash books, and writes a private `data/tally-import.json` snapshot. `data/` is gitignored. On committee sign-in, the UI fetches the snapshot through `/api/admin/tally-import`, adds missing rows to browser storage by stable IDs, sets the imported opening balance only when none exists, and creates the April 1 Advance AMC reclassification rows. This is a local import bridge, not authoritative backend accounting storage.

## UI and state organization

`src/App.tsx` contains the landing page, theme toggle, office-bearer display, events, login, resident workflows, data types/storage helpers, admin forms, report generation, and the committee dashboard. `src/styles.css` contains the app-wide visual system, responsive rules, admin/resident styles, and theme-specific overrides. The shared theme preference is `apclrwa_theme`; a custom event propagates theme changes within the page. Office-bearer updates use a similar custom event. Events and user-entered records are read from `localStorage`.

The public page filters out residents-only events. Committee login uses an HTTP-only backend session cookie; resident sign-in remains unavailable until resident accounts are migrated. Old browser session flags are cleared at startup. Resident UPI payment claims are still browser-persisted pending items until committee review; approval appends a posted entry to the browser ledger and does not verify bank settlement.

## Persisted browser data

The app uses these keys (all scoped to one browser profile, without multi-user synchronization):

| Key | Contents / use |
| --- | --- |
| `apclrwa_residents` | Resident records, membership state, active status, prototype plaintext passwords (not safe for production) |
| `apclrwa_pending_payments` | Resident-submitted payment claims and review status |
| `apclrwa_admin_ledger` | Maintenance, contribution, expense, and bank/cash rows, with a string `kind` and posted/status fields |
| `apclrwa_fixed_deposits` | FD records and lifecycle status |
| `apclrwa_opening_balances` | Editable opening bank/cash figures and financial year |
| `apclrwa_expense_types` | User-configurable expense categories |
| `apclrwa_events` | Community updates, including optional image data and resident-only visibility |
| `apclrwa_office_bearers` | Association office-bearer details and optional image data |
| `apclrwa_theme` | Shared light/dark preference |
| `apclrwa_selected_fy` | Committee portal's selected FY |
| `apclrwa_tally_import_id` | Local marker for the imported Tally snapshot version |
| `apclrwa_tally_reconciliation` | Tally bank/cash roll-forward and source-ledger control results |
| `apclrwa_admin_session`, `apclrwa_resident_session`, `apclrwa_resident_username` | Demo login/session routing state |

Missing resident/event/opening-balance data now produces empty or unset states; the exact built-in sample resident is filtered from the resident store. Legacy residents with no `cross` value are normalized when loaded. Images may be stored as data URLs. Browser storage is not a reliable backup or a shared source of truth.

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
2. **Persistence and concurrency:** localStorage is per browser and can be edited or cleared by a user. It does not provide server-side validation, transactional updates, multi-user consistency, durable identifiers, or managed backups.
3. **Accounting integrity:** balances are derived from mutable records rather than balanced, immutable journal entries. UI statuses and approvals are not a substitute for settlement verification, audit logs, period locks, or reversal workflows.
4. **Authentication:** committee authentication is server-side, but resident accounts, password recovery, rate limiting, deployment secrets, and production cookie/CORS configuration remain incomplete. Legacy resident records may still contain plaintext passwords in browser storage.
5. **Reporting semantics:** the local Tally books reconcile to their reported closing balances; the opening cash variance, missing AGM detail amount, and incomplete AMC support exports are shown in Reports. These reports still read mutable browser storage, not a protected journal. No close controls, full ageing, or append-only audit log exist.
6. **Large media:** event/office-bearer images can be held in browser storage as data URLs, which does not scale and is not a production file-storage strategy.

## Repository notes at inspection

The active branch is `initial`. The repository has a tracked `.github/workflows/deploy-pages.yml`; GitHub Pages deployment does not host the FastAPI service or private Tally data. The local `data/` directory, source workbooks, build outputs, dependencies, and importer runtime are excluded from Git.
