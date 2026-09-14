-- ============================================================
-- VALIDATION FINDINGS
-- For titles that already matched (any layer), compare specific
-- facts across sources and record disagreements. A successful match
-- means "this is probably the same title" — it does NOT mean every
-- field the sources report about it agrees. That's what this checks.
-- ============================================================

DROP TABLE IF EXISTS validation_findings;

CREATE TABLE validation_findings (
    finding_id      BIGSERIAL PRIMARY KEY,
    wikidata_item   TEXT NOT NULL,
    matched_source  VARCHAR(10) NOT NULL CHECK (matched_source IN ('imdb', 'tmdb')),
    field_checked   VARCHAR(20) NOT NULL,   -- 'release_year', 'title', etc.
    wikidata_value  TEXT,
    source_value    TEXT,
    agrees          BOOLEAN NOT NULL,
    note            TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_validation_findings_item ON validation_findings(wikidata_item);
CREATE INDEX idx_validation_findings_agrees ON validation_findings(agrees);
