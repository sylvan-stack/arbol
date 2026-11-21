-- Older import provenance stays readable. Every new or updated provenance row
-- must identify the exact paths and content hashes in its current manifest.
ALTER TABLE public.chat_imports
  ADD COLUMN files_fingerprint text
  CHECK (files_fingerprint IS NULL OR files_fingerprint ~ '^[0-9a-f]{64}$');

CREATE FUNCTION public.require_import_files_fingerprint() RETURNS trigger
  LANGUAGE plpgsql
  SET search_path = pg_catalog, public
AS $$
BEGIN
  IF NEW.files_fingerprint IS NULL THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'import_files_fingerprint_required';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER chat_imports_require_files_fingerprint
  BEFORE INSERT OR UPDATE ON public.chat_imports
  FOR EACH ROW EXECUTE FUNCTION public.require_import_files_fingerprint();
