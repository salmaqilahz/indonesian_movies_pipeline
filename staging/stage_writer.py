"""
Shared staging logic.

Every extractor writes its raw output through this single function,
so naming, timestamping, and folder structure stay consistent across
all three sources instead of being reimplemented three times.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def write_raw_json(records: list[dict], source: str, subtype: str, staging_dir: Path) -> Path:
    """
    Save raw records untouched into staging_data/<source>/<source>_<subtype>_raw_<timestamp>.json

    source:  which source produced this data — 'wikidata', 'tmdb', 'imdb'
    subtype: a label for this specific extraction within the source,
             e.g. 'movies' / 'tv' for TMDb, or just the source name again
             for sources that only produce one file (Wikidata, IMDb)
    staging_dir: the project's root staging directory (from config.settings.STAGING_DIR)
    """
    out_dir = staging_dir / source
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # Avoid doubling the name for single-file sources (e.g. "wikidata_wikidata_raw...")
    label = source if subtype == source else f"{source}_{subtype}"
    out_path = out_dir / f"{label}_raw_{timestamp}.json"

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    logger.info("Saved %d raw records to %s", len(records), out_path)
    return out_path
