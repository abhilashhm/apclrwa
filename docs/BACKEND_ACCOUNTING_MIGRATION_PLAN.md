# Backend and accounting migration plan

This plan is based on the current `initial` branch implementation documented in [CURRENT_ARCHITECTURE.md](CURRENT_ARCHITECTURE.md). It is a proposal; it does not change the accounting rules or imply that existing browser data has been reconciled.

## Goals and guardrails

- Keep the existing React screens and resident/committee workflows working while replacing persistence behind them incrementally.
- Make SQLite and a backend API the authoritative store for residents, payment claims, receipts, financial years, journals, fixed deposits, audit events, and uploaded files.
- Only report accounting balances from posted, balanced journal lines. Keep submitted payment claims separate from posted transactions until verified.
- Preserve existing browser data during transition. Export/preview it, validate it, import it idempotently, and retain a backup before any cutover. Never silently treat a browser snapshot as verified books.
- Do not fabricate receipt references, opening balances, payment settlement, or historical journal detail that is absent from existing rows.
- Keep accounting posting rules and permissions on the backend. The frontend remains responsible for presentation and user input, not financial authority.

## Suggested target components

1. **FastAPI service:** request validation, authentication, authorization, application services, receipt allocation, posting, reporting queries, file handling, and audit logging.
2. **SQLite database:** foreign keys enabled; schema migrations checked into the repository; transactions around approval/posting and sequence allocation. Use integer minor units (paise) for amounts, or an explicit decimal representation with consistent rounding; avoid binary floating-point for accounting.
3. **React API client:** typed request/response layer replacing direct `localStorage` reads and writes by feature. Keep existing view components and styles unless a workflow requires a small UI addition.
4. **File storage:** local managed uploads initially, with database metadata and validated paths; keep large images out of localStorage. Include files in backup/restore.

## Core accounting/data model

- `FinancialYear` and `AccountingPeriod`: canonical start/end dates, open/closed state, and authorized reopen events.
- `Account`: chart of accounts, account type, code, and active status.
- `JournalEntry` and `JournalLine`: date, FY/period, source type/id, narration, status, created/posted metadata, account, debit/credit in minor units. Enforce non-empty balanced postings inside one database transaction. Posted entries are immutable; corrections use a linked reversal and replacement/correction entry.
- `Receipt`: durable number, receipt family (AMC, membership, contribution), issue year/FY, linked source/payment/journal, and lifecycle state. Allocate sequences transactionally; never recycle a number after posting.
- Domain records: `Resident`, `Charge`, `PaymentSubmission`, `Contribution`, `Expense`, `FixedDeposit`, `BankStatementImport`, `BankStatementLine`, and `Reconciliation` with explicit relationships and audit references.
- `AuditLog`: actor, timestamp, action, entity, before/after snapshots where appropriate, reason, and FY/period. Append-only for business actions.
- `User`, `Role`, and session/token records: backend password hashing, expiration, rate limits, and server-enforced role checks.

## Incremental delivery sequence

### Phase 1 — baseline and documentation (current)

Record the actual frontend/localStorage architecture, repair existing type/build errors, and establish this migration direction. Do not redesign the product or migrate records in this phase.

### Phase 2 — backend foundation

- Add a FastAPI application, SQLite connection management, schema migrations, health/version endpoint, configuration, and local run instructions.
- Add authentication/role foundations before exposing protected financial APIs.
- Add typed frontend API client and a backend adapter boundary so components can move feature by feature.
- Retain a read-only/export path for browser records; do not silently switch or wipe data.

### Phase 3 — ledger foundation

- Create chart of accounts, journals/lines, audit log, period/FY primitives, transactional posting service, and reversal rules.
- Add backend invariants for equal debit/credit totals, valid accounts, date/FY consistency, and closed-period rejection.
- Keep this foundation independently reviewable before moving live workflows.

### Phase 4 — migrate financial workflows in controlled slices

1. Residents and membership charges/payments.
2. Annual maintenance charges and resident payment submissions.
3. Contributions/donations.
4. Expenses.
5. Bank/cash transfers and opening balances.
6. Fixed deposits and maturity/early-closure confirmation.

For each slice: define posting rules, API and authorization, idempotency key, audit event, UI adapter, migration/verification, and regression checks. A payment submission is not income until the committee verifies it; approval and journal posting must commit atomically. Use linked receipts on successful posting.

### Phase 5 — receipt numbering and historic migration

- Implement AMC, membership, and contribution sequences in the database, with concurrency-safe allocation and no reuse.
- Build a dry-run importer for localStorage JSON. Validate schema, duplicates, resident references, FY/date coherence, and payment states; show a reconciliation summary before write.
- Import identifiable records with stable legacy IDs. Keep legacy IDs separately from new receipt/journal numbers. Mark unknown or unverified opening data as requiring review; do not create imaginary journal lines or receipts.
- Back up the database and source JSON, record import batch/audit entries, and verify counts/totals before cutover.

### Phase 6 — bank imports and reconciliation

Import CSV to a staged statement batch, map columns, deduplicate, preview, and only then persist statement lines. Match statement lines to book transactions; keep unmatched lines visible. Do not auto-post imports. Complete reconciliation only when the difference is zero or a documented, authorized adjustment has been posted.

### Phase 7 — closing controls

Implement monthly close/reopen and FY close/reopen services after period/date validation is in use. Close checks should flag unbalanced entries, pending claims, unreconciled bank items, and invalid references. Reopen requires role authorization, reason, and audit event; prior-year records remain retained.

### Phase 8 — reports and operations

Rebuild reports from journal/domain queries: maintenance collection and outstanding, membership, contribution, expense, cash/bank book, general ledger, trial balance, income/expense, FD principal/interest, reconciliation, ageing, defaulters, audit register/dashboard, master report, and audit pack. Add backup/restore with schema/version and uploads, pre-restore backup, validation, and audit event. Add gallery and production hardening when core accounting is stable.

## Cutover questions to resolve with source records

Before importing balances or posting opening journals, reconcile the actual bank statements, cash count, FD certificates, and any existing paper/Tally books. The prototype now shows opening balances as unset unless a user has saved them; any saved browser value remains unverified and must not automatically be treated as an approved opening balance. Confirm the intended accounting treatment for unpaid AMC/membership (cash-basis income vs receivable/accrual), receipt-year rule, financial-year policy, and approval authority against association records. Store decisions as explicit policy/configuration and test their effects.

## Completion criteria for migration slices

- No screen in the migrated slice reads or writes its authoritative data directly from localStorage.
- Backend permissions and input validation reject unauthorized or invalid operations.
- Posting and audit/receipt creation are transactional and idempotent.
- Posted journal entries balance, remain immutable, and have a tested reversal/correction path.
- A migration preview and recoverable backup exist before historic import or cutover.
- Financial reports can be reproduced from the database and reconcile to the journal ledger.
