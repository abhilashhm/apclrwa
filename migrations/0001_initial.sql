CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('committee', 'resident')),
    password_salt TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    resident_id TEXT,
    must_change_password INTEGER NOT NULL DEFAULT 0 CHECK (must_change_password IN (0, 1)),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_resident ON users(resident_id);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS auth_attempts (
    id TEXT PRIMARY KEY,
    account_key TEXT NOT NULL,
    ip_key TEXT NOT NULL,
    attempted_at REAL NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('pending', 'failed', 'succeeded', 'cleared'))
);
CREATE INDEX IF NOT EXISTS idx_auth_attempts_account ON auth_attempts(account_key, outcome, attempted_at);
CREATE INDEX IF NOT EXISTS idx_auth_attempts_ip ON auth_attempts(ip_key, attempted_at);
CREATE INDEX IF NOT EXISTS idx_auth_attempts_expiry ON auth_attempts(attempted_at);

CREATE TABLE IF NOT EXISTS auth_attempt_guard (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    account_key TEXT NOT NULL,
    ip_key TEXT NOT NULL,
    cutoff REAL NOT NULL,
    account_limit INTEGER NOT NULL,
    ip_limit INTEGER NOT NULL
);

CREATE TRIGGER IF NOT EXISTS auth_attempt_guard_check
BEFORE INSERT ON auth_attempt_guard
WHEN
    (SELECT COUNT(*) FROM auth_attempts
     WHERE account_key = NEW.account_key
       AND outcome IN ('pending', 'failed')
       AND attempted_at > NEW.cutoff) >= NEW.account_limit
 OR
    (SELECT COUNT(*) FROM auth_attempts
     WHERE ip_key = NEW.ip_key
       AND attempted_at > NEW.cutoff) >= NEW.ip_limit
BEGIN
    SELECT RAISE(ABORT, 'auth rate limit');
END;

CREATE TABLE IF NOT EXISTS portal_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS portal_collection_versions (
    name TEXT PRIMARY KEY,
    version_id TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS portal_collection_chunks (
    name TEXT NOT NULL,
    version_id TEXT NOT NULL,
    chunk_no INTEGER NOT NULL,
    value_json TEXT NOT NULL,
    PRIMARY KEY (name, version_id, chunk_no)
);
CREATE INDEX IF NOT EXISTS idx_portal_collection_chunks_active ON portal_collection_chunks(name, version_id, chunk_no);

CREATE TABLE IF NOT EXISTS portal_revision_guard (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    expected_revision INTEGER NOT NULL
);

CREATE TRIGGER IF NOT EXISTS portal_revision_guard_check
BEFORE INSERT ON portal_revision_guard
WHEN (SELECT revision FROM portal_state WHERE id = 1) <> NEW.expected_revision
BEGIN
    SELECT RAISE(ABORT, 'portal revision conflict');
END;

CREATE TABLE IF NOT EXISTS portal_payment_keys (
    resident_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    payment_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (resident_id, idempotency_key)
);
