-- Additive Seqoya identity/binding authority (BRW-1.11, BRW-1.14).
-- Applied only by the normal fenced migration tool. No catalogue is imported:
-- reusable Driver ids and timestamps cannot establish an old login's identity.
CREATE TABLE public.seqoya_installation (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  id uuid NOT NULL UNIQUE DEFAULT gen_random_uuid()
);
INSERT INTO public.seqoya_installation (singleton) VALUES (true);

CREATE TABLE public.seqoya_subscriptions (
  installation uuid NOT NULL REFERENCES public.seqoya_installation (id) ON DELETE RESTRICT,
  driver text NOT NULL CHECK (driver ~ '^[a-z][a-z0-9-]{0,79}$'),
  incarnation uuid NOT NULL,
  native_id text NOT NULL CHECK (octet_length(native_id) BETWEEN 1 AND 256),
  state text NOT NULL CHECK (state IN ('active', 'needs_rebind', 'retired')),
  created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
  retired_at timestamptz,
  PRIMARY KEY (installation, driver, incarnation),
  CHECK ((state = 'retired') = (retired_at IS NOT NULL))
);
CREATE UNIQUE INDEX seqoya_subscription_current
  ON public.seqoya_subscriptions (installation, driver, native_id)
  WHERE state <> 'retired';

CREATE TABLE public.seqoya_browser_bindings (
  installation uuid NOT NULL,
  driver text NOT NULL,
  subscription_incarnation uuid NOT NULL,
  creation_request text NOT NULL CHECK (creation_request ~ '^create_[A-Za-z0-9_-]{22}$'),
  profile text NOT NULL UNIQUE CHECK (profile ~ '^seqoya-[0-9a-f]{32}$'),
  profile_instance text CHECK (profile_instance ~ '^prf_[A-Za-z0-9_-]{22}$'),
  state text NOT NULL CHECK (state IN ('preparing', 'active', 'needs_rebind', 'retired')),
  PRIMARY KEY (installation, driver, subscription_incarnation, creation_request),
  FOREIGN KEY (installation, driver, subscription_incarnation)
    REFERENCES public.seqoya_subscriptions (installation, driver, incarnation) ON DELETE RESTRICT,
  CHECK (state <> 'active' OR profile_instance IS NOT NULL)
);
CREATE UNIQUE INDEX seqoya_binding_current
  ON public.seqoya_browser_bindings (installation, driver, subscription_incarnation)
  WHERE state <> 'retired';
