"""
Wikidata extractor.

Responsibility: pull raw Indonesian film/TV/series data from Wikidata
via SPARQL, and save it untouched into the staging area. No cleaning,
no matching, no transforming — that happens in later pipeline stages.
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from SPARQLWrapper import JSON, SPARQLWrapper

import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))
from config.settings import (
    MAX_BACKOFF_SECONDS,
    MAX_RETRIES,
    STAGING_DIR,
    WIKIDATA_SPARQL_ENDPOINT,
    WIKIDATA_USER_AGENT,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# SPARQL query: Indonesian-origin films, TV series, and web series.
# P495 = country of origin, P31 = instance of.
# We ask Wikidata to also give us the IMDb ID (P345) and TMDb ID (P4947)
# directly, since that's our strongest signal for matching later.
INDONESIA_FILMS_QUERY = """
SELECT ?item ?itemLabel ?imdbId ?tmdbId ?publicationDate ?instanceOfLabel WHERE {
  ?item wdt:P495 wd:Q252 .            # country of origin = Indonesia
  ?item wdt:P31 ?instanceOf .
  VALUES ?instanceOf { wd:Q11424 wd:Q5398426 wd:Q526877 wd:Q1259759 }  # film / TV series / web series / miniseries

  OPTIONAL { ?item wdt:P345 ?imdbId. }
  OPTIONAL { ?item wdt:P4947 ?tmdbId. }
  OPTIONAL { ?item wdt:P577 ?publicationDate. }

  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,id". }
}
"""


def _run_query_with_retry(sparql: SPARQLWrapper) -> dict:
    """Run a SPARQL query with exponential backoff on rate-limit errors."""
    backoff = 60
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return sparql.query().convert()
        except Exception as exc:
            if attempt == MAX_RETRIES:
                logger.error("Giving up after %d attempts: %s", attempt, exc)
                raise
            logger.warning(
                "Attempt %d/%d failed (%s). Retrying in %ds...",
                attempt, MAX_RETRIES, exc, backoff,
            )
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)


def extract_indonesian_titles() -> list[dict]:
    """Fetch raw Indonesian title records from Wikidata via SPARQL."""
    sparql = SPARQLWrapper(WIKIDATA_SPARQL_ENDPOINT, agent=WIKIDATA_USER_AGENT)
    sparql.setQuery(INDONESIA_FILMS_QUERY)
    sparql.setReturnFormat(JSON)

    logger.info("Querying Wikidata for Indonesian films/series...")
    results = _run_query_with_retry(sparql)
    bindings = results["results"]["bindings"]
    logger.info("Retrieved %d raw results from Wikidata", len(bindings))
    return bindings


def save_to_staging(records: list[dict]) -> Path:
    """Save raw Wikidata results untouched, timestamped, into staging_data/wikidata/."""
    out_dir = STAGING_DIR / "wikidata"
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"wikidata_raw_{timestamp}.json"

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    logger.info("Saved %d raw records to %s", len(records), out_path)
    return out_path


def main():
    records = extract_indonesian_titles()
    save_to_staging(records)


if __name__ == "__main__":
    main()
