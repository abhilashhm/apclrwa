# Production data readiness

## Current status

The UI no longer seeds sample events, resident/payment histories, dashboard totals, or opening bank/cash balances. Missing events and resident records render as empty states, missing opening balances render as “Not set,” and financial years are derived from the current date plus saved ledger entries. The exact built-in sample resident (`RES-DEMO`, or the matching `Demo Resident` / `9876543210` record) is filtered out when resident data is loaded. Other saved browser records are preserved.

Browser-only sign-in has been disabled because credentials and session flags in frontend code or `localStorage` are not secure authentication. Old session flags and the remembered resident username are cleared at startup. The static office-bearer roster and association business settings remain because they are association content/configuration, not fabricated activity.

## Production readiness: not yet

Removing fabricated display data does not make the application production-ready. The app still has no backend or database, and its records remain in the current browser’s `localStorage`. Resident passwords can be saved in plaintext there; role checks, access controls, audit trail, and payment claims are not protected by a server. Posted ledger entries are not double-entry journals, reports are browser calculations, and UPI QR generation or a committee approval does not confirm settlement with the bank. Existing locally saved financial records also have not been reconciled against bank statements or source books.

Do not use the current figures as association books or claim that this UI is a production accounting system. A missing opening balance is intentionally shown as unset. A saved opening balance is user-entered and still needs reconciliation and approval.

## Next work, in order

1. Confirm the source of truth for residents, historical receipts, bank/cash, fixed deposits, and prior-year accounts. Preserve an export of each browser’s saved data before any migration.
2. Agree accounting policies with the association: FY boundaries, cash versus accrual for AMC/membership, receipt numbering, opening-balance treatment, payment verification authority, and reversal/correction rules.
3. Implement a FastAPI service with server-side authentication, secure password hashing, role-based authorization, request validation, and protected APIs. Keep sign-in unavailable until this backend is deployed and configured.
4. Add SQLite schema migrations and a double-entry journal with balanced posting, immutable posted entries, controlled reversals, unique receipt references, and an append-only audit log.
5. Replace every authoritative `localStorage` read/write with API calls; use browser storage only for non-sensitive preferences. Add validated upload storage, automated encrypted backups, restore procedures, and operational logging.
6. Build a dry-run importer for existing browser records. Report malformed rows, duplicates, orphaned records, missing evidence, and balance differences; require review and reconciliation before cutover.
7. Validate exports and reports against reconciled source books and bank statements, then deploy behind HTTPS with secrets/configuration and a tested backup/restore process.

## Phase 1 verification

`npm run build` passes (`tsc -b` and Vite production bundle). This verifies compilation and bundling only; it does not validate accounting correctness, security, payment settlement, deployment, or data reconciliation.
