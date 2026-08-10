# PaperMetrix

PaperMetrix is a research prototype for personalized scientific-paper
retrieval and recommendation.  The codebase separates production web views
from reproducible offline retrieval experiments.

## Security notice

The historical source contained embedded credentials. They have been removed,
but the corresponding provider credentials must still be revoked and replaced.
Configuration now comes from environment variables; `.env` is ignored.

## Local setup

Requirements: Python 3.13, PostgreSQL 16, and Redis 7.

1. Create and activate a virtual environment.
2. Install dependencies:

   `python -m pip install -r req.txt`

3. Copy `.env.example` to `.env`; Django loads this ignored local file
   automatically. `DATABASE_URL` takes precedence over the individual `DB_*`
   values. If using the included Compose database, set
   `DB_PASSWORD=paper-dev-only`.
4. Start infrastructure:

   `docker compose up -d db redis`

5. Apply migrations and run checks:

   `python manage.py migrate`

   `python manage.py check`

   `python -m pytest`

6. Start Django:

   `python manage.py runserver`

Celery is optional for web development:

- worker: `celery -A PaperMetrics worker --loglevel=info`
- scheduler: `celery -A PaperMetrics beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler`

## Scholarly data ingestion

All providers are mapped into one canonical record before touching the
database. `Article` stores the merged work, while `WorkIdentifier`,
`SourceRecord`, `WorkVersion`, and `Citation` preserve identifiers, raw source
payloads, preprint/accepted/published versions, provenance, and graph edges.

Configure `OPENALEX_EMAIL`, `CROSSREF_EMAIL`, `UNPAYWALL_EMAIL`, and, strongly
recommended, `SEMANTIC_SCHOLAR_API_KEY`. Then ingest a bounded result set:

`python manage.py ingest_scholarly --source openalex --query "scientific paper recommendation" --limit 25`

Valid sources are `openalex`, `semantic_scholar`, `crossref`, and `arxiv`.
Identity
resolution prioritizes DOI, arXiv, OpenAlex, and Semantic Scholar identifiers,
with normalized title + year as a conservative fallback. Conflicting stable
identifiers fail instead of silently merging two papers.

Backfill conservative version rows, then enrich DOI records with Unpaywall:

`python manage.py backfill_work_versions --limit 1000`

`python manage.py enrich_open_access --limit 100`

Every Unpaywall outcome is recorded in `MetadataEnrichmentAttempt`. OA
locations become version rows, so accepted manuscripts and published versions
remain linked to one canonical work rather than becoming duplicate papers.

## Retrieval baselines

The production adapter is `frontend/recom.py`. The Django-independent,
deterministic implementation and metrics are under `retrieval/`.

Implemented experimental channels:

- TF-IDF;
- Okapi BM25;
- SPECTER2 with separate paper and ad-hoc query adapters;
- BM25 + SPECTER2 fused with Reciprocal Rank Fusion (RRF).

The live search endpoint (`/api/search/live/`) uses BM25 + TF-IDF RRF as an
always-available path and adds SPECTER2 when the registered embedding cache is
mounted. Every response names the active method, component ranks, matched
terms, and any dense-retrieval fallback; the UI never labels a sparse-only
result as semantic. Configure `SEMANTIC_SEARCH_ENABLED` and
`SPECTER2_CACHE_PATH` to control this behavior.

Online latency, per-component ranks, the staff evaluation dashboard, offline
artifact import, and the disabled-by-default LLM query-expansion arm are
documented in [`docs/ONLINE_EVALUATION.md`](docs/ONLINE_EVALUATION.md).

All sparse baselines:

- fit once per eligible corpus snapshot rather than once per query;
- preserves ranking order;
- returns numeric scores;
- has deterministic tie handling;
- exposes Precision, Recall, MRR, and nDCG evaluation.

See `experiments/README.md` for corpus export, judgment format, and evaluation.

## Reproducibility rules

For every reported experiment, record:

- Git commit;
- corpus snapshot checksum and temporal cutoff;
- query/qrels version;
- complete configuration and model revision;
- random seed;
- environment/package lock;
- per-query results, latency, and aggregate metrics.

Do not overwrite result files used in a paper. Use a new experiment identifier.

## Temporal evaluation

The temporal benchmark enforces `publication_date <= query_date` for every
indexed, seed, and relevant paper. Unknown day/month values are conservatively
assigned December 31 of the known year. Future papers therefore cannot leak
into an earlier query index.

See `experiments/README.md` for manifest generation and channel evaluation.
LLM query understanding and reranking remain intentionally outside this phase;
they should be introduced only after these non-LLM baselines are frozen.

## Production deployment

The production Compose stack builds the web service with CPU SPECTER2
dependencies and one multi-threaded Gunicorn worker, preventing duplicate
model copies on an 8 GB VPS. A background warm-up loads the query adapter while
the health endpoint remains available. Background workers continue to use the
smaller production dependency image.

Caddy terminates HTTPS and serves collected static files. Redis is isolated on
an internal Docker network; PostgreSQL is expected to be a managed external
service.

Copy `.env.production.example` to the ignored `.env.production` file, rotate
all previously exposed credentials, and follow
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). GitHub Actions run tests, Django
deployment checks, a container build, CodeQL, dependency review, and full
history secret scanning. CI also creates isolated deterministic research data,
logs in with a CI-only account, and runs axe against public and authenticated
search, paper, library, topic, and recommendation pages.

Do not publish research corpora, database dumps, generated embeddings, or API
credentials with the source repository.
