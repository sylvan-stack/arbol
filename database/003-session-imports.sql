-- Additive session-import provenance (IMP-0.11, IMP-0.12). Applied only by the
-- normal fenced migration tool. The importer is the only writer of both tables.
CREATE TABLE public.chat_imports (
  chat_id         uuid        PRIMARY KEY REFERENCES public.chats (id) ON DELETE RESTRICT,
  tool            text        NOT NULL CHECK (tool IN ('claude-code', 'codex', 'kimi-code', 'pi', 'mimo')),
  native_id       text        NOT NULL CHECK (octet_length(native_id) BETWEEN 1 AND 256),
  kind            text        NOT NULL CHECK (kind IN ('owner', 'agent_launched', 'scheduled', 'arbol_driver', 'probe')),
  tool_version    text,
  origin          jsonb       NOT NULL CHECK (jsonb_typeof(origin) = 'object'),
  manifest        text        NOT NULL CHECK (manifest ~ '^[0-9a-f]{64}$'),
  first_imported  timestamptz NOT NULL,
  last_imported   timestamptz NOT NULL,
  UNIQUE (tool, native_id)
);

CREATE TABLE public.exchange_imports (
  exchange_id  uuid  PRIMARY KEY REFERENCES public.exchanges (id) ON DELETE RESTRICT,
  chat_id      uuid  NOT NULL REFERENCES public.chat_imports (chat_id) ON DELETE RESTRICT,
  turn_key     text  NOT NULL CHECK (octet_length(turn_key) BETWEEN 1 AND 512),
  trigger      text  NOT NULL CHECK (trigger IN ('typed', 'steered', 'task', 'scheduled', 'system')),
  UNIQUE (chat_id, turn_key)
);
