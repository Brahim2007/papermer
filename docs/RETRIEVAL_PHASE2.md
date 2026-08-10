# Phase 2: canonical scholarly retrieval

## Research contract

This phase freezes a reproducible, non-LLM retrieval layer before any
language-model component is introduced. The comparison matrix is:

| Run | Candidate generation | Fusion | Purpose |
| --- | --- | --- | --- |
| C0 | popularity | none | query-independent popularity control |
| C1 | recency | none | query-independent recency control |
| B0 | TF-IDF | none | repaired historical baseline |
| B1 | BM25 | none | lexical baseline |
| B2 | SPECTER2 | none | scientific dense baseline |
| B3 | BM25 + SPECTER2 | RRF | score-scale-independent hybrid |
| B4 | citation graph | direct/coupling/co-citation | structural ablation |
| B5 | BM25 + SPECTER2 + graph | weighted RRF | three-channel hybrid |
| B6 | B3 candidates | cross-encoder | text reranking ablation |
| B7 | B5 candidates | cross-encoder | full non-LLM retrieval stack |

Any later LLM run must use the same corpus snapshot, query set, temporal
eligibility rule, and candidate budget as at least one of B1-B3.

## Canonical data contract

`CanonicalWorkRecord` is the boundary between external APIs and persistence.
Provider payloads are never treated as the canonical object directly.

Identity matching order:

1. source record (`source`, `external_id`);
2. DOI, arXiv, OpenAlex, or Semantic Scholar identifier;
3. normalized title and publication year.

The database retains:

- merged work metadata in `Article`;
- all known identifiers in `WorkIdentifier`;
- immutable source payload snapshots and checksums in `SourceRecord`;
- citation edges in `Citation`;
- field-level source ownership in `Article.provenance`.
- every metadata-enrichment outcome in `MetadataEnrichmentAttempt`, including
  negative outcomes and provider failures.

### Work versions and open access

`Article` is the canonical scholarly work. `WorkVersion` stores concrete
submitted, accepted, and published manifestations, so an arXiv preprint and a
journal version linked by DOI are not treated as separate retrieval documents.
The arXiv connector preserves the provider's versioned external identifier
while normalizing the work-level arXiv identifier without the `vN` suffix.

Unpaywall enrichment is DOI-based and auditable. Raw responses are retained in
`SourceRecord`, each usable OA location becomes a `WorkVersion`, and every
closed/not-found/request-error outcome is written to
`MetadataEnrichmentAttempt`. Generate a coverage artifact with:

`python manage.py report_version_coverage --output artifacts/version_oa_coverage.json`

Do not overwrite a frozen corpus snapshot merely because version or OA
metadata was added. Create and preregister a new corpus version if these fields
become experimental features.

## Frozen corpus scope v1

The first scoped snapshot uses the immutable JSON contract
`experiments/specs/paper_recommendation_scope_v1.json`: five declared search
queries, OpenAlex and Semantic Scholar providers, English article/review
content with abstracts, and publication dates from 2015-01-01 through
2026-08-04. Sampling is explicitly top-cited within each query/provider, so
popularity bias must be reported and tested with the C0 control.

The expansion command stores the exact spec hash and per-query counts. It
checkpoints atomically and can resume only when the spec hash is unchanged.
Identity matching remains canonical and does not rely on search rank.

Missing-abstract enrichment tries identifier-safe OpenAlex lookup first, then
Semantic Scholar DOI/S2/arXiv lookup. Outcomes such as
`provider_no_abstract`, `not_found`, and `request_error` are retained and
exported with the snapshot.

## Temporal protocol

For query time `t`, the candidate collection is exactly the set of
non-retracted papers with known publication date at or before `t`.
Relevant and seed identifiers are validated against the same rule. A known
year without month/day is represented as December 31 to avoid optimistic
early inclusion.

The manifest records corpus/query SHA-256 hashes, train and test boundaries,
and counts. Evaluation output records per-query metrics, eligible index size,
elapsed time, method, and the same hashes.

## Recommended paper experiments

- Report Recall@20/100, nDCG@10/20, MRR, and latency.
- Report query latency mean/p50/p95, sequential throughput, and index build
  time separately. Do not mix one-time model loading with steady-state query
  latency without labelling it.
- Use paired bootstrap confidence intervals across queries.
- Compare B0-B3 on identical temporal folds.
- Stratify by query year, discipline, query length, and popularity of relevant
  papers.
- Add ablations for RRF `k`, title-only versus title+abstract, and retracted
  work filtering.
- Sweep citation graph channel weight, direct citation, bibliographic
  coupling, and co-citation independently. A graph channel is not assumed to
  help.
- Hold cross-encoder candidate depth fixed (50, 100, or 200) across comparable
  runs and report both retrieval quality and latency.
- Freeze exact SPECTER2 model and adapter revisions before the main run.
- Cache dense document embeddings keyed by corpus hash and model revision.

Do not claim LLM improvement against a non-temporal or differently filtered
baseline.

## Snapshot quality gate

Every corpus used in a table must pass `audit_corpus_quality` with declared
thresholds. The report includes missing abstracts/DOIs, duplicate identifiers
and title-year pairs, invalid or future dates, source/language/type
distributions, outgoing-reference coverage, and internal-edge rate. The
`generate_csv --as-of-date` filter excludes works with known future issue
dates and records the excluded count in the snapshot manifest.

## Frozen model revisions

The default SPECTER2 configuration is pinned to:

- base: `3447645e1def9117997203454fa4495937bfbd83`;
- proximity adapter: `2081559630a80fc5851d8f798a05ba81e9468089`;
- ad-hoc query adapter: `3f4448817028388648a74349ece07af4518ec5bd`.

Changing any revision defines a different experimental condition and requires
a new embedding cache and run identifier.

The default cross-encoder is pinned in code. For multilingual Arabic/English
experiments, use the pinned mMARCO or BGE reranker constants and record the
exact revision. The small TinyBERT model is permitted for pipeline smoke tests
only, not as the claimed multilingual model.

## Citation graph artifact

`resolve_citations` links external references to canonical works when a known
identifier exists. `export_citation_graph` writes a corpus-aligned TSV and a
SHA-256 manifest. Retrieval implements direct neighbors, bibliographic
coupling, and co-citation. Temporal evaluation first filters candidate papers
by publication date; edges from ineligible citing papers are therefore not
indexed.

The current pilot graph is sparse internally. Its diagnostic results cannot be
used as evidence that graph retrieval improves effectiveness; graph coverage
must be reported with the final benchmark.

## Evidence levels

Smoke and diagnostic qrels exist only to prove the pipeline works. They must
be labelled `diagnostic only; not publication qrels`. Publication tables
require independently constructed relevance judgments, a frozen query
protocol, and uncertainty estimates across a substantially larger query set.
