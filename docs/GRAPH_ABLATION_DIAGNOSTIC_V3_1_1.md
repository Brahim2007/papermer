# Graph ablation diagnostic — Scope v3.1.1

## Status and purpose

This is a temporal engineering diagnostic, not publication evidence. Each
query is the title of its single grade-2 relevant paper, so lexical and dense
retrieval receive deliberate title leakage. The diagnostic checks artifact
compatibility, temporal filtering, graph integration, and operational cost.
It must not replace the frozen human-query benchmark with two independent
assessors.

The original fixture contained 20 queries. `related-0027` was excluded before
the run because its judged S3PaR document is absent from Scope v3.1.1. The
remaining 19 judged document IDs exist in the corpus and are not later than
their query dates.

## Frozen inputs

| Artifact | SHA-256 |
|---|---|
| corpus.csv | `2d80460bd329c2c5401478320f3dbd1e6d35806631ce4df1e5d96fa280af765f` |
| citations.tsv | `99936c8426c7b43b0af718966957dfb37b4002df0b1379db0ffcb82f63046b6c` |
| specter2.npz | `66cf1b364ee7af2d2af8ad715997d28d7a2f42aa32d3787ca5307b8313a33447` |
| diagnostic queries | `4fa426538a17b94b732b9a3eba9146a8b8cfd72aa6c3d04ef1020fff186c168e` |
| diagnostic qrels | `0d8746b52d6ee000dbe6ff4276f1d3b9b4d5e39a7461b7d7a0c75c6294d82db2` |

Both conditions used BM25 k1=1.2/b=0.75, SPECTER2, RRF k=60,
candidate-k=100, top-k=100, and publication-date ≤ query-date. Graph-on added
direct citation, bibliographic coupling, and co-citation at weight 1, then
fused the graph channel at weight 1. No reranker or LLM was used.

## Raw comparison

| Metric | Graph off | Graph on | Absolute delta | Relative delta |
|---|---:|---:|---:|---:|
| MAP | 1.000 | 0.664 | -0.336 | -33.55% |
| MRR | 1.000 | 0.664 | -0.336 | -33.55% |
| Recall@5 | 1.000 | 0.947 | -0.053 | -5.26% |
| nDCG@5 | 1.000 | 0.732 | -0.268 | -26.80% |
| Recall@10 | 1.000 | 1.000 | 0.000 | 0.00% |
| nDCG@10 | 1.000 | 0.749 | -0.251 | -25.14% |
| Mean query latency | 1,226.91 ms | 2,302.99 ms | +1,076.08 ms | +87.71% |
| p95 query latency | 2,553.39 ms | 4,431.70 ms | +1,878.31 ms | +73.56% |
| Index-build total | 98.18 s | 186.90 s | +88.72 s | +90.36% |
| End-to-end elapsed | 213.31 s | 342.32 s | +129.01 s | +60.48% |

Result hashes:

- graph-off: `55809f27bc1724462aa6020b80233629cb9d07b13478ef14c38eb3bd93e3e873`
- graph-on: `42d61f1b0f023b959cd8670e9f50147492f15597276dcb16262d29fc932afb4c`

## Paired findings

1. Graph-on improved zero queries, tied eight, and degraded eleven. The mean
   paired MRR delta was -0.336; a fixed-seed 10,000-sample query bootstrap
   interval was [-0.474, -0.197]. This interval is descriptive only because
   the title-leakage fixture is not a representative query sample.
2. All relevant papers remained within the top 10, but graph fusion displaced
   eleven exact-title matches from rank 1. Equal graph weight therefore
   overpowers a highly confident text match in this condition.
3. Graph-on also reduced topic diversity, citation novelty, and long-tail share
   at every reported cutoff. Coverage@100 rose only 0.00035 absolute.
4. Query latency rose 87.71% and temporal index construction rose 90.36%.
   Graph structures should be prebuilt or cached per deployment snapshot before
   considering an online rollout.

## Implication and next experiment

Do not enable graph weight 1 as the platform default. On the completed human
development queries, run a preregistered weight ablation such as
0, 0.1, 0.25, 0.5, and 1.0 while keeping corpus, cache, candidates, and qrels
fixed. Select at most one weight on development, freeze it, then evaluate once
on test. The publication claim must be based on pooled judgments from two
independent assessors, not this diagnostic.
