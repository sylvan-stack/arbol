-- Additive Steady Trunk diagnostics (STE-0.25). Applied by migrate_schema.py.
CREATE TABLE public.exchange_phase_details (
  exchange_id uuid    NOT NULL REFERENCES public.exchanges (id) ON DELETE RESTRICT,
  position    integer NOT NULL CHECK (position > 0),
  entry       text    NOT NULL CHECK (entry <> ''),
  PRIMARY KEY (exchange_id, position)
);
