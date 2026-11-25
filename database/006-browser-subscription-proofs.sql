-- An accepted Driver proof belongs to one application Subscription lifetime.
-- Existing lifetimes deliberately start without proofs.
CREATE TABLE public.seqoya_subscription_proofs (
  installation uuid NOT NULL,
  driver text NOT NULL CHECK (driver IN ('codex', 'claude', 'pi', 'mimo')),
  incarnation uuid NOT NULL,
  version smallint NOT NULL CHECK (version = 1),
  generation text NOT NULL CHECK (generation COLLATE "C" ~ '^[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]$'),
  witness text NOT NULL CHECK (witness COLLATE "C" ~ '^[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]$'),
  PRIMARY KEY (installation, driver, incarnation),
  FOREIGN KEY (installation, driver, incarnation)
    REFERENCES public.seqoya_subscriptions (installation, driver, incarnation) ON DELETE RESTRICT
);

CREATE TABLE public.seqoya_browser_identity_restore (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  attempt text CHECK (attempt COLLATE "C" ~ '^[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]$'),
  endpoint_sha256 text CHECK (endpoint_sha256 COLLATE "C" ~ '^[0-9a-f]{64}$'),
  database_oid oid CHECK (database_oid <> '0'::oid),
  completed_at timestamptz,
  CHECK (num_nonnulls(attempt, endpoint_sha256, database_oid, completed_at) IN (0, 4))
);
INSERT INTO public.seqoya_browser_identity_restore (singleton) VALUES (true);
