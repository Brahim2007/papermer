# Retrieval experiments

This directory contains evaluation entry points, not production request code.

## TF-IDF baseline

1. Export a versioned corpus snapshot:

   `python generate_csv.py --from-date 2015-01-01 --as-of-date 2026-08-04 --output artifacts/corpus.csv`

The as-of filter excludes known future issue dates while recording the excluded
count in the manifest. Run the corpus quality gate before encoding:

`python -m experiments.audit_corpus_quality --corpus artifacts/corpus.csv --citation-graph artifacts/corpus.citations.tsv --as-of-date 2026-08-04 --output results/corpus_quality.json --fail-on-violation`

Enrich missing abstracts without losing negative outcomes:

`python manage.py enrich_abstracts --provider openalex --provider semantic_scholar --limit 100`

Each attempt is stored as `enriched`, `provider_no_abstract`, `not_found`,
`no_identifier`, `request_error`, or `identity_mismatch`. The latest status per
provider is included in the exported corpus snapshot.

Expand from a frozen topical/temporal contract:

`python manage.py expand_scholarly_corpus --spec experiments/specs/paper_recommendation_scope_v1.json --output results/corpus_expansion_scope_v1.json`

Long runs checkpoint after every provider/query unit and can continue with
`--resume` when the scope-spec hash is unchanged.

2. Prepare JSONL relevance judgments:

   `{"query_id":"q1","query":"scientific literature retrieval","relevant_ids":["id-1","id-2"]}`

3. Evaluate:

   `python -m experiments.evaluate_tfidf --corpus artifacts/corpus.csv --queries data/queries.jsonl --output results/tfidf.json`

Do not edit a corpus snapshot after recording results. Record its checksum,
the temporal cutoff, query-set version, random seeds (where applicable), and
the Git commit with every reported table.

## Temporal benchmark

Every JSONL query must additionally contain `query_date` and may contain
`seed_ids`. A relevant or seed paper published after `query_date` is rejected
as leakage.

Build a signed manifest:

`python -m experiments.build_temporal_benchmark --corpus artifacts/corpus.csv --queries data/temporal_queries.jsonl --train-end 2023-12-31 --test-end 2024-12-31 --output artifacts/temporal_manifest.json`

Evaluate one channel at a time:

`python -m experiments.evaluate_temporal --method bm25 --corpus artifacts/corpus.csv --queries data/temporal_queries.jsonl --train-end 2023-12-31 --test-end 2024-12-31 --output results/bm25_temporal.json`

Valid methods are `popularity`, `recency`, `tfidf`, `bm25`, `specter2`, `hybrid`, `graph`,
`hybrid_graph`, `hybrid_rerank`, and `hybrid_graph_rerank`. The hybrid uses
BM25 + SPECTER2 with Reciprocal Rank Fusion. SPECTER2 uses the official
proximity adapter for papers and ad-hoc query adapter for queries.

Export the corpus-aligned citation graph:

`python manage.py resolve_citations`

`python -m experiments.export_citation_graph --corpus artifacts/corpus.csv --output artifacts/corpus.citations.tsv`

Graph methods require `--citation-graph artifacts/corpus.citations.tsv`.
Use `--graph-rrf-weight` to ablate the structural channel independently.
Reranked methods accept `--reranker-candidate-k`, `--reranker-model`, and
`--reranker-revision`; never report an unpinned model revision.

## Frozen SPECTER2 cache

Encode a frozen corpus once:

`python -m experiments.build_specter2_cache --corpus artifacts/corpus.csv --output artifacts/corpus.specter2.npz --batch-size 16`

Then pass `--specter-cache artifacts/corpus.specter2.npz` to temporal
evaluation. The cache metadata records exact base-model and adapter commits,
the corpus SHA-256, dimensions, runtime versions, and device. Temporal folds
select eligible rows from this frozen matrix; they do not re-encode papers.

Hybrid ablations can set `--rrf-k`, `--candidate-k`, `--bm25-weight`, and
`--specter2-weight`. BM25 ablations can set `--bm25-k1` and `--bm25-b`. Every
value is persisted in the result JSON.

Compare only contract-compatible runs:

`python -m experiments.summarize_runs results/bm25.json results/specter2.json results/hybrid.json --output results/comparison.csv --label "publication qrels"`

The summarizer rejects runs with different corpus/query hashes, temporal
boundaries, protocols, or query counts.

## Publication benchmark construction

## External benchmark import

Import the two first publication benchmarks into an ignored artifact directory:

`python -m experiments.import_external_benchmark --dataset beir-scifact --dataset beir-scidocs`

Import LitSearch separately because its pinned official Parquet corpus download is about
1.2 GB:

