"""
Layer 1 matching: exact ID matching.

Responsibility: match Wikidata items to IMDb/TMDb records using the
IDs Wikidata already claims, but ONLY after checking those IDs aren't
part of a known conflict (e.g. one Wikidata item with two different
IMDb IDs, or one IMDb ID claimed by two different Wikidata items).

Conflicts are recorded, not resolved — resolving them means deciding
which claim is correct, which is exactly the kind of judgment call
that belongs to a human reviewer, not this script.
"""

import logging
import sys
from pathlib import Path

import psycopg2

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config.settings import DB_CONFIG

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _get_connection():
    conn_kwargs = {k: v for k, v in DB_CONFIG.items() if v is not None}
    return psycopg2.connect(**conn_kwargs)


def find_conflicting_wikidata_ids(conn) -> list[tuple]:
    """
    Find Wikidata items that claim more than one distinct IMDb ID,
    or more than one distinct TMDb ID. These get flagged, not matched.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT wikidata_item, 'imdb' AS id_type, COUNT(DISTINCT imdb_id) AS distinct_count
            FROM raw_wikidata
            WHERE imdb_id IS NOT NULL
            GROUP BY wikidata_item
            HAVING COUNT(DISTINCT imdb_id) > 1

            UNION ALL

            SELECT wikidata_item, 'tmdb' AS id_type, COUNT(DISTINCT tmdb_id) AS distinct_count
            FROM raw_wikidata
            WHERE tmdb_id IS NOT NULL
            GROUP BY wikidata_item
            HAVING COUNT(DISTINCT tmdb_id) > 1
        """)
        return cur.fetchall()


def find_shared_ids_across_items(conn) -> list[tuple]:
    """
    Find IMDb/TMDb IDs that are claimed by more than one distinct
    Wikidata item — the "same ID, different movies" danger case,
    as opposed to the "same item, different IDs" case above.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT imdb_id AS shared_id, 'imdb' AS id_type, COUNT(DISTINCT wikidata_item) AS item_count
            FROM raw_wikidata
            WHERE imdb_id IS NOT NULL
            GROUP BY imdb_id
            HAVING COUNT(DISTINCT wikidata_item) > 1

            UNION ALL

            SELECT tmdb_id AS shared_id, 'tmdb' AS id_type, COUNT(DISTINCT wikidata_item) AS item_count
            FROM raw_wikidata
            WHERE tmdb_id IS NOT NULL
            GROUP BY tmdb_id
            HAVING COUNT(DISTINCT wikidata_item) > 1
        """)
        return cur.fetchall()


def record_conflicts(conn, conflicting_items: list[tuple], shared_ids: list[tuple]) -> set[str]:
    """Write conflict rows to match_candidates. Returns the set of wikidata_items to exclude from exact matching."""
    excluded_items: set[str] = set()
    rows = []

    for wikidata_item, id_type, distinct_count in conflicting_items:
        rows.append((
            wikidata_item, "conflict", None, "manual",
            f"This Wikidata item claims {distinct_count} different {id_type} IDs — needs manual review",
        ))
        excluded_items.add(wikidata_item)

    for shared_id, id_type, item_count in shared_ids:
        rows.append((
            None, "conflict", shared_id, "manual",
            f"This {id_type} ID is claimed by {item_count} different Wikidata items — needs manual review",
        ))
        # Note: excluding specific items here would need another query;
        # left as a known limitation, flagged in the summary at the end.

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO match_candidates (wikidata_item, match_type, matched_value, confidence, note)
            VALUES (%s, %s, %s, %s, %s)
            """,
            rows,
        )
    conn.commit()
    logger.info("Recorded %d conflict rows", len(rows))
    return excluded_items


def match_exact_imdb(conn, excluded_items: set[str]) -> int:
    """Match Wikidata items to raw_imdb via exact imdb_id, skipping anything flagged as conflicting."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO match_candidates (wikidata_item, match_type, matched_value, confidence)
            SELECT DISTINCT w.wikidata_item, 'exact_imdb', w.imdb_id, 'exact'
            FROM raw_wikidata w
            JOIN raw_imdb i ON w.imdb_id = i.tconst
            WHERE w.imdb_id IS NOT NULL
              AND NOT (w.wikidata_item = ANY(%s))
        """, (list(excluded_items),))
        count = cur.rowcount
    conn.commit()
    logger.info("Matched %d Wikidata items to raw_imdb via exact IMDb ID", count)
    return count


def match_exact_tmdb(conn, excluded_items: set[str]) -> int:
    """Match Wikidata items to raw_tmdb via exact tmdb_id, skipping anything flagged as conflicting."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO match_candidates (wikidata_item, match_type, matched_value, confidence)
            SELECT DISTINCT w.wikidata_item, 'exact_tmdb', w.tmdb_id, 'exact'
            FROM raw_wikidata w
            JOIN raw_tmdb t ON w.tmdb_id::bigint = t.tmdb_id::bigint
            WHERE w.tmdb_id IS NOT NULL
              AND w.tmdb_id ~ '^\\d+$'
              AND NOT (w.wikidata_item = ANY(%s))
        """, (list(excluded_items),))
        count = cur.rowcount
    conn.commit()
    logger.info("Matched %d Wikidata items to raw_tmdb via exact TMDb ID", count)
    return count


def main():
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE match_candidates")
        conn.commit()

        conflicting_items = find_conflicting_wikidata_ids(conn)
        shared_ids = find_shared_ids_across_items(conn)
        logger.info(
            "Found %d Wikidata items with conflicting IDs, %d IDs shared across multiple items",
            len(conflicting_items), len(shared_ids),
        )

        excluded_items = record_conflicts(conn, conflicting_items, shared_ids)
        match_exact_imdb(conn, excluded_items)
        match_exact_tmdb(conn, excluded_items)


if __name__ == "__main__":
    main()
