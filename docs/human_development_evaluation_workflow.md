# Human development evaluation workflow

This workflow never evaluates the frozen test assignment. Human input is required
at the two marked gates; scripts must not synthesize queries or relevance labels.

## Gate 1 — human query authoring

Distribute these files separately:

- `artifacts/development_query_authoring/query_author_a.csv`
- `artifacts/development_query_authoring/query_author_b.csv`

Authors edit only `query` and `notes`, following
`docs/development_query_authoring_protocol_ar.md`. After both are returned:

```powershell
python -m experiments.merge_query_author_packets `
  --master-draft artifacts/development_query_authoring/development_authoring_master.csv `
  --packet-manifest artifacts/development_query_authoring/authoring_manifest.json `
  --packet artifacts/development_query_authoring/query_author_a.csv `
  --packet artifacts/development_query_authoring/query_author_b.csv `
  --output artifacts/development_query_authoring/development_human_queries.csv

python -m experiments.compile_benchmark_queries `
  --draft artifacts/development_query_authoring/development_human_queries.csv `
  --output artifacts/development_human_queries_v1.jsonl
```

The compile step rejects blank, duplicate, invalid-date, and near-title-copy queries.

## Freeze expansions for the approved human queries

Run this only after archiving the approved query CSV and JSONL checksums:

```powershell
$env:LLM_QUERY_EXPANSION_ENABLED='true'
python -m experiments.expand_development_queries `
  --queries artifacts/development_human_queries_v1.jsonl `
  --split artifacts/benchmark_query_split_scope_v1_frozen.json `
  --output artifacts/development_human_query_expansions_v1.jsonl `
  --execute
Remove-Item Env:LLM_QUERY_EXPANSION_ENABLED
```

## Build a method-blind depth-20 union pool

```powershell
python -m experiments.build_candidate_pool `
  --corpus artifacts/paper_recommendation_scope_v2.csv `
  --queries artifacts/development_human_queries_v1.jsonl `
  --specter-cache artifacts/paper_recommendation_scope_v2.specter2.npz `
  --methods hybrid llm_expanded_hybrid `
  --llm-expansions artifacts/development_human_query_expansions_v1.jsonl `
  --depth 20 --candidate-k 100 --rrf-k 60 `
  --assessor assessor_a --assessor assessor_b `
  --output artifacts/development_llm_comparison_pool_v1.jsonl `
  --annotation-dir artifacts/development_llm_comparison_annotations_v1
```

The master pool retains method provenance for audit. Assessor CSV files omit it and
use independent deterministic row orders.

## Gate 2 — two independent relevance assessments

Give each assessor only their own CSV plus
`docs/development_relevance_assessment_protocol_ar.md`. When both are complete:

```powershell
python -m experiments.analyze_judgments `
  --pool artifacts/development_llm_comparison_pool_v1.jsonl `
  --judgments artifacts/development_llm_comparison_annotations_v1/assessor_a.csv `
              artifacts/development_llm_comparison_annotations_v1/assessor_b.csv `
  --report results/development_llm_agreement_v1.json `
  --adjudication artifacts/development_llm_adjudication_v1.csv
```

Resolve only conflicts in the adjudication file, documenting every rationale, then:

```powershell
python -m experiments.finalize_qrels `
  --adjudication artifacts/development_llm_adjudication_v1.csv `
  --agreement-report results/development_llm_agreement_v1.json `
  --output artifacts/development_llm_qrels_v1.tsv
```

Only after this final checksum-locked qrels artifact exists should nDCG, Recall, MRR,
paired significance, or publication-facing effectiveness claims be computed.

## Scope v3.1.1 graph-weight ablation

The graph-weight experiment is registered separately in
`experiments/specs/retrieval_graph_ablation_scope_v3_1_1_v2.json`; it does not
modify the frozen v1 protocol. After Gate 1 and Gate 2 are complete for the
graph union pool, run only the development split:

```powershell
python -m experiments.run_registered_matrix `
  --spec experiments/specs/retrieval_graph_ablation_scope_v3_1_1_v2.json `
  --stage development `
  --queries artifacts/development_human_queries_v1.jsonl `
  --qrels artifacts/development_graph_qrels_v2.tsv `
  --output-dir results/graph_ablation_scope_v3_1_1_v2
```

The runner rejects fewer than 20 queries, a query-ID mismatch, fewer than 20
final judgments for any query, and any changed corpus/graph/cache/split hash.
Weights are 0, 0.1, 0.25, 0.5, and 1.0; all other retrieval parameters are
fixed. Select one weight on development by nDCG@10, with p95 latency and then
the lower weight as the registered tie breakers.
