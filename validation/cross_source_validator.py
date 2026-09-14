"""
Cross-source validator.

Matching answers "is this probably the same title across sources?"
This answers a different question: "now that we think it's the same
title, do the sources actually agree on its facts?"

The most important gap this closes: Layer 1 (exact ID matching) never
checked release year at all — it trusted the ID alone. So even a
"certain" match could carry a Wikidata year that disagrees with what
IMDb/TMDb report, completely undetected until now. That's exactly the
kind of thing this project exists to catch, not just matching for its
own sake.
"""

import logging
import re
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


def extract_year(date_str: str) -> int | None:
    if not date_str:
        return None
    match = re.match(r"^\s*(\d{4})", date_str)
    return int(match.group(1)) if match else None


def get_matched_pairs(conn) -> list[tuple]:
    """
    Every real match (any layer), joined back to its Wikidata source
    row and its matched IMDb/TMDb row, so we have both sides' data
    to compare.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                mc.wikidata_item,
                mc.match_type,
                mc.matched_value,
                w.item_label,
                w.publication_date
            FROM match_candidates mc
            JOIN raw_wikidata w ON w.wikidata_item = mc.wikidata_item
            WHERE mc.match_type != 'conflict'
        """)
        return cur.fetchall()


def get_imdb_years(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT tconst, start_year FROM raw_imdb")
        return {tconst: extract_year(year) for tconst, year in cur.fetchall()}


def get_tmdb_years(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT tmdb_id, release_date FROM raw_tmdb")
        return {str(tmdb_id): extract_year(date) for tmdb_id, date in cur.fetchall()}


def main():
    with _get_connection() as conn:
        matched_pairs = get_matched_pairs(conn)
        imdb_years = get_imdb_years(conn)
        tmdb_years = get_tmdb_years(conn)

        logger.info("Checking release year agreement for %d matched title/source pairs", len(matched_pairs))

        findings = []
        checked = 0
        disagreements = 0

        for wikidata_item, match_type, matched_value, item_label, publication_date in matched_pairs:
            wikidata_year = extract_year(publication_date)
            if wikidata_year is None or matched_value is None:
                continue  # nothing to compare

            source = "imdb" if "imdb" in match_type else "tmdb"
            source_year = imdb_years.get(matched_value) if source == "imdb" else tmdb_years.get(matched_value)
            if source_year is None:
                continue

            checked += 1
            agrees = wikidata_year == source_year

            # Layer 1 (exact ID) never checked year at all, so ANY disagreement there
            # is a genuinely new finding. Layers 2/3 already required agreement within
            # +/-1, so only a >1 year gap there would be unexpected (shouldn't happen,
            # but worth recording if it somehow does).
            if not agrees:
                disagreements += 1
                gap = abs(wikidata_year - source_year)
                findings.append((
                    wikidata_item, source, "release_year",
                    str(wikidata_year), str(source_year), False,
                    f"Matched via {match_type}; year gap of {gap} — Wikidata says {wikidata_year}, {source} says {source_year}",
                ))

        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE validation_findings")
            cur.executemany(
                """
                INSERT INTO validation_findings
                    (wikidata_item, matched_source, field_checked, wikidata_value, source_value, agrees, note)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                findings,
            )
        conn.commit()

        logger.info(
            "Checked %d matched pairs: %d agreed on release year, %d disagreed (recorded in validation_findings)",
            checked, checked - disagreements, disagreements,
        )


if __name__ == "__main__":
    main()
