"""
Central configuration for the pipeline.

Everything here is loaded from environment variables (via a .env file
in local development). Nothing sensitive is hardcoded, so this file
is safe to commit to a public repo.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load variables from a .env file if one exists in the project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


# --- Database ---
# Left as None by default so psycopg2 falls back to unix socket peer
# auth, which is how Salma's local Postgres is set up.
DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "film_series_db"),
    "user": os.getenv("DB_USER") or None,
    "password": os.getenv("DB_PASSWORD") or None,
    "host": os.getenv("DB_HOST") or None,
    "port": os.getenv("DB_PORT") or None,
}

# --- TMDb ---
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
TMDB_BASE_URL = "https://api.themoviedb.org/3"

# --- Wikidata ---
WIKIDATA_SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
WIKIDATA_USER_AGENT = os.getenv(
    "WIKIDATA_USER_AGENT",
    "IndonesianFilmPipeline/1.0 (portfolio project)",
)

# --- IMDb dataset dumps ---
IMDB_DATA_DIR = Path(os.getenv("IMDB_DATA_DIR", PROJECT_ROOT / "data" / "imdb"))

# --- Staging ---
STAGING_DIR = PROJECT_ROOT / "staging_data"

# --- Retry / rate limiting ---
MAX_RETRIES = 5
INITIAL_BACKOFF_SECONDS = 60
MAX_BACKOFF_SECONDS = 300
