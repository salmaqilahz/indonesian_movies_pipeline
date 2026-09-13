# Indonesian Film & Series Data Pipeline

A data engineering pipeline that extracts Indonesian film, TV series, and web series data from **Wikidata**, **TMDb**, and **IMDb**, reconciles it across sources, and loads it into PostgreSQL — with the long-term goal of detecting and correcting data quality issues in Wikidata itself.

## Motivation

While contributing to Wikimedia Indonesia's [Datathon](https://www.wikidata.org/wiki/Wikidata:WikiProject_Indonesia/Kegiatan/Datathon), inputting IMDb data into Indonesian Wikidata film/series entries, I found real, recurring data quality problems in Wikidata's coverage of Indonesian film and TV: incomplete fields, wrong categorizations, and typos. This project exists to catch those issues systematically rather than one at a time — by cross-checking every Wikidata claim against TMDb and IMDb, and flagging disagreements instead of trusting any single source blindly.

This is also my first data engineering portfolio project, so it's deliberately built in small, demonstrable stages rather than as one large script.

## Why three sources, not one

No single source is reliable enough on its own:

| Source | Strength | Limitation |
|---|---|---|
| Wikidata | Structured, linkable, editable | Community-maintained — has real errors and gaps |
| TMDb | Good API, decent country/genre metadata | "Origin country" isn't always "production country" |
| IMDb | Most complete title-level data | No API — only bulk dataset dumps; no country-of-origin field at all, only release regions |

Cross-referencing all three lets the pipeline catch disagreements — like a Wikidata item carrying two conflicting IMDb IDs — that no single source would ever reveal on its own.

## Architecture

```
Extraction  →  Staging  →  Matching  →  Validation  →  Load  →  Review  →  Wikidata export
(3 sources)   (raw JSON)   (cross-ref)  (agree/       (Postgres) (human    (QuickStatements
                                         disagree)                approval)  batch)
```

Each stage is a separate, independently runnable piece — see the folder structure below.

### Design principles

- **Extraction never transforms.** Each extractor's only job is to pull raw data and save it untouched, so bugs are traceable to a specific stage.
- **Never trust one source for a fact.** Country of origin, categories, and other key fields get cross-checked, not copied from whichever source happens to be queried first.
- **No silent data loss.** When data is filtered or scoped (e.g. dropping IMDb video games from an Indonesian release-region search), it's logged with counts, not silently dropped.
- **Wikidata edits are human-approved.** The pipeline proposes fixes; it never writes to Wikidata automatically. Approved batches go through [QuickStatements](https://quickstatements.toolforge.org/), which gives an undo trail.

## Tech stack

- **Python 3.11** — pipeline logic
- **PostgreSQL 16/17** — storage
- **SPARQLWrapper** — Wikidata SPARQL queries
- **requests** — TMDb API
- **pandas** — processing IMDb's bulk dataset dumps
- **psycopg2** — PostgreSQL access
- **rapidfuzz** — fuzzy title matching (planned)
- **GitHub Codespaces** — cloud dev environment (Python + Postgres via devcontainer)

## Project structure

```
indonesian_movies_pipeline/
├── config/settings.py       # central config, loaded from .env — no hardcoded secrets
├── extractors/               # one module per source — Wikidata, TMDb, IMDb
├── staging/                  # (planned) shared staging-save logic
├── matching/                 # (planned) cross-source ID/fuzzy matching
├── validation/                # (planned) cross-source fact comparison
├── loaders/                   # (planned) idempotent PostgreSQL loading
├── review/                    # (planned) human review queue for proposed fixes
├── wikidata_export/           # (planned) QuickStatements batch generation
├── db/schema_film_series.sql  # PostgreSQL schema
├── notebooks/                 # exploratory data quality checks per source
├── .devcontainer/              # Codespaces environment config
├── .env.example                # template for required environment variables
└── requirements.txt
```

## Database schema

Built around one canonical `titles` table, with `external_ids` bridging each title to its Wikidata/TMDb/IMDb identifiers. Country and language are tracked separately by `role` (`origin` vs `release_region`), since these mean genuinely different things and conflating them was one of the exact problems this project tries to avoid. Ratings are kept per-source rather than averaged, and every field can be traced back to where and when it was retrieved via `data_provenance`. Full schema: [`db/schema_film_series.sql`](db/schema_film_series.sql).

## Setup

```bash
git clone <repo-url>
cd indonesian_movies_pipeline
cp .env.example .env    # then fill in your TMDb API key
pip install -r requirements.txt
createdb film_series_db
psql -d film_series_db -f db/schema_film_series.sql
```

Or open in GitHub Codespaces — the devcontainer installs PostgreSQL and Python dependencies automatically.

## Running the extractors

```bash
python -m extractors.wikidata_extractor
python -m extractors.tmdb_extractor
python -m extractors.imdb_extractor
```

Each saves raw, timestamped JSON into `staging_data/<source>/` (gitignored — regenerable, not versioned).

## Current status

- [x] Schema design
- [x] Wikidata extractor (SPARQL, with retry/backoff and rate-limit handling)
- [x] TMDb extractor (paginated discover API, movies + TV)
- [x] IMDb extractor (bulk dataset dumps, chunked processing, filtered to Indonesian release region and in-scope title types)
- [x] Exploratory data quality checks per source (see `notebooks/`)
- [ ] Cross-source matching (exact ID → year+type → fuzzy fallback)
- [ ] Cross-source validation and confidence scoring
- [ ] Idempotent PostgreSQL loading
- [ ] Human review queue for flagged discrepancies
- [ ] QuickStatements export for approved Wikidata corrections
- [ ] Cleanup script for `staging_data/` — currently every extractor run keeps a new timestamped file forever; needs a retention policy (e.g. keep last N runs per source)

## Known data quality findings so far

Documented here rather than silently patched, since surfacing this kind of thing is the whole point of the project:

- Some Wikidata items carry more than one IMDb or TMDb ID (e.g. a title with two different IMDb IDs attached) — a genuine upstream data error, not a pipeline bug.
- TMDb's `origin_country` filter includes international co-productions, not only Indonesian-language content.
- IMDb has no "country of origin" field — only release regions, which is a materially different concept. Concretely, this means the IMDb extraction currently includes genuinely foreign films that simply had an Indonesian theatrical release — e.g. *Big Boss of Shanghai*, a Hong Kong production, gets pulled in purely because it has an `ID` entry in `title.akas`. This isn't a bug in the extractor; it's expected to be resolved during cross-source validation, once these titles are checked against Wikidata's and TMDb's actual country-of-origin fields, rather than guessed at from IMDb data alone.
- IMDb's title-type coverage includes categories (video games, shorts) that fall outside this project's scope and are explicitly filtered out, with counts logged.
