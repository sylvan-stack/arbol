-- The second Root's own tables (RTM-1).
-- Kept in the arbol-root repository as roots/jensen/layout.sql; the second Root's arbol-root Builds carry it as layout/root-tables.sql.
-- arbol-roots runs it after the chat tables: psql --no-psqlrc --set ON_ERROR_STOP=1 --single-transaction --file root-tables.sql
-- Every statement can run again: on a database that already has everything, the file changes nothing.
-- Arbol's own tables, such as Drafts, are added to this file by Arbol's specification.

CREATE TABLE IF NOT EXISTS migrated_chats (
  chat_id        uuid        PRIMARY KEY REFERENCES chats (id) ON DELETE RESTRICT,
  from_root      text        NOT NULL,
  from_chat      uuid        NOT NULL,
  ended_through  integer     NOT NULL CHECK (ended_through >= 0),
  migrated_at    timestamptz NOT NULL
);
COMMENT ON TABLE migrated_chats IS 'One row for each chat that a migration brought into this Root: where it came from and how far the original had got. Written once, by the migration script.';
COMMENT ON COLUMN migrated_chats.chat_id IS 'The chat in this Root, for example c3d4e5f6-0718-4293-a4b5-c6d7e8f90a1b.';
COMMENT ON COLUMN migrated_chats.from_root IS 'The identifier of the Root it came from, for example sapling.';
COMMENT ON COLUMN migrated_chats.from_chat IS 'The chat''s identifier in that Root; the same as chat_id for a chat copied as it was.';
COMMENT ON COLUMN migrated_chats.ended_through IS 'How far the original had got when it was read: the number of its last Exchange that had ended, 0 when none had.';
COMMENT ON COLUMN migrated_chats.migrated_at IS 'When the older database was read: the moment of the snapshot the copy shows.';

-- Compatible addition for comparing and refreshing migrated copies (RTM-1.12).
ALTER TABLE migrated_chats ADD COLUMN IF NOT EXISTS stale boolean NOT NULL DEFAULT false;
COMMENT ON COLUMN migrated_chats.stale IS 'Whether the original has a later ended Exchange than ended_through; changed only by an explicit comparison or successful reimport.';

-- The Arbol backend's own tables (BKD-0). Written by the Arbol backend alone.

CREATE SEQUENCE IF NOT EXISTS drafts_revision;
COMMENT ON SEQUENCE drafts_revision IS 'The one counter of the revisions of every Draft, so that no revision is given twice, also after a Draft was removed.';

CREATE TABLE IF NOT EXISTS drafts (
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
COMMENT ON TABLE drafts IS 'What the Leather Bag typed in a composer and has not sent: one Draft of the reply for each chat, and one Draft of a new chat for each repository folder. Written by the Arbol backend alone (BKD-0).';
COMMENT ON COLUMN drafts.id IS 'The Draft''s own identifier, a UUID the backend gives it.';
COMMENT ON COLUMN drafts.chat_id IS 'For the Draft of a reply: its chat, for example c3d4e5f6-0718-4293-a4b5-c6d7e8f90a1b; NULL for the Draft of a new chat.';
COMMENT ON COLUMN drafts.folder IS 'For the Draft of a new chat: the absolute folder of its repository, for example /Users/sam/repos/shop; NULL for the Draft of a reply.';
COMMENT ON COLUMN drafts.text IS 'The text as the Leather Bag typed it, exactly.';
COMMENT ON COLUMN drafts.revision IS 'A new value of drafts_revision each time the Draft is saved. A save names the revision it was made over and is refused when that is no longer the Draft''s.';
COMMENT ON COLUMN drafts.sent_as IS 'The Exchange this Draft was sent as and not yet accepted or refused, for example 9b3a2c1e-5c6d-4f70-9a1b-2c3d4e5f6a7b; NULL when it is not being sent. Cleared by a save, which brings new text. The Draft is removed once that Exchange is in the chat tables.';
COMMENT ON COLUMN drafts.sent_request IS 'With sent_as: what the Draft was sent with, so that a send left half done can be made again with the same Exchange, for example {"chat": "c3d4e5f6-…", "route": {"driver": "claude", "subscription": "anthropic", "model": "sonnet"}, "workingFolder": "/Users/sam/repos/sylvan-stack/readonly/shop"}.';
COMMENT ON COLUMN drafts.updated_at IS 'When the Draft was last saved.';

CREATE TABLE IF NOT EXISTS chat_settings (
  chat_id         uuid        PRIMARY KEY REFERENCES chats (id) ON DELETE RESTRICT,
  route           jsonb       CHECK (route IS NULL OR jsonb_typeof(route) = 'object'),
  working_folder  text        CHECK (working_folder IS NULL OR working_folder LIKE '/%'),
  updated_at      timestamptz NOT NULL
);
COMMENT ON TABLE chat_settings IS 'What the Leather Bag picked for a chat''s next message, where it differs from the chat''s last Exchange. Written by the Arbol backend alone (BKD-0).';
COMMENT ON COLUMN chat_settings.chat_id IS 'The chat.';
COMMENT ON COLUMN chat_settings.route IS 'The route picked for the next message, in the form of ARC-0, for example {"driver": "claude", "subscription": "anthropic", "model": "sonnet", "effort": "high"}; NULL: the route of the last Exchange.';
COMMENT ON COLUMN chat_settings.working_folder IS 'The absolute folder picked for the next message, for example /Users/sam/repos/shop; NULL: the folder of the last Exchange.';
COMMENT ON COLUMN chat_settings.updated_at IS 'When a choice was last saved.';

CREATE TABLE IF NOT EXISTS chat_marks (
  chat_id      uuid        PRIMARY KEY REFERENCES chats (id) ON DELETE RESTRICT,
  ongoing      boolean     NOT NULL DEFAULT false,
  archived_at  timestamptz,
  updated_at   timestamptz NOT NULL
);
COMMENT ON TABLE chat_marks IS 'The marks the Leather Bag gives a chat in Elma Chat. Written by the Arbol backend alone (BKD-0).';
COMMENT ON COLUMN chat_marks.chat_id IS 'The chat.';
COMMENT ON COLUMN chat_marks.ongoing IS 'true while the Leather Bag marks the chat as one still being worked on (Elma Chat, Ongoing).';
COMMENT ON COLUMN chat_marks.archived_at IS 'When the Leather Bag archived the chat; NULL while it is not archived. An archived chat leaves the latest chats.';
COMMENT ON COLUMN chat_marks.updated_at IS 'When a mark was last changed.';

CREATE TABLE IF NOT EXISTS exchange_notes (
  exchange_id  uuid        NOT NULL REFERENCES exchanges (id) ON DELETE RESTRICT,
  kind         text        NOT NULL CHECK (kind IN ('ended_stuck')),
  at           timestamptz NOT NULL,
  PRIMARY KEY (exchange_id, kind)
);
COMMENT ON TABLE exchange_notes IS 'What Arbol says about an Exchange that the chat tables do not hold. Written by the Arbol backend alone (BKD-0).';
COMMENT ON COLUMN exchange_notes.exchange_id IS 'The Exchange the note is about.';
COMMENT ON COLUMN exchange_notes.kind IS 'ended_stuck: the backend ended the Exchange by force because its heartbeat stood still (ARC-3).';
COMMENT ON COLUMN exchange_notes.at IS 'When the backend decided it.';
