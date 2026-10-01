-- Schema from docs/SPEC.md §3. Idempotent: every migration runs on each start.
-- An applied migration is never edited; changes go into a new NNN_*.sql.

CREATE TABLE IF NOT EXISTS checks (
  id             BIGSERIAL PRIMARY KEY,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  status         TEXT NOT NULL,          -- done | error
  verdict        TEXT,                   -- fail | needs_review | incomplete | pass
  spec           JSONB,
  extraction     JSONB,
  findings       JSONB,
  error          JSONB,
  model          TEXT,
  prompt_version TEXT,
  rules_version  TEXT,
  usage          JSONB,                  -- tokens from the model response
  raw_text       TEXT,                   -- raw model output, kept on model errors too (audit)
  cache_hit      BOOLEAN,
  duration_ms    INT
);

CREATE TABLE IF NOT EXISTS check_images (
  check_id BIGINT REFERENCES checks(id) ON DELETE CASCADE,
  idx      INT,
  sha256   TEXT,
  mime     TEXT,
  width    INT,
  height   INT,
  data     BYTEA NOT NULL,               -- the prepared photo: exactly what the model saw
  PRIMARY KEY (check_id, idx)
);

-- cache_key = sha256(concatenated photo sha256s in upload order) + PROMPT_VERSION + model.
-- Order matters: photo_index in the extraction depends on it.
CREATE TABLE IF NOT EXISTS extraction_cache (
  cache_key      TEXT PRIMARY KEY,
  prompt_version TEXT,
  model          TEXT,
  extraction     JSONB NOT NULL,
  raw_text       TEXT,
  usage          JSONB,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
