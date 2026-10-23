# Accounting foundation boundary

The first normalized accounting slice is now available in both the local
FastAPI/SQLite service and the Cloudflare Worker/D1 service.

## Included

- A chart of accounts with stable IDs, codes, account types, active state, and
  optional parent accounts.
- April–March accounting periods with open/closed state and an audit trail for
  creation, closing, and authorized reopening.
- Draft journal entries with at least two lines, integer paise amounts, valid
  active account IDs, equal debit/credit totals, and date/financial-year/period
  consistency.
- Transactional posting, immutable posted entries and lines, linked posted
  reversals, and linked posted correction entries.
- Append-only audit events protected by database triggers. Close and reopen
  actions require both a reason and an authorization reference.
- Committee-only API routes under `/api/admin/accounting/` for chart of
  accounts, periods, journals, reversals/corrections, period controls, and
  audit listing.
- A committee-facing **Accounting Controls** screen for creating balanced draft
  journals, posting them, reversing posted entries, viewing the chart of
  accounts, closing/reopening annual periods with reason and authorization, and
  reviewing the normalized append-only audit events.

## Explicit boundaries

- Existing `ledger`, payment, opening-balance, and `tallyReconciliation`
  collections remain unchanged. The Tally importer still appends its existing
  stable rows and does **not** fabricate journal lines from imported history.
- No existing Tally row is converted into a balanced journal automatically.
  Opening balances and historic vouchers need a separately verified mapping and
  an explicit committee posting decision.
- The current slice does not migrate resident payment approvals, expenses,
  fixed deposits, receipts, bank reconciliation, or reports onto journal
  queries. Those workflows continue to use their existing portal paths until a
  later controlled migration.
- The UI intentionally refuses to present the historic imported Tally ledger as
  normalized journals. A committee member must create a verified mapping and
  explicit opening/posting decision before any historic entry is journalized.
- A correction endpoint creates a new posted, linked balanced adjustment. An
  exact reversal swaps the original entry's debit and credit lines into a new
  posted entry; the original remains retained and immutable.
- Receipt numbering, tax policy, accrual/receivable policy, reconciliation
  matching, and automated financial statements are outside this foundation.
- Periods are annual April–March FY periods in this slice; monthly sub-periods
  and month-by-month close controls remain a later extension.

The normalized tables are created by `migrations/0003_accounting.sql` for D1
and by the local startup initializer for SQLite. No remote database or Worker
deployment is performed by this change.
