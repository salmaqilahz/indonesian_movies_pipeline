"""
Layer 2 matching: title + year + type.

For Wikidata items that didn't get an exact ID match in Layer 1
(no usable ID at all, or the ID didn't exist in our extracted data),
try matching on a combination of normalized title, release year
(within +/-1, since sources sometimes disagree by a year), and
compatible content type.

Ambiguous cases — where a Wikidata item matches more than one
candidate — are skipped, not guessed at. This is deliberately
conservative: better to leave a title unmatched than to silently
merge two different movies that happen to share a title and year.
"""

import logging
import re
import sys
from collections import defaultdict
from pathlib import Path

import psycopg2

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config.settings import DB_CONFIG

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Wikidata instance_of_label -> compatible IMDb titleTypes / TMDb media_types
WIKIDATA_TO_IMDB_TYPES = {
    "film": {"movie"},
    "television series": {"tvSeries"},
    "web series": {"tvSeries"},  # IMDb has no dedicated web series type — see README known findings
    "miniseries": {"tvMiniSeries"},
}
WIKIDATA_TO_TMDB_TYPES = {
    "film": {"movie"},
    "television series": {"tv"},
    "web series": {"tv"},
    "miniseries": {"tv"},
}


def _get_connection():
    conn_kwargs = {k: v for k, v in DB_CONFIG.items() if v is not None}
    return psycopg2.connect(**conn_kwargs)


def normalize_title(title: str) -> str:
    """Lowercase, strip punctuation and extra whitespace, for comparison purposes only."""
    if not title:
        return ""
    title = title.lower()
    title = re.sub(r"[^\w\s]", "", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


def extract_year(date_str: str) -> int | None:
    """Pull a 4-digit year out of a date string, tolerating messy/partial formats."""
    if not date_str:
        return None
    match = re.match(r"^\s*(\d{4})", date_str)
    return int(match.group(1)) if match else None


def get_already_matched_items(conn) -> set[str]:
    """Wikidata items already resolved in Layer 1 (exact match or conflict) — skip these."""
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT wikidata_item FROM match_candidates WHERE wikidata_item IS NOT NULL")
        return {row[0] for row in cur.fetchall()}


def get_unmatched_wikidata_rows(conn, already_matched: set[str]) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT wikidata_item, item_label, instance_of_label, publication_date
            FROM raw_wikidata
        """)
        return [row for row in cur.fetchall() if row[0] not in already_matched]


def build_imdb_index(conn) -> dict[str, list[tuple]]:
    """normalized_title -> list of (tconst, year, title_type)."""
    index = defaultdict(list)
    with conn.cursor() as cur:
        cur.execute("SELECT tconst, primary_title, original_title, start_year, title_type FROM raw_imdb")
        for tconst, primary_title, original_title, start_year, title_type in cur.fetchall():
            year = extract_year(start_year)
            for title in {primary_title, original_title}:
                norm = normalize_title(title)
                if norm:
                    index[norm].append((tconst, year, title_type))
    return index


def build_tmdb_index(conn) -> dict[str, list[tuple]]:
    """normalized_title -> list of (tmdb_id, year, media_type)."""
    index = defaultdict(list)
    with conn.cursor() as cur:
        cur.execute("SELECT tmdb_id, title, release_date, media_type FROM raw_tmdb")
        for tmdb_id, title, release_date, media_type in cur.fetchall():
            year = extract_year(release_date)
            norm = normalize_title(title)
            if norm:
                index[norm].append((tmdb_id, year, media_type))
    return index


def _find_unique_match(candidates: list[tuple], target_year: int | None, allowed_types: set[str]):
    """
    Among same-title candidates, keep only those within +/-1 year and a
    compatible type. Return the single match, or None if zero or more
    than one candidate qualifies (ambiguous — skipped, not guessed).
    """
    if target_year is None:
        return None  # can't safely narrow down without a year to compare

    qualifying = [
        c for c in candidates
        if c[1] is not None and abs(c[1] - target_year) <= 1 and c[2] in allowed_types
    ]
    if len(qualifying) == 1:
        return qualifying[0]
    return None  # zero or ambiguous (>1) — both are skipped, not guessed at


def main():
    with _get_connection() as conn:
        already_matched = get_already_matched_items(conn)
        unmatched_rows = get_unmatched_wikidata_rows(conn, already_matched)
        logger.info("%d Wikidata items remain unmatched after Layer 1", len(unmatched_rows))

        imdb_index = build_imdb_index(conn)
        tmdb_index = build_tmdb_index(conn)

        imdb_matches = []
        tmdb_matches = []

        for wikidata_item, item_label, instance_of_label, publication_date in unmatched_rows:
            norm_title = normalize_title(item_label)
            year = extract_year(publication_date)
            if not norm_title or year is None:
                continue

            imdb_candidates = imdb_index.get(norm_title, [])
            allowed_imdb_types = WIKIDATA_TO_IMDB_TYPES.get(instance_of_label, set())
            imdb_match = _find_unique_match(imdb_candidates, year, allowed_imdb_types)
            if imdb_match:
                imdb_matches.append((wikidata_item, imdb_match[0]))

            tmdb_candidates = tmdb_index.get(norm_title, [])
            allowed_tmdb_types = WIKIDATA_TO_TMDB_TYPES.get(instance_of_label, set())
            tmdb_match = _find_unique_match(tmdb_candidates, year, allowed_tmdb_types)
            if tmdb_match:
                tmdb_matches.append((wikidata_item, str(tmdb_match[0])))

        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO match_candidates (wikidata_item, match_type, matched_value, confidence)
                VALUES (%s, 'year_type_imdb', %s, 'high')
                """,
                imdb_matches,
            )
            cur.executemany(
                """
                INSERT INTO match_candidates (wikidata_item, match_type, matched_value, confidence)
                VALUES (%s, 'year_type_tmdb', %s, 'high')
                """,
                tmdb_matches,
            )
        conn.commit()

        logger.info("Layer 2: matched %d items to IMDb, %d items to TMDb via title+year+type", len(imdb_matches), len(tmdb_matches))


if __name__ == "__main__":
    main()
