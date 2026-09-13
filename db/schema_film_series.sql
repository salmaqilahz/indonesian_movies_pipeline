-- ============================================================
-- SCHEMA: Film, Web Series, TV Series
-- Sources: IMDb, TMDb, Wikidata
-- Target: PostgreSQL
-- ============================================================

DROP TABLE IF EXISTS data_provenance CASCADE;
DROP TABLE IF EXISTS title_ratings CASCADE;
DROP TABLE IF EXISTS series_episodes CASCADE;
DROP TABLE IF EXISTS title_crew CASCADE;
DROP TABLE IF EXISTS person_external_ids CASCADE;
DROP TABLE IF EXISTS persons CASCADE;
DROP TABLE IF EXISTS title_genres CASCADE;
DROP TABLE IF EXISTS genres CASCADE;
DROP TABLE IF EXISTS title_languages CASCADE;
DROP TABLE IF EXISTS title_countries CASCADE;
DROP TABLE IF EXISTS external_ids CASCADE;
DROP TABLE IF EXISTS titles CASCADE;


-- ============================================================
-- 1. MASTER TABLE — canonical entity (film/series/episode)
-- ============================================================
CREATE TABLE titles (
    title_id        BIGSERIAL PRIMARY KEY,
    content_type    VARCHAR(20) NOT NULL
                    CHECK (content_type IN ('movie', 'web_series', 'tv_series', 'mini_series', 'episode')),
    primary_title   TEXT NOT NULL,
    original_title  TEXT,
    release_year    SMALLINT,
    end_year        SMALLINT,               -- NULL if film or series still ongoing
    runtime_minutes INTEGER,
    is_adult        BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE titles IS 'Master canonical entity table: one row = one film/series/episode, regardless of source';


-- ============================================================
-- 2. EXTERNAL ID MAPPING — cross-source reconciliation key
-- ============================================================
CREATE TABLE external_ids (
    external_id_pk  BIGSERIAL PRIMARY KEY,
    title_id        BIGINT NOT NULL REFERENCES titles(title_id) ON DELETE CASCADE,
    source          VARCHAR(20) NOT NULL CHECK (source IN ('imdb', 'tmdb', 'wikidata')),
    source_id       VARCHAR(50) NOT NULL,   -- e.g. tt1234567 / 12345 / Q12345
    confidence      VARCHAR(10) DEFAULT 'exact'
                    CHECK (confidence IN ('exact', 'fuzzy', 'manual')),
    matched_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE (source, source_id)
);
CREATE INDEX idx_ext_title ON external_ids(title_id);

COMMENT ON TABLE external_ids IS 'Bridges IDs from IMDb/TMDb/Wikidata to one canonical title_id';


-- ============================================================
-- 3. COUNTRY & LANGUAGE — separate production vs release country
-- ============================================================
CREATE TABLE title_countries (
    title_id        BIGINT NOT NULL REFERENCES titles(title_id) ON DELETE CASCADE,
    country_code    CHAR(2) NOT NULL,       -- ISO 3166-1 alpha-2, e.g. 'ID'
    role            VARCHAR(20) NOT NULL DEFAULT 'production'
                    CHECK (role IN ('production', 'origin', 'release_region')),
    source          VARCHAR(20),            -- data origin: 'wikidata_p495', 'tmdb', 'imdb_akas'
    PRIMARY KEY (title_id, country_code, role)
);

COMMENT ON COLUMN title_countries.role IS
    'origin = country of production origin (Wikidata P495); release_region = release territory (IMDb akas region)';

CREATE TABLE title_languages (
    title_id        BIGINT NOT NULL REFERENCES titles(title_id) ON DELETE CASCADE,
    language_code   VARCHAR(10) NOT NULL,   -- 'id', 'en', etc (ISO 639-1)
    is_original     BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (title_id, language_code)
);


-- ============================================================
-- 4. GENRES — many-to-many relation
-- ============================================================
CREATE TABLE genres (
    genre_id    SERIAL PRIMARY KEY,
    genre_name  VARCHAR(50) UNIQUE NOT NULL
);

CREATE TABLE title_genres (
    title_id    BIGINT NOT NULL REFERENCES titles(title_id) ON DELETE CASCADE,
    genre_id    INTEGER NOT NULL REFERENCES genres(genre_id) ON DELETE CASCADE,
    PRIMARY KEY (title_id, genre_id)
);


-- ============================================================
-- 5. PEOPLE — cast & crew, shared across all titles
-- ============================================================
CREATE TABLE persons (
    person_id       BIGSERIAL PRIMARY KEY,
    primary_name    TEXT NOT NULL,
    birth_year      SMALLINT,
    death_year      SMALLINT
);

CREATE TABLE person_external_ids (
    person_id   BIGINT NOT NULL REFERENCES persons(person_id) ON DELETE CASCADE,
    source      VARCHAR(20) NOT NULL CHECK (source IN ('imdb', 'tmdb', 'wikidata')),
    source_id   VARCHAR(50) NOT NULL,
    PRIMARY KEY (source, source_id)
);

CREATE TABLE title_crew (
    title_id        BIGINT NOT NULL REFERENCES titles(title_id) ON DELETE CASCADE,
    person_id       BIGINT NOT NULL REFERENCES persons(person_id) ON DELETE CASCADE,
    role            VARCHAR(30) NOT NULL,   -- 'director','writer','actor','producer', etc
    character_name  TEXT,                    -- filled when role = 'actor'
    billing_order   SMALLINT,
    PRIMARY KEY (title_id, person_id, role)
);


-- ============================================================
-- 6. SERIES STRUCTURE — parent-child relation (series -> episode)
-- ============================================================
CREATE TABLE series_episodes (
    episode_title_id  BIGINT PRIMARY KEY REFERENCES titles(title_id) ON DELETE CASCADE,
    parent_series_id  BIGINT NOT NULL REFERENCES titles(title_id) ON DELETE CASCADE,
    season_number     SMALLINT,
    episode_number    SMALLINT
);

COMMENT ON TABLE series_episodes IS
    'Links an episode (content_type=episode) to its parent series (web_series/tv_series)';


-- ============================================================
-- 7. RATINGS PER SOURCE — never averaged into one number
-- ============================================================
CREATE TABLE title_ratings (
    title_id        BIGINT NOT NULL REFERENCES titles(title_id) ON DELETE CASCADE,
    source          VARCHAR(20) NOT NULL CHECK (source IN ('imdb', 'tmdb', 'wikidata')),
    average_rating  DECIMAL(3,1),
    vote_count      INTEGER,
    fetched_at      TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (title_id, source)
);


-- ============================================================
-- 8. PROVENANCE — audit trail per field (needed for Wikidata citation)
-- ============================================================
CREATE TABLE data_provenance (
    provenance_id BIGSERIAL PRIMARY KEY,
    title_id      BIGINT NOT NULL REFERENCES titles(title_id) ON DELETE CASCADE,
    field_name    VARCHAR(50) NOT NULL,
    source        VARCHAR(20) NOT NULL CHECK (source IN ('imdb', 'tmdb', 'wikidata')),
    source_url    TEXT,
    retrieved_at  TIMESTAMP DEFAULT NOW()
);


-- ============================================================
-- ADDITIONAL INDEXES for common queries
-- ============================================================
CREATE INDEX idx_titles_content_type ON titles(content_type);
CREATE INDEX idx_titles_release_year ON titles(release_year);
CREATE INDEX idx_title_countries_code ON title_countries(country_code);
CREATE INDEX idx_title_crew_person ON title_crew(person_id);


-- ============================================================
-- SAMPLE DATA — Indonesian film as illustration
-- ============================================================
INSERT INTO titles (content_type, primary_title, original_title, release_year, runtime_minutes)
VALUES ('movie', 'Laskar Pelangi', 'Laskar Pelangi', 2008, 125);
-- title_id = 1 (assuming a fresh table)

INSERT INTO external_ids (title_id, source, source_id, confidence) VALUES
(1, 'imdb', 'tt1240643', 'exact'),
(1, 'wikidata', 'Q3213097', 'exact'),
(1, 'tmdb', '13268', 'exact');

INSERT INTO title_countries (title_id, country_code, role, source) VALUES
(1, 'ID', 'origin', 'wikidata_p495'),
(1, 'ID', 'release_region', 'imdb_akas');

INSERT INTO title_languages (title_id, language_code, is_original) VALUES
(1, 'id', TRUE);

INSERT INTO genres (genre_name) VALUES ('Drama'), ('Family') ON CONFLICT DO NOTHING;

INSERT INTO title_genres (title_id, genre_id)
SELECT 1, genre_id FROM genres WHERE genre_name IN ('Drama', 'Family');

INSERT INTO title_ratings (title_id, source, average_rating, vote_count) VALUES
(1, 'imdb', 7.9, 25000),
(1, 'tmdb', 7.7, 320);


-- ============================================================
-- EXAMPLE QUERY: Indonesian films across sources
-- ============================================================
-- SELECT t.primary_title, t.release_year, e.source, e.source_id
-- FROM titles t
-- JOIN title_countries tc ON t.title_id = tc.title_id AND tc.role = 'origin'
-- JOIN external_ids e ON t.title_id = e.title_id
-- WHERE tc.country_code = 'ID' AND t.content_type = 'movie';
