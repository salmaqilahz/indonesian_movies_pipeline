"""
IMDb extractor.

Responsibility: pull raw title data from IMDb's public dataset dumps,
filtered to titles with an Indonesian release region, and save it
untouched into staging.

Important distinction (matches our schema's title_countries.role):
IMDb has no "country of origin" field. The closest we get is
title.akas.tsv.gz, which lists RELEASE regions, not production origin.
So this extractor answers "what was released in Indonesia", not
"what was made in Indonesia" — those are genuinely different questions,
and conflating them would be exactly the kind of data quality mistake
this whole project is trying to catch, not repeat.
"""

import gzip
import logging
import sys
import shutil
from pathlib import Path

import pandas as pd
import requests

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config.settings import IMDB_DATA_DIR, STAGING_DIR
from staging.stage_writer import write_raw_json

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

IMDB_BASE_URL = "https://datasets.imdbws.com"
RELEASE_REGION = "ID"
CHUNK_SIZE = 200_000  # rows per chunk when reading the large basics file

# Only keep IMDb title types that map cleanly onto our schema's content_type.
# Everything else (short, video, tvMovie, tvSpecial, tvShort, videoGame, etc.)
# is a deliberate scope decision, not an oversight — logged below so it's visible.
ALLOWED_TITLE_TYPES = {"movie", "tvSeries", "tvMiniSeries", "tvEpisode"}


def download_dataset(filename: str, force: bool = False) -> Path:
    """Download an IMDb dataset file if not already present locally."""
    IMDB_DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = IMDB_DATA_DIR / filename

    if out_path.exists() and not force:
        logger.info("%s already downloaded, skipping (%.1f MB)", filename, out_path.stat().st_size / 1e6)
        return out_path

    url = f"{IMDB_BASE_URL}/{filename}"
    logger.info("Downloading %s ...", url)
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with open(out_path, "wb") as f:
            shutil.copyfileobj(response.raw, f)

    logger.info("Downloaded %s (%.1f MB)", filename, out_path.stat().st_size / 1e6)
    return out_path


def find_indonesian_title_ids() -> set[str]:
    """
    Scan title.akas.tsv.gz in chunks and collect every tconst
    that has at least one Indonesian release region.
    """
    akas_path = download_dataset("title.akas.tsv.gz")
    logger.info("Scanning %s for region == '%s' ...", akas_path.name, RELEASE_REGION)

    matching_ids: set[str] = set()
    chunks_read = 0

    with gzip.open(akas_path, "rt", encoding="utf-8") as f:
        for chunk in pd.read_csv(
            f, sep="\t", chunksize=CHUNK_SIZE, dtype=str, na_values="\\N",
            usecols=["titleId", "region"],
        ):
            matches = chunk.loc[chunk["region"] == RELEASE_REGION, "titleId"]
            matching_ids.update(matches.tolist())
            chunks_read += 1
            if chunks_read % 10 == 0:
                logger.info("  ...scanned %d chunks, %d matching IDs so far", chunks_read, len(matching_ids))

    logger.info("Found %d titles with an Indonesian release region", len(matching_ids))
    return matching_ids


def extract_basics_for_ids(title_ids: set[str]) -> list[dict]:
    """
    Scan title.basics.tsv.gz in chunks and pull full rows for
    only the titles we already know have an Indonesian release region.
    """
    basics_path = download_dataset("title.basics.tsv.gz")
    logger.info("Scanning %s for %d matching title IDs ...", basics_path.name, len(title_ids))

    matched_rows: list[dict] = []
    chunks_read = 0

    with gzip.open(basics_path, "rt", encoding="utf-8") as f:
        for chunk in pd.read_csv(
            f, sep="\t", chunksize=CHUNK_SIZE, dtype=str, na_values="\\N",
        ):
            matched = chunk[chunk["tconst"].isin(title_ids)]
            if not matched.empty:
                matched_rows.extend(matched.to_dict(orient="records"))
            chunks_read += 1
            if chunks_read % 10 == 0:
                logger.info("  ...scanned %d chunks, %d matches so far", chunks_read, len(matched_rows))

    logger.info("Matched %d full title records", len(matched_rows))
    return matched_rows


def save_to_staging(records: list[dict]) -> Path:
    """Save the filtered (but otherwise untouched) IMDb records via the shared staging writer."""
    return write_raw_json(records, source="imdb", subtype="imdb", staging_dir=STAGING_DIR)


def filter_to_allowed_types(records: list[dict]) -> list[dict]:
    """
    Keep only title types that map cleanly onto our schema's content_type.
    Logs what's being dropped and why, so this scope decision stays visible
    rather than silently discarding data.
    """
    dropped_counts: dict[str, int] = {}
    kept = []

    for record in records:
        title_type = record.get("titleType", "?")
        if title_type in ALLOWED_TITLE_TYPES:
            kept.append(record)
        else:
            dropped_counts[title_type] = dropped_counts.get(title_type, 0) + 1

    total_dropped = sum(dropped_counts.values())
    logger.info("Kept %d records matching allowed types %s", len(kept), ALLOWED_TITLE_TYPES)
    if total_dropped:
        logger.info("Dropped %d records outside scope: %s", total_dropped, dropped_counts)

    return kept


def main():
    title_ids = find_indonesian_title_ids()
    records = extract_basics_for_ids(title_ids)
    records = filter_to_allowed_types(records)
    save_to_staging(records)


if __name__ == "__main__":
    main()
