"""
TMDb extractor.

Responsibility: pull raw Indonesian-origin movies and TV shows from
TMDb's discover endpoints, and save them untouched into staging.
No cleaning, no matching against Wikidata — that happens later.
"""

import logging
import sys
import time
from pathlib import Path

import requests

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config.settings import (
    MAX_BACKOFF_SECONDS,
    MAX_RETRIES,
    STAGING_DIR,
    TMDB_API_KEY,
    TMDB_BASE_URL,
)
from staging.stage_writer import write_raw_json

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# TMDb's country filter for "origin country" — ISO 3166-1 alpha-2
ORIGIN_COUNTRY = "ID"


def _get_with_retry(url: str, params: dict) -> dict:
    """GET request with exponential backoff, specifically handling TMDb's 429 rate limit."""
    backoff = 5
    for attempt in range(1, MAX_RETRIES + 1):
        response = requests.get(url, params=params, timeout=30)

        if response.status_code == 200:
            return response.json()

        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", backoff))
            logger.warning(
                "Rate limited by TMDb (attempt %d/%d). Waiting %ds...",
                attempt, MAX_RETRIES, retry_after,
            )
            time.sleep(retry_after)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue

        # Any other error — log and raise, don't silently swallow it
        logger.error("TMDb request failed: %s %s", response.status_code, response.text[:200])
        response.raise_for_status()

    raise RuntimeError(f"Giving up on {url} after {MAX_RETRIES} attempts")


def _discover_all_pages(endpoint: str) -> list[dict]:
    """Page through a TMDb /discover endpoint, filtered to Indonesian origin, until exhausted."""
    url = f"{TMDB_BASE_URL}/{endpoint}"
    params = {
        "api_key": TMDB_API_KEY,
        "with_origin_country": ORIGIN_COUNTRY,
        "page": 1,
        "sort_by": "popularity.desc",
    }

    first_page = _get_with_retry(url, params)
    total_pages = first_page.get("total_pages", 1)
    # TMDb caps pagination at 500 pages regardless of total_pages reported
    total_pages = min(total_pages, 500)

    all_results = list(first_page.get("results", []))
    logger.info("%s: page 1/%d (%d results so far)", endpoint, total_pages, len(all_results))

    for page in range(2, total_pages + 1):
        params["page"] = page
        data = _get_with_retry(url, params)
        all_results.extend(data.get("results", []))
        if page % 10 == 0 or page == total_pages:
            logger.info("%s: page %d/%d (%d results so far)", endpoint, page, total_pages, len(all_results))

    return all_results


def extract_movies() -> list[dict]:
    logger.info("Discovering Indonesian-origin movies from TMDb...")
    return _discover_all_pages("discover/movie")


def extract_tv_shows() -> list[dict]:
    logger.info("Discovering Indonesian-origin TV shows from TMDb...")
    return _discover_all_pages("discover/tv")


def save_to_staging(records: list[dict], subtype: str) -> Path:
    """Save raw TMDb results untouched into staging, via the shared staging writer."""
    return write_raw_json(records, source="tmdb", subtype=subtype, staging_dir=STAGING_DIR)


def main():
    if not TMDB_API_KEY:
        raise RuntimeError("TMDB_API_KEY is not set — check your .env file")

    movies = extract_movies()
    save_to_staging(movies, "movies")

    tv_shows = extract_tv_shows()
    save_to_staging(tv_shows, "tv")


if __name__ == "__main__":
    main()
