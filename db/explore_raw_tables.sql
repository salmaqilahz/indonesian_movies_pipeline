-- ============================================================
-- EXPLORE RAW TABLES
-- Run with: psql -d film_series_db -f db/explore_raw_tables.sql
--
-- Purely exploratory — nothing here writes or changes data.
-- The overlap queries at the end are just curiosity checks on how
-- much cross-source agreement exists; they are NOT the real matching
-- logic (that's still a separate, deliberate stage).
-- ============================================================

\echo '--- Row counts ---'
SELECT 'raw_wikidata' AS table_name, COUNT(*) FROM raw_wikidata
UNION ALL
SELECT 'raw_tmdb', COUNT(*) FROM raw_tmdb
UNION ALL
SELECT 'raw_imdb', COUNT(*) FROM raw_imdb;


\echo '--- raw_wikidata: breakdown by instance_of_label ---'
SELECT instance_of_label, COUNT(*)
FROM raw_wikidata
GROUP BY instance_of_label
ORDER BY COUNT(*) DESC;


\echo '--- raw_tmdb: breakdown by media_type ---'
SELECT media_type, COUNT(*)
FROM raw_tmdb
GROUP BY media_type;


\echo '--- raw_imdb: breakdown by title_type ---'
SELECT title_type, COUNT(*)
FROM raw_imdb
GROUP BY title_type
ORDER BY COUNT(*) DESC;


\echo '--- Sample row from each table (just the extracted columns) ---'
SELECT wikidata_item, item_label, instance_of_label, imdb_id, tmdb_id
FROM raw_wikidata
LIMIT 3;

SELECT tmdb_id, media_type, title, release_date, original_language
FROM raw_tmdb
LIMIT 3;

SELECT tconst, title_type, primary_title, start_year, genres
FROM raw_imdb
LIMIT 3;


\echo '--- Reaching into the raw JSONB for fields we did not extract as columns ---'
-- e.g. TMDb's vote_average and popularity weren't given their own columns,
-- but the full record is still there in `raw`, queryable with ->> (returns text)
SELECT
    tmdb_id,
    title,
    raw->>'vote_average' AS vote_average,
    raw->>'popularity' AS popularity,
    raw->>'genre_ids' AS genre_ids
FROM raw_tmdb
ORDER BY (raw->>'popularity')::float DESC
LIMIT 10;


\echo '--- Curiosity check: how many Wikidata IMDb IDs actually exist in raw_imdb? ---'
-- Not real matching — just seeing how much of Wikidata's claimed IMDb IDs
-- are titles we actually captured in the IMDb extraction at all.
SELECT
    COUNT(*) FILTER (WHERE imdb_id IS NOT NULL) AS wikidata_rows_with_imdb_id,
    COUNT(*) FILTER (WHERE imdb_id IS NOT NULL AND imdb_id IN (SELECT tconst FROM raw_imdb)) AS also_found_in_raw_imdb
FROM raw_wikidata;


\echo '--- Curiosity check: how many Wikidata TMDb IDs exist in raw_tmdb? ---'
SELECT
    COUNT(*) FILTER (WHERE tmdb_id IS NOT NULL) AS wikidata_rows_with_tmdb_id,
    COUNT(*) FILTER (
        WHERE tmdb_id IS NOT NULL
        AND tmdb_id::bigint IN (SELECT tmdb_id::bigint FROM raw_tmdb)
    ) AS also_found_in_raw_tmdb
FROM raw_wikidata
WHERE tmdb_id ~ '^\d+$';  -- guard against any non-numeric tmdb_id values before casting
