"""
Raw table loaders.

Responsibility: read the latest staging JSON for each source and load
it into that source's raw landing table in PostgreSQL. This is a
full-refresh load — each run truncates and reloads the raw table from
the current staging file, since staging_data/ already keeps the full
history as separate timestamped files. The raw tables just reflect
"what does the latest extraction look like", not history themselves.

No matching, no deduplication across sources here — that's deliberately
left for the (not yet built) matching stage.
"""

import json
import logging
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config.settings import DB_CONFIG, STAGING_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _get_connection():
    # Only pass through config values that are actually set, so
    # psycopg2 falls back to unix socket peer auth when they're None —
    # same pattern used throughout this project.
    conn_kwargs = {k: v for k, v in DB_CONFIG.items() if v is not None}
    return psycopg2.connect(**conn_kwargs)


def _latest_file(source: str, pattern: str) -> Path:
    matches = sorted((STAGING_DIR / source).glob(pattern))
    if not matches:
        raise FileNotFoundError(f"No staging files matching {pattern} in {STAGING_DIR / source}")
    return matches[-1]


def load_wikidata_raw():
    latest = _latest_file("wikidata", "wikidata_raw_*.json")
    logger.info("Loading %s into raw_wikidata ...", latest.name)

    with open(latest, encoding="utf-8") as f:
        records = json.load(f)

    rows = []
    for r in records:
        rows.append((
            r.get("item", {}).get("value"),
            r.get("itemLabel", {}).get("value"),
            r.get("instanceOfLabel", {}).get("value"),
            r.get("imdbId", {}).get("value"),
            r.get("tmdbId", {}).get("value"),
            r.get("publicationDate", {}).get("value"),
            latest.name,
            json.dumps(r),
        ))

    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE raw_wikidata")
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO raw_wikidata
                    (wikidata_item, item_label, instance_of_label, imdb_id, tmdb_id,
                     publication_date, source_file, raw)
                VALUES %s
                """,
                rows,
            )
        conn.commit()

    logger.info("Loaded %d rows into raw_wikidata", len(rows))


def load_tmdb_raw():
    movies_file = _latest_file("tmdb", "tmdb_movies_raw_*.json")
    tv_file = _latest_file("tmdb", "tmdb_tv_raw_*.json")

    rows = []

    with open(movies_file, encoding="utf-8") as f:
        for r in json.load(f):
            rows.append((
                r.get("id"), "movie", r.get("title"), r.get("release_date"),
                r.get("original_language"), movies_file.name, json.dumps(r),
            ))

    with open(tv_file, encoding="utf-8") as f:
        for r in json.load(f):
            rows.append((
                r.get("id"), "tv", r.get("name"), r.get("first_air_date"),
                r.get("original_language"), tv_file.name, json.dumps(r),
            ))

    logger.info("Loading %d TMDb records (movies + TV) into raw_tmdb ...", len(rows))

    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE raw_tmdb")
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO raw_tmdb
                    (tmdb_id, media_type, title, release_date, original_language, source_file, raw)
                VALUES %s
                """,
                rows,
            )
        conn.commit()

    logger.info("Loaded %d rows into raw_tmdb", len(rows))


def load_imdb_raw():
    latest = _latest_file("imdb", "imdb_raw_*.json")
    logger.info("Loading %s into raw_imdb ...", latest.name)

    with open(latest, encoding="utf-8") as f:
        records = json.load(f)

    rows = []
    for r in records:
        rows.append((
            r.get("tconst"),
            r.get("titleType"),
            r.get("primaryTitle"),
            r.get("originalTitle"),
            r.get("startYear"),
            r.get("runtimeMinutes"),
            r.get("genres"),
            latest.name,
            json.dumps(r),
        ))

    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE raw_imdb")
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO raw_imdb
                    (tconst, title_type, primary_title, original_title, start_year,
                     runtime_minutes, genres, source_file, raw)
                VALUES %s
                """,
                rows,
            )
        conn.commit()

    logger.info("Loaded %d rows into raw_imdb", len(rows))


def main():
    load_wikidata_raw()
    load_tmdb_raw()
    load_imdb_raw()


if __name__ == "__main__":
    main()
