-- Subscriptions Vigor's records (SGM-1, "The calculation record"). Written by the Arbol process alone, the backend and
-- `arbol vigor`. They belong to the Root where they were made and are not copied when the Root changes (SGM-D29).

CREATE TABLE IF NOT EXISTS vigor_profiles (
  version      integer          PRIMARY KEY CHECK (version >= 1),
  approval     text             NOT NULL CHECK (approval IN ('proposed', 'approved')),
  pace         text             NOT NULL,
  placeholder  double precision NOT NULL CHECK (placeholder >= 0 AND placeholder <= 1),
  gates        jsonb            NOT NULL CHECK (jsonb_typeof(gates) = 'array'),
  stale_rule   text             NOT NULL,
  recorded_at  timestamptz      NOT NULL
);
COMMENT ON TABLE vigor_profiles IS 'The versioned choices of a Vigor calculation, in the shape of SGM-0''s profile: the pace assumption, the gate weights and the stale rule. Version 1 is the first profile, proposed, with the placeholder 0.1. Written by the Arbol process alone (SGM-1).';
COMMENT ON COLUMN vigor_profiles.version IS 'The profile''s version, for example 1; a result names the version it was computed by.';
COMMENT ON COLUMN vigor_profiles.approval IS 'proposed until the owner approves the profile for operation, approved afterwards (SGM-D15, SGM-D17).';
COMMENT ON COLUMN vigor_profiles.pace IS 'The pace the loss assumes, for example even: the window''s even pace, which drains the bucket exactly by its reset.';
COMMENT ON COLUMN vigor_profiles.placeholder IS 'The weight of every gate without a learned weight, 0 to 1, marked placeholder: 0.1 until a learned weight is approved (SGM-D15).';
COMMENT ON COLUMN vigor_profiles.gates IS 'The learned gate weights with their marking, a list of objects such as [{"family": "anthropic", "label": "Five hours", "value": 0.12, "source": "learned"}]; empty while every gate uses the placeholder.';
COMMENT ON COLUMN vigor_profiles.stale_rule IS 'The rule that makes a result stale, for example shortest-window: the report is older than the Subscription''s shortest window that is summed or can exhaust it (SGM-D31).';
COMMENT ON COLUMN vigor_profiles.recorded_at IS 'When the profile was written into this Root.';

