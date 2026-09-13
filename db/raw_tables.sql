-- ============================================================
-- RAW LANDING TABLES
-- One per source, loaded directly from staging JSON.
-- Purpose: get staged data into Postgres, queryable, before any
-- cross-source matching happens. These are intentionally messy —
-- duplicates and conflicts from the source data are preserved,
-- not resolved here. That's the matching stage's job, later.
--
-- Pattern: a few key columns extracted for easy querying, plus
-- a `raw` JSONB column holding the entire original record, so
-- nothing is ever lost even for fields we didn't think to extract.
-- ============================================================

DROP TABLE IF EXISTS raw_imdb;
DROP TABLE IF EXISTS raw_tmdb;
DROP TABLE IF EXISTS raw_wikidata;


-- ============================================================
-- raw_wikidata
-- ============================================================
CREATE TABLE raw_wikidata (
    raw_id              BIGSERIAL PRIMARY KEY,
    wikidata_item       TEXT NOT NULL,          -- full URI, e.g. http://www.wikidata.org/entity/Q12345
    item_label          TEXT,
    instance_of_label   TEXT,                    -- film / television series / web series / miniseries
    imdb_id             TEXT,
    tmdb_id             TEXT,
    publication_date    TEXT,                    -- kept as text at this layer; parsed properly later
    source_file         TEXT NOT NULL,           -- which staging_data file this row came from
    loaded_at           TIMESTAMP DEFAULT NOW(),
    raw                 JSONB NOT NULL           -- the full original record, untouched
);

CREATE INDEX idx_raw_wikidata_item ON raw_wikidata(wikidata_item);
CREATE INDEX idx_raw_wikidata_imdb ON raw_wikidata(imdb_id);
CREATE INDEX idx_raw_wikidata_tmdb ON raw_wikidata(tmdb_id);


-- ============================================================
-- raw_tmdb
-- Movies and TV share one table (media_type distinguishes them),
-- since they're both "TMDb records" at this raw layer.
-- ============================================================
CREATE TABLE raw_tmdb (
    raw_id              BIGSERIAL PRIMARY KEY,
    tmdb_id             INTEGER NOT NULL,
    media_type          VARCHAR(10) NOT NULL CHECK (media_type IN ('movie', 'tv')),
    title               TEXT,                    -- 'title' for movies, 'name' for TV — normalized here
    release_date        TEXT,                    -- 'release_date' for movies, 'first_air_date' for TV
    original_language   TEXT,
    source_file         TEXT NOT NULL,
    loaded_at           TIMESTAMP DEFAULT NOW(),
    raw                 JSONB NOT NULL
);

CREATE INDEX idx_raw_tmdb_id ON raw_tmdb(tmdb_id);
CREATE INDEX idx_raw_tmdb_media_type ON raw_tmdb(media_type);


-- ============================================================
-- raw_imdb
-- ============================================================
CREATE TABLE raw_imdb (
    raw_id              BIGSERIAL PRIMARY KEY,
    tconst              TEXT NOT NULL,           -- IMDb's own ID, e.g. tt1234567
    title_type          TEXT,
    primary_title       TEXT,
    original_title      TEXT,
    start_year          TEXT,
    runtime_minutes     TEXT,
    genres              TEXT,
    source_file         TEXT NOT NULL,
    loaded_at           TIMESTAMP DEFAULT NOW(),
    raw                 JSONB NOT NULL
);

CREATE INDEX idx_raw_imdb_tconst ON raw_imdb(tconst);
