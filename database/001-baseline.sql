-- Arbol single-database baseline (ARC-4). Applied only by migrate_schema.py.
-- The chat and Exchange layout comes from the former chat contract. Application
-- state and Vigor use the layouts common to both previous installations.

CREATE TABLE chats (
  id          uuid        PRIMARY KEY,
  title       text        CHECK (title IS NULL OR char_length(title) BETWEEN 1 AND 240),
  created_at  timestamptz NOT NULL
);

CREATE TABLE exchanges (
  id                uuid        PRIMARY KEY,
  chat_id           uuid        NOT NULL REFERENCES chats (id) ON DELETE RESTRICT,
  number            integer     NOT NULL CHECK (number >= 1),
  state             text        NOT NULL CHECK (state IN ('open', 'completed', 'failed', 'cancelled', 'interrupted')),
  error             jsonb,
  trunk             text        NOT NULL CHECK (trunk ~ '^[a-z][a-z0-9]{0,31}$'),
  build             text        NOT NULL CHECK (build ~ '^(0|[1-9a-f][0-9a-f]*)$'),
  route             jsonb       NOT NULL CHECK (jsonb_typeof(route) = 'object'),
  small_call_route  jsonb       CHECK (small_call_route IS NULL OR jsonb_typeof(small_call_route) = 'object'),
  working_folder    text        NOT NULL CHECK (working_folder LIKE '/%'),
  accepted_at       timestamptz NOT NULL,
  ended_at          timestamptz,
  replaced_by       uuid        REFERENCES exchanges (id) ON DELETE RESTRICT,
  UNIQUE (chat_id, number),
  CHECK ((state = 'open') = (ended_at IS NULL)),
  CHECK ((state = 'failed') = (error IS NOT NULL)),
  CHECK (replaced_by IS NULL OR (replaced_by <> id AND state <> 'open'))
);
CREATE UNIQUE INDEX exchanges_one_open_per_chat ON exchanges (chat_id) WHERE state = 'open';

CREATE TABLE messages (
  exchange_id  uuid    NOT NULL REFERENCES exchanges (id) ON DELETE RESTRICT,
  position     integer NOT NULL CHECK (position >= 0),
  role         text    NOT NULL CHECK (role IN ('user', 'assistant')),
  text         text    NOT NULL,
  PRIMARY KEY (exchange_id, position),
  CHECK ((position = 0) = (role = 'user'))
);

CREATE TABLE tool_calls (
  exchange_id     uuid    NOT NULL REFERENCES exchanges (id) ON DELETE RESTRICT,
  position        integer NOT NULL CHECK (position >= 1),
  run_id          text    NOT NULL,
  call_id         text    NOT NULL,
  parent_call_id  text,
  name            text    NOT NULL,
  input           jsonb   NOT NULL,
  ok              boolean NOT NULL,
  result          jsonb,
  error           text,
  truncated       boolean NOT NULL DEFAULT false,
  interrupted     boolean NOT NULL DEFAULT false,
  ask             jsonb,
  answer          jsonb,
  PRIMARY KEY (exchange_id, position)
);

CREATE TABLE runs (
  exchange_id  uuid        NOT NULL REFERENCES exchanges (id) ON DELETE RESTRICT,
  run_id       text        NOT NULL,
  kind         text        NOT NULL DEFAULT 'agent' CHECK (kind IN ('agent', 'small')),
  outcome      text        NOT NULL CHECK (outcome IN ('completed', 'failed', 'cancelled', 'interrupted')),
  usage        jsonb       NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(usage) = 'object'),
  error        jsonb,
  started      jsonb,
  ended_at     timestamptz NOT NULL,
  PRIMARY KEY (exchange_id, run_id),
  CHECK ((outcome = 'failed') = (error IS NOT NULL))
);

CREATE SEQUENCE drafts_revision;

CREATE TABLE drafts (
  id              uuid        PRIMARY KEY,
  chat_id         uuid        UNIQUE REFERENCES chats (id) ON DELETE RESTRICT,
  folder          text        UNIQUE CHECK (folder IS NULL OR folder LIKE '/%'),
  text            text        NOT NULL,
  revision        bigint      NOT NULL CHECK (revision >= 1),
  sent_as         uuid,
  sent_request    jsonb       CHECK (sent_request IS NULL OR jsonb_typeof(sent_request) = 'object'),
  updated_at      timestamptz NOT NULL,
  CHECK ((chat_id IS NULL) <> (folder IS NULL)),
  CHECK ((sent_as IS NULL) = (sent_request IS NULL))
);