CREATE TABLE IF NOT EXISTS vigor_reports (
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
COMMENT ON TABLE vigor_reports IS 'Every usage report as it arrived from a Driver: one row for each report whose fetchedAt is newer than the last recorded one of its Subscription (SGM-1, SGM-D22). Written by the Arbol process alone.';
COMMENT ON COLUMN vigor_reports.id IS 'The report record''s own identifier, a UUID the Arbol process gives it; a result names the report it used by it.';
COMMENT ON COLUMN vigor_reports.driver IS 'The Driver that delivered the report, for example claude.';
COMMENT ON COLUMN vigor_reports.subscription IS 'The Subscription''s identifier within its Driver, for example anthropic (DRV-D21).';
COMMENT ON COLUMN vigor_reports.family IS 'The Subscription''s vendor family, for example anthropic or kimi-coding; it chooses the window scopes (SGM-D32).';
COMMENT ON COLUMN vigor_reports.outcome IS 'The report''s outcome as the Driver Contract names it: ok, needs_sign_in, unavailable or unsupported (DRV-1).';
COMMENT ON COLUMN vigor_reports.fetched_at IS 'When the Driver fetched the report from the vendor, its fetchedAt; the latest of a Subscription is its last recorded report.';
COMMENT ON COLUMN vigor_reports.message IS 'The Driver''s message, present unless the outcome is ok; NULL otherwise.';
COMMENT ON COLUMN vigor_reports.windows IS 'The windows as delivered, a list of the Driver Contract''s window objects, for example [{"kind": "session", "label": "Five hours", "resource": "tokens", "usedPercent": 35, "resetsAt": "2026-10-26T13:20:00Z", "windowMinutes": 300, "limitReached": false}].';
COMMENT ON COLUMN vigor_reports.extra IS 'The report''s extra as delivered, the vendor''s related fields, for example {"isUsingOverage": false}; an empty object when the Driver delivered none.';
COMMENT ON COLUMN vigor_reports.arrived_at IS 'When the Arbol process read the report from the Driver.';
COMMENT ON COLUMN vigor_reports.run IS 'The run that produced the report, when one did and the Arbol process matched it, for example 9b3a2c1e-5c6d-4f70-9a1b-2c3d4e5f6a7b; NULL until then.';

CREATE TABLE IF NOT EXISTS vigor_results (
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
CREATE INDEX IF NOT EXISTS vigor_results_subscription ON vigor_results (driver, subscription, moment);
COMMENT ON TABLE vigor_results IS 'Every calculation of a Subscription''s Vigor with its inputs, the weights'' profile version, each window''s loss, the result, its state and its next change (SGM-1, SGM-D22). Written by the Arbol process alone.';
COMMENT ON COLUMN vigor_results.id IS 'The calculation record''s own identifier, a UUID the Arbol process gives it.';
COMMENT ON COLUMN vigor_results.driver IS 'The Driver of the Subscription, for example claude.';
COMMENT ON COLUMN vigor_results.subscription IS 'The Subscription''s identifier within its Driver, for example anthropic.';
COMMENT ON COLUMN vigor_results.family IS 'The Subscription''s vendor family, for example anthropic.';
COMMENT ON COLUMN vigor_results.moment IS 'The moment the calculation was made for: the clock it was given.';
COMMENT ON COLUMN vigor_results.report IS 'The report record the calculation used; NULL while there is no report yet (SGM-1.9).';
COMMENT ON COLUMN vigor_results.profile IS 'The version of the profile whose pace, weights and stale rule the calculation used, for example 1.';
COMMENT ON COLUMN vigor_results.losses IS 'Each window''s part in the result, in the order of the report: the window as used, which differs from the delivered one after a prediction, its role and its loss, for example [{"label": "Seven days", "resource": "tokens", "countedAs": "tokens", "assumed": false, "role": "store", "reached": false, "loss": 0.37, "weight": 1, "contribution": 0.37, "reason": null, "predicted": false, "usedPercent": 20, "resetsAt": "2026-10-29T10:00:00Z", "windowMinutes": 10080}].';
COMMENT ON COLUMN vigor_results.vigor IS 'The Subscription''s Vigor, 0 to 1; NULL when the result is unknown (SGM-1.9).';
COMMENT ON COLUMN vigor_results.exhausted IS 'true while a reached inference-gating window without overage exhausts the Subscription (SGM-1.5).';
COMMENT ON COLUMN vigor_results.predicted IS 'true when the calculation used a window predicted fresh after a reset without a newer report (SGM-1.7).';
COMMENT ON COLUMN vigor_results.stale IS 'The report''s age when the result is stale, the report being older than the profile''s stale rule allows; NULL when it is not (SGM-1.8).';
COMMENT ON COLUMN vigor_results.unknown IS 'The reason when the Vigor cannot be computed, shown after unknown: , for example allowance not supported for zai; NULL when it is known (SGM-1.9).';
COMMENT ON COLUMN vigor_results.notes IS 'What the calculation says on the result, a list of texts, for example ["5-hour window: the chatgpt report names no resource; counted as tokens"].';
COMMENT ON COLUMN vigor_results.next_change IS 'The next change of the Vigor: the earliest reset among the windows, or, while exhausted, the moment the last reached inference-gating window resets; NULL when no window names a reset time or the result is unknown (SGM-1.6).';
COMMENT ON COLUMN vigor_results.next_value IS 'The Vigor at the next change, computed on the windows predicted for that moment; NULL with next_change.';
COMMENT ON INDEX vigor_results_subscription IS 'Finds the latest result of a Subscription, and every result of it in the order of its moments, for the read and the replay.';
