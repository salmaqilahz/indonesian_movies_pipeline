-- ============================================================
-- MATCH CANDIDATES
-- Holds the results of cross-source matching, kept separate from
-- the clean `titles` table so every match stays inspectable and
-- re-runnable before anything is committed as "final" data.
-- ============================================================

DROP TABLE IF EXISTS match_candidates;

CREATE TABLE match_candidates (
    match_id        BIGSERIAL PRIMARY KEY,
    wikidata_item   TEXT,              -- nullable: a shared-ID conflict has no single item to attach to
    match_type      VARCHAR(20) NOT NULL
                    CHECK (match_type IN ('exact_imdb', 'exact_tmdb', 'year_type_imdb', 'year_type_tmdb', 'conflict')),
    matched_value   TEXT,              -- the tconst or tmdb_id that matched (NULL for item-level conflicts)
    confidence      VARCHAR(10) NOT NULL DEFAULT 'exact'
                    CHECK (confidence IN ('exact', 'high', 'fuzzy', 'manual')),
    note            TEXT,              -- human-readable explanation, especially for conflicts
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_match_candidates_item ON match_candidates(wikidata_item);
CREATE INDEX idx_match_candidates_type ON match_candidates(match_type);
