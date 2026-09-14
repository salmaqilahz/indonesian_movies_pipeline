"""
Layer 3 matching: fuzzy title matching.

The last-resort layer, for Wikidata items where neither an exact ID
nor an exact title+year+type match worked. Uses rapidfuzz to catch
spelling variants, alternate romanizations, and minor title
differences — but still requires: a compatible year, a compatible
type, a high similarity score, AND a clear best match (not two
candidates scoring nearly the same). Anything less certain gets
flagged for manual review rather than guessed at.

This is deliberately the most conservative layer, not the most
permissive — fuzzy matching is exactly where false-positive merges
are easiest to introduce by accident.
"""

import logging
import re
import sys
from collections import defaultdict
from pathlib import Path

import psycopg2
from rapidfuzz import fuzz

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config.settings import DB_CONFIG

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Same type-compatibility mapping as Layer 2 — kept in sync deliberately.
WIKIDATA_TO_IMDB_TYPES = {
    "film": {"movie"},
    "television series": {"tvSeries"},
    "web series": {"tvSeries"},
    "miniseries": {"tvMiniSeries"},
}
WIKIDATA_TO_TMDB_TYPES = {
    "film": {"movie"},
    "television series": {"tv"},
    "web series": {"tv"},
    "miniseries": {"tv"},
}

SIMILARITY_THRESHOLD = 90       # rapidfuzz score (0-100) required to even qualify
MIN_SCORE_GAP = 5               # best match must beat the runner-up by at least this much


def _get_connection():
    conn_kwargs = {k: v for k, v in DB_CONFIG.items() if v is not None}
    return psycopg2.connect(**conn_kwargs)


def normalize_title(title: str) -> str:
    if not title:
        return ""
    title = title.lower()
    title = re.sub(r"[^\w\s]", "", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


def extract_year(date_str: str) -> int | None:
    if not date_str:
        return None
    match = re.match(r"^\s*(\d{4})", date_str)
    return int(match.group(1)) if match else None


def get_already_matched_items(conn) -> set[str]:
    """Only real matches count as resolved — see the note in year_type_matcher.py."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT wikidata_item FROM match_candidates
            WHERE wikidata_item IS NOT NULL AND match_type != 'conflict'
        """)
        return {row[0] for row in cur.fetchall()}


def get_unmatched_wikidata_rows(conn, already_matched: set[str]) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT wikidata_item, item_label, instance_of_label, publication_date
            FROM raw_wikidata
        """)
        return [row for row in cur.fetchall() if row[0] not in already_matched]


def build_imdb_candidates_by_year(conn) -> dict[int, list[tuple]]:
    """year -> list of (tconst, title_for_comparison, title_type). Bucketed by year for speed."""
    buckets = defaultdict(list)
    with conn.cursor() as cur:
        cur.execute("SELECT tconst, primary_title, original_title, start_year, title_type FROM raw_imdb")
        for tconst, primary_title, original_title, start_year, title_type in cur.fetchall():
            year = extract_year(start_year)
            if year is None:
                continue
            for title in {primary_title, original_title}:
                if title:
                    buckets[year].append((tconst, title, title_type))
    return buckets


def build_tmdb_candidates_by_year(conn) -> dict[int, list[tuple]]:
    buckets = defaultdict(list)
    with conn.cursor() as cur:
        cur.execute("SELECT tmdb_id, title, release_date, media_type FROM raw_tmdb")
        for tmdb_id, title, release_date, media_type in cur.fetchall():
            year = extract_year(release_date)
            if year is None or not title:
                continue
            buckets[year].append((str(tmdb_id), title, media_type))
    return buckets


def _best_fuzzy_match(target_title: str, candidates_by_year: dict, target_year: int, allowed_types: set[str]):
    """
    Search candidates within +/-1 year, filtered to compatible type,
    score by rapidfuzz token_sort_ratio. Returns (match, score, note).
    Only returns a match if it clearly beats every other candidate.
    """
    pool = []
    for y in (target_year - 1, target_year, target_year + 1):
        pool.extend(candidates_by_year.get(y, []))

    pool = [c for c in pool if c[2] in allowed_types]
    if not pool:
        return None, None, None

    scored = [(c, fuzz.token_sort_ratio(target_title, normalize_title(c[1]))) for c in pool]
    scored.sort(key=lambda x: x[1], reverse=True)

    best_candidate, best_score = scored[0]
    if best_score < SIMILARITY_THRESHOLD:
        return None, None, None

    if len(scored) > 1:
        runner_up_score = scored[1][1]
        if best_score - runner_up_score < MIN_SCORE_GAP:
            return None, None, f"Top fuzzy matches too close to call ({best_score} vs {runner_up_score}) — skipped"

    return best_candidate, best_score, None


def main():
    with _get_connection() as conn:
        already_matched = get_already_matched_items(conn)
        unmatched_rows = get_unmatched_wikidata_rows(conn, already_matched)
        logger.info("%d Wikidata items remain unmatched after Layers 1 and 2", len(unmatched_rows))

        imdb_by_year = build_imdb_candidates_by_year(conn)
        tmdb_by_year = build_tmdb_candidates_by_year(conn)

        imdb_matches = []
        tmdb_matches = []
        skipped_conflicts = []

        for wikidata_item, item_label, instance_of_label, publication_date in unmatched_rows:
            norm_title = normalize_title(item_label)
            year = extract_year(publication_date)
            if not norm_title or year is None:
                continue

            allowed_imdb_types = WIKIDATA_TO_IMDB_TYPES.get(instance_of_label, set())
            match, score, note = _best_fuzzy_match(norm_title, imdb_by_year, year, allowed_imdb_types)
            if match:
                imdb_matches.append((wikidata_item, match[0], f"fuzzy score {score}"))
            elif note:
                skipped_conflicts.append((wikidata_item, f"[IMDb] {note}"))

            allowed_tmdb_types = WIKIDATA_TO_TMDB_TYPES.get(instance_of_label, set())
            match, score, note = _best_fuzzy_match(norm_title, tmdb_by_year, year, allowed_tmdb_types)
            if match:
                tmdb_matches.append((wikidata_item, match[0], f"fuzzy score {score}"))
            elif note:
                skipped_conflicts.append((wikidata_item, f"[TMDb] {note}"))

        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO match_candidates (wikidata_item, match_type, matched_value, confidence, note)
                VALUES (%s, 'fuzzy_imdb', %s, 'fuzzy', %s)
                """,
                imdb_matches,
            )
            cur.executemany(
                """
                INSERT INTO match_candidates (wikidata_item, match_type, matched_value, confidence, note)
                VALUES (%s, 'fuzzy_tmdb', %s, 'fuzzy', %s)
                """,
                tmdb_matches,
            )
            cur.executemany(
                """
                INSERT INTO match_candidates (wikidata_item, match_type, matched_value, confidence, note)
                VALUES (%s, 'conflict', NULL, 'manual', %s)
                """,
                skipped_conflicts,
            )
        conn.commit()

        logger.info(
            "Layer 3: fuzzy-matched %d items to IMDb, %d items to TMDb; %d ambiguous cases flagged for review",
            len(imdb_matches), len(tmdb_matches), len(skipped_conflicts),
        )


if __name__ == "__main__":
    main()
