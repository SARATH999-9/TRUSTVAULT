-- TrustVault PostgreSQL schema. Run once as the migration/owner role.
CREATE TABLE users (
  id             VARCHAR(36) PRIMARY KEY,
  email          VARCHAR(254) NOT NULL UNIQUE,
  name           VARCHAR(120) NOT NULL,
  password_hash  VARCHAR(255) NOT NULL,
  role           VARCHAR(10)  NOT NULL CHECK (role IN ('admin','owner','viewer')),
  status         VARCHAR(12)  NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','active','rejected','suspended')),
  email_verified BOOLEAN NOT NULL DEFAULT FALSE,
  auth_provider  VARCHAR(10)  NOT NULL DEFAULT 'password',
  google_sub     VARCHAR(64) UNIQUE,
  registered_ip  VARCHAR(45),
  last_login_at  TIMESTAMPTZ,
  decided_by     VARCHAR(36),
  decided_at     TIMESTAMPTZ,
  decision_reason VARCHAR(500),
  failed_logins  INTEGER NOT NULL DEFAULT 0,
  locked_until   TIMESTAMPTZ,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_users_status ON users(status);

CREATE TABLE sessions (
  id          VARCHAR(36) PRIMARY KEY,
  token_hash  VARCHAR(64) NOT NULL UNIQUE,
  user_id     VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at  TIMESTAMPTZ NOT NULL,
  revoked_at  TIMESTAMPTZ,
  ip          VARCHAR(45),
  user_agent  VARCHAR(255)
);
CREATE INDEX ix_sessions_user ON sessions(user_id);

CREATE TABLE documents (
  id          VARCHAR(36) PRIMARY KEY,
  owner_id    VARCHAR(36) NOT NULL REFERENCES users(id),
  name        VARCHAR(255) NOT NULL,
  category    VARCHAR(60) NOT NULL DEFAULT 'general',
  description TEXT NOT NULL DEFAULT '',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at  TIMESTAMPTZ,
  review_status VARCHAR(10) NOT NULL DEFAULT 'approved' CHECK (review_status IN ('pending','approved','rejected')),
  reviewed_by VARCHAR(36),
  reviewed_at TIMESTAMPTZ,
  review_reason VARCHAR(500)
);
CREATE INDEX ix_documents_review ON documents(review_status);
CREATE INDEX ix_documents_owner ON documents(owner_id);
CREATE INDEX ix_documents_name ON documents(name);
CREATE INDEX ix_documents_category ON documents(category);
CREATE INDEX ix_documents_created ON documents(created_at);

CREATE TABLE document_versions (
  id                VARCHAR(36) PRIMARY KEY,
  document_id       VARCHAR(36) NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  version_no        INTEGER NOT NULL,
  storage_key       VARCHAR(64) NOT NULL UNIQUE,
  original_filename VARCHAR(255) NOT NULL,
  mime_type         VARCHAR(100) NOT NULL,
  size_bytes        INTEGER NOT NULL,
  sha256            VARCHAR(64) NOT NULL,
  uploaded_by       VARCHAR(36) NOT NULL REFERENCES users(id),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (document_id, version_no)
);

CREATE TABLE grants (
  id          VARCHAR(36) PRIMARY KEY,
  document_id VARCHAR(36) NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  user_id     VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  permission  VARCHAR(10) NOT NULL CHECK (permission IN ('read','edit')),
  granted_by  VARCHAR(36) NOT NULL REFERENCES users(id),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at  TIMESTAMPTZ,
  UNIQUE (document_id, user_id)
);

CREATE TABLE app_settings (
  key         VARCHAR(60) PRIMARY KEY,
  value       TEXT NOT NULL DEFAULT '{}',
  updated_by  VARCHAR(36),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ai_suggestions (
  id           VARCHAR(36) PRIMARY KEY,
  document_id  VARCHAR(36) NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  requested_by VARCHAR(36) NOT NULL REFERENCES users(id),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  source       VARCHAR(10) NOT NULL,
  candidates   TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX ix_ai_suggestions_doc ON ai_suggestions(document_id);

CREATE TABLE audit_log (
  id             SERIAL PRIMARY KEY,
  ts             TIMESTAMPTZ NOT NULL DEFAULT now(),
  actor_id       VARCHAR(36),
  actor_email    VARCHAR(254),
  action         VARCHAR(40) NOT NULL,
  outcome        VARCHAR(10) NOT NULL CHECK (outcome IN ('allowed','denied')),
  document_id    VARCHAR(36),
  target_user_id VARCHAR(36),
  ip             VARCHAR(45),
  detail         TEXT NOT NULL DEFAULT '{}',
  prev_hash      VARCHAR(64) NOT NULL,
  row_hash       VARCHAR(64) NOT NULL
);
CREATE INDEX ix_audit_ts ON audit_log(ts);
CREATE INDEX ix_audit_doc_ts ON audit_log(document_id, ts);

-- Audit rows can never be changed or removed, even by the application role.
CREATE FUNCTION audit_immutable() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'audit_log is append-only';
END; $$ LANGUAGE plpgsql;

CREATE TRIGGER audit_no_update BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION audit_immutable();
CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON audit_log
  FOR EACH STATEMENT EXECUTE FUNCTION audit_immutable();

-- Least-privilege application role (replace password). App connects as this, not as owner.
-- CREATE ROLE trustvault_app LOGIN PASSWORD '...';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON users, sessions, documents, document_versions, grants, ai_suggestions, app_settings TO trustvault_app;
-- GRANT SELECT, INSERT ON audit_log TO trustvault_app;
-- GRANT USAGE ON SEQUENCE audit_log_id_seq TO trustvault_app;