CREATE TABLE chat_settings (
  chat_id         uuid        PRIMARY KEY REFERENCES chats (id) ON DELETE RESTRICT,
  route           jsonb       CHECK (route IS NULL OR jsonb_typeof(route) = 'object'),
  working_folder  text        CHECK (working_folder IS NULL OR working_folder LIKE '/%'),
  updated_at      timestamptz NOT NULL
);

CREATE TABLE chat_marks (
  chat_id      uuid        PRIMARY KEY REFERENCES chats (id) ON DELETE RESTRICT,
  ongoing      boolean     NOT NULL DEFAULT false,
  archived_at  timestamptz,
  updated_at   timestamptz NOT NULL
);

CREATE TABLE exchange_notes (
  exchange_id  uuid        NOT NULL REFERENCES exchanges (id) ON DELETE RESTRICT,
  kind         text        NOT NULL CHECK (kind IN ('ended_stuck')),
  at           timestamptz NOT NULL,
  PRIMARY KEY (exchange_id, kind)
);

CREATE TABLE vigor_profiles (
  version      integer          PRIMARY KEY CHECK (version >= 1),
  approval     text             NOT NULL CHECK (approval IN ('proposed', 'approved')),
  pace         text             NOT NULL,
  placeholder  double precision NOT NULL CHECK (placeholder >= 0 AND placeholder <= 1),
  gates        jsonb            NOT NULL CHECK (jsonb_typeof(gates) = 'array'),
  stale_rule   text             NOT NULL,
  recorded_at  timestamptz      NOT NULL
);

CREATE TABLE vigor_reports (
  id            uuid        PRIMARY KEY,
  driver        text        NOT NULL,
  subscription  text        NOT NULL,
  family        text        NOT NULL,
  outcome       text        NOT NULL CHECK (outcome IN ('ok', 'needs_sign_in', 'unavailable', 'unsupported')),
  fetched_at    timestamptz NOT NULL,
  message       text,
  windows       jsonb       NOT NULL CHECK (jsonb_typeof(windows) = 'array'),
  extra         jsonb       NOT NULL CHECK (jsonb_typeof(extra) = 'object'),
  arrived_at    timestamptz NOT NULL,
  run           uuid,
  UNIQUE (driver, subscription, fetched_at)
);

CREATE TABLE vigor_results (
  id            uuid             PRIMARY KEY,
  driver        text             NOT NULL,
  subscription  text             NOT NULL,
  family        text             NOT NULL,
  moment        timestamptz      NOT NULL,
  report        uuid             REFERENCES vigor_reports (id) ON DELETE RESTRICT,
  profile       integer          NOT NULL REFERENCES vigor_profiles (version) ON DELETE RESTRICT,
  losses        jsonb            NOT NULL CHECK (jsonb_typeof(losses) = 'array'),
  vigor         double precision CHECK (vigor IS NULL OR (vigor >= 0 AND vigor <= 1)),
  exhausted     boolean          NOT NULL,
  predicted     boolean          NOT NULL,
  stale         interval,
  unknown       text,
  notes         jsonb            NOT NULL CHECK (jsonb_typeof(notes) = 'array'),
  next_change   timestamptz,
  next_value    double precision,
  CHECK ((vigor IS NULL) = (unknown IS NOT NULL)),
  CHECK ((next_change IS NULL) = (next_value IS NULL))
);
CREATE INDEX vigor_results_subscription ON vigor_results (driver, subscription, moment);

-- The tool appends one row in the same transaction as each migration.
CREATE TABLE public.arbol_schema_migrations (
  revision               integer PRIMARY KEY CHECK (revision > 0),
  migration_id           text    NOT NULL UNIQUE CHECK (migration_id <> ''),
  checksum               text    NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
  compatibility_version  integer NOT NULL CHECK (compatibility_version BETWEEN 1 AND revision)
);

-- The original restore proof remains bound to its maintenance session across
-- partial commits and lost responses. This is private maintenance metadata.
CREATE TABLE public.arbol_schema_upgrades (
  maintenance_session  text    PRIMARY KEY CHECK (maintenance_session <> ''),
  starting_revision    integer NOT NULL REFERENCES public.arbol_schema_migrations (revision),
  target_revision      integer NOT NULL CHECK (target_revision > starting_revision),
  prior_release        text    NOT NULL CHECK (prior_release <> ''),
  release_checksum     text    NOT NULL CHECK (release_checksum ~ '^[0-9a-f]{64}$'),
  receipt_checksum     text    NOT NULL CHECK (receipt_checksum ~ '^[0-9a-f]{64}$')
);