`python -m experiments.import_external_benchmark --dataset litsearch`

Each output contains `corpus.jsonl`, the compatibility export `corpus.csv`,
`queries.jsonl`, `qrels.tsv`, `licenses.json`, and a SHA-256 manifest. Raw external data
must remain outside Git. Run the deterministic implementation check with:

`python -m experiments.external_benchmark_smoke --benchmark-dir artifacts/external/beir-scifact/beir-v1.0.0`

Run the publication matrix after building the pinned SPECTER2 cache. Lexical and
graph channels may be run first with repeated `--only` flags:

`python -m experiments.run_external_matrix --benchmark-dir artifacts/external/beir-scidocs/beir-v1.0.0 --output-dir results/external/beir-scidocs --only B0 --only B1 --only B4`

The runner records B4/B5/B7 as `not_applicable` when the upstream corpus has no
citation metadata (currently BEIR-SciFact); it never substitutes an empty graph.

Select stratified related-paper tasks:

`python -m experiments.sample_benchmark_seeds --corpus artifacts/corpus.csv --count 100 --from-date 2020-01-01 --to-date 2024-12-31 --output artifacts/query_draft.csv`

After human query authors complete the blank columns:

`python -m experiments.compile_benchmark_queries --draft artifacts/query_draft.csv --output artifacts/queries.jsonl`

Freeze query IDs before assessment (for a small pilot, an explicit development
count avoids rounding to an unusably small set):

`python -m experiments.freeze_benchmark_split --draft artifacts/query_draft.csv --dev-count 3 --output artifacts/query_split.json`

After compiling the human-authored queries, materialize the immutable split:

`python -m experiments.materialize_benchmark_split --queries artifacts/queries.jsonl --split-manifest artifacts/query_split.json --development-output artifacts/queries.development.jsonl --test-output artifacts/queries.test.jsonl --output-manifest artifacts/frozen_query_split.json`

Build method-blind, assessor-specific pools:

`python -m experiments.build_candidate_pool --corpus artifacts/corpus.csv --queries artifacts/queries.jsonl --specter-cache artifacts/corpus.specter2.npz --citation-graph artifacts/corpus.citations.tsv --methods bm25 specter2 hybrid graph hybrid_graph hybrid_rerank hybrid_graph_rerank --depth 20 --candidate-k 100 --reranker-candidate-k 100 --assessor assessor_a --assessor assessor_b --output artifacts/pool.jsonl --annotation-dir artifacts/annotations`

Analyze completed assessor files and create adjudication:

`python -m experiments.analyze_judgments --pool artifacts/pool.jsonl --judgments artifacts/annotations/assessor_a.csv artifacts/annotations/assessor_b.csv --report results/agreement.json --adjudication artifacts/adjudication.csv`

After resolving every conflict:

`python -m experiments.finalize_qrels --adjudication artifacts/adjudication.csv --agreement-report results/agreement.json --output artifacts/qrels.tsv`

Pass `--qrels artifacts/qrels.tsv` to `evaluate_temporal`. See
`docs/BENCHMARK_PROTOCOL.md` for the relevance scale, blinding rules, and
publication checks.

## Registered experiment matrix

The frozen experiment contract is
`experiments/specs/retrieval_preregistration_v1.json`. It records hashes for
the corpus, graph, SPECTER2 cache, and query-ID split; primary metric
`nDCG@10`; development grids; model revisions; and the confirmatory
multiple-comparison policy.

Run development only after human qrels are frozen:

`python -m experiments.run_registered_matrix --spec experiments/specs/retrieval_preregistration_v1.json --stage development --queries artifacts/queries.development.jsonl --qrels artifacts/qrels.development.tsv --output-dir results/registered_development`

Freeze one configuration per method family:

`python -m experiments.lock_development_runs --spec experiments/specs/retrieval_preregistration_v1.json --matrix-manifest results/registered_development/matrix_manifest.json --output artifacts/development_configuration_lock.json`

Then run the untouched test partition:

`python -m experiments.run_registered_matrix --spec experiments/specs/retrieval_preregistration_v1.json --stage test --queries artifacts/queries.test.jsonl --qrels artifacts/qrels.test.tsv --lock artifacts/development_configuration_lock.json --output-dir results/registered_test`

The runner rejects changed artifact hashes, wrong partition IDs, qrels from a
different partition, incomplete development matrices, and attempts to lock
diagnostic `--only` runs.

Compute query-paired bootstrap intervals against a declared baseline:

`python -m experiments.compare_runs_paired --baseline results/bm25.json --candidate results/hybrid.json --candidate results/hybrid_rerank.json --samples 10000 --output results/paired_comparisons.json`
