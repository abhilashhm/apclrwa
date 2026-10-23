CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    account_type TEXT NOT NULL CHECK (account_type IN ('Asset', 'Liability', 'Equity', 'Income', 'Expense')),
    parent_id TEXT REFERENCES accounts(id),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_accounts_parent ON accounts(parent_id);
CREATE INDEX IF NOT EXISTS idx_accounts_active ON accounts(active);

CREATE TABLE IF NOT EXISTS accounting_periods (
    id TEXT PRIMARY KEY,
    financial_year TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Open' CHECK (status IN ('Open', 'Closed')),
    closed_at TEXT,
    closed_by TEXT REFERENCES users(id),
    close_reason TEXT,
    close_authorization TEXT,
    reopened_at TEXT,
    reopened_by TEXT REFERENCES users(id),
    reopen_reason TEXT,
    reopen_authorization TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(financial_year, start_date, end_date),
    CHECK (start_date < end_date)
);
CREATE INDEX IF NOT EXISTS idx_accounting_periods_year ON accounting_periods(financial_year);
CREATE INDEX IF NOT EXISTS idx_accounting_periods_status ON accounting_periods(status);

CREATE TABLE IF NOT EXISTS journal_entries (
    id TEXT PRIMARY KEY,
    entry_date TEXT NOT NULL,
    financial_year TEXT NOT NULL,
    period_id TEXT NOT NULL REFERENCES accounting_periods(id),
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Draft' CHECK (status IN ('Draft', 'Posted')),
    source_type TEXT,
    source_id TEXT,
    reversal_of_entry_id TEXT REFERENCES journal_entries(id),
    correction_of_entry_id TEXT REFERENCES journal_entries(id),
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    posted_by TEXT REFERENCES users(id),
    posted_at TEXT,
    CHECK (reversal_of_entry_id IS NULL OR correction_of_entry_id IS NULL)
);
CREATE INDEX IF NOT EXISTS idx_journal_entries_period ON journal_entries(period_id, entry_date);
CREATE INDEX IF NOT EXISTS idx_journal_entries_status ON journal_entries(status);
CREATE INDEX IF NOT EXISTS idx_journal_entries_source ON journal_entries(source_type, source_id);

CREATE TABLE IF NOT EXISTS journal_lines (
    id TEXT PRIMARY KEY,
    entry_id TEXT NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
    line_no INTEGER NOT NULL CHECK (line_no > 0),
    account_id TEXT NOT NULL REFERENCES accounts(id),
    description TEXT,
    debit_paise INTEGER NOT NULL DEFAULT 0 CHECK (typeof(debit_paise) = 'integer' AND debit_paise >= 0),
    credit_paise INTEGER NOT NULL DEFAULT 0 CHECK (typeof(credit_paise) = 'integer' AND credit_paise >= 0),
    CHECK ((debit_paise > 0 AND credit_paise = 0) OR (credit_paise > 0 AND debit_paise = 0)),
    UNIQUE(entry_id, line_no)
);
CREATE INDEX IF NOT EXISTS idx_journal_lines_entry ON journal_lines(entry_id, line_no);
CREATE INDEX IF NOT EXISTS idx_journal_lines_account ON journal_lines(account_id);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    occurred_at TEXT NOT NULL,
    actor_user_id TEXT NOT NULL REFERENCES users(id),
    actor_username TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    financial_year TEXT,
    period_id TEXT REFERENCES accounting_periods(id),
    reason TEXT,
    authorization TEXT,
    details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_audit_events_occurred ON audit_events(occurred_at, id);
CREATE INDEX IF NOT EXISTS idx_audit_events_entity ON audit_events(entity_type, entity_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_audit_events_period ON audit_events(period_id, occurred_at);

CREATE TRIGGER IF NOT EXISTS journal_entries_posted_immutable
BEFORE UPDATE ON journal_entries
WHEN OLD.status = 'Posted'
BEGIN
    SELECT RAISE(ABORT, 'posted journal entry is immutable');
END;

CREATE TRIGGER IF NOT EXISTS journal_entries_posted_delete_forbidden
BEFORE DELETE ON journal_entries
WHEN OLD.status = 'Posted'
BEGIN
    SELECT RAISE(ABORT, 'posted journal entry is immutable');
END;

CREATE TRIGGER IF NOT EXISTS journal_lines_posted_immutable
BEFORE UPDATE ON journal_lines
WHEN EXISTS (SELECT 1 FROM journal_entries WHERE id = OLD.entry_id AND status = 'Posted')
BEGIN
    SELECT RAISE(ABORT, 'posted journal entry lines are immutable');
END;

CREATE TRIGGER IF NOT EXISTS journal_lines_posted_insert_forbidden
BEFORE INSERT ON journal_lines
WHEN EXISTS (SELECT 1 FROM journal_entries WHERE id = NEW.entry_id AND status = 'Posted')
BEGIN
    SELECT RAISE(ABORT, 'posted journal entry lines are immutable');
END;

CREATE TRIGGER IF NOT EXISTS journal_lines_posted_delete_forbidden
BEFORE DELETE ON journal_lines
WHEN EXISTS (SELECT 1 FROM journal_entries WHERE id = OLD.entry_id AND status = 'Posted')
BEGIN
    SELECT RAISE(ABORT, 'posted journal entry lines are immutable');
END;

CREATE TRIGGER IF NOT EXISTS journal_entry_closed_period_forbidden
BEFORE INSERT ON journal_entries
WHEN EXISTS (SELECT 1 FROM accounting_periods WHERE id = NEW.period_id AND status = 'Closed')
BEGIN
    SELECT RAISE(ABORT, 'accounting period is closed');
END;

CREATE TRIGGER IF NOT EXISTS journal_entry_post_closed_period_forbidden
BEFORE UPDATE OF status ON journal_entries
WHEN NEW.status = 'Posted' AND EXISTS (SELECT 1 FROM accounting_periods WHERE id = NEW.period_id AND status = 'Closed')
BEGIN
    SELECT RAISE(ABORT, 'accounting period is closed');
END;

CREATE TRIGGER IF NOT EXISTS audit_events_append_only_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit events are append-only');
END;

CREATE TRIGGER IF NOT EXISTS audit_events_append_only_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit events are append-only');
END;

INSERT OR IGNORE INTO accounts(id, code, name, account_type, parent_id, active, created_at, updated_at)
VALUES
    ('COA-BANK', '1000', 'Bank', 'Asset', NULL, 1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('COA-CASH', '1010', 'Cash', 'Asset', NULL, 1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('COA-FD', '1020', 'Fixed Deposits', 'Asset', NULL, 1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('COA-RECEIVABLES', '1100', 'Resident Receivables', 'Asset', NULL, 1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('COA-PAYABLES', '2000', 'Payables', 'Liability', NULL, 1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('COA-CORPUS', '3000', 'Association Corpus', 'Equity', NULL, 1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('COA-OPENING', '3100', 'Opening Balance Equity', 'Equity', NULL, 1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('COA-MAINTENANCE', '4000', 'Maintenance Income', 'Income', NULL, 1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('COA-MEMBERSHIP', '4010', 'Membership Income', 'Income', NULL, 1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('COA-CONTRIBUTIONS', '4020', 'Contributions and Donations', 'Income', NULL, 1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('COA-INTEREST', '4030', 'Interest Income', 'Income', NULL, 1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('COA-EXPENSES', '5000', 'Operating Expenses', 'Expense', NULL, 1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));
