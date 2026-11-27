ALTER TABLE public.seqoya_browser_bindings
  DROP CONSTRAINT seqoya_browser_bindings_profile_check,
  ADD COLUMN profile_origin text NOT NULL DEFAULT 'generated',
  ADD CONSTRAINT seqoya_browser_bindings_profile_check CHECK (
    (profile_origin = 'generated' AND profile ~ '^seqoya-[0-9a-f]{32}$')
    OR
    (profile_origin = 'existing' AND profile ~ '^[a-z]([a-z0-9-]{0,62}[a-z0-9])?$'
      AND profile <> 'default' AND profile !~ '^seqoya-[0-9a-f]{32}$'
      AND state <> 'preparing' AND profile_instance IS NOT NULL)
  );
