# Publication benchmark protocol

## Scope

This protocol creates temporal relevance judgments for two tasks:

- `ad_hoc`: a natural-language information need with no known target paper;
- `related_paper`: find useful papers given one or more seed papers.

Diagnostic queries and title-derived judgments must never be mixed with the
publication qrels.

## Query construction

1. Select seed tasks deterministically across publication-year and citation
   strata.
2. A query author writes the information need without copying the seed title.
3. The query date represents when the information need occurred, not when the
   benchmark was assembled.
4. A related-paper seed must have been published on or before the query date.
5. Store a pseudonymous `author_id`; do not store personal data in public
   artifacts.
6. Freeze development/test query IDs before relevance assessment. Development
   queries may be used for graph weights and candidate-depth selection; test
   queries remain untouched until every configuration and primary metric is
   frozen.

The compiler rejects empty queries, duplicate IDs, invalid task types, missing
related-paper seeds, ad-hoc queries containing seeds, and queries with excessive
token overlap with a seed title.

## Pooling and blinding

The publication pool is the union of the top 20 from every system included in
the final comparison: BM25, SPECTER2, Hybrid-RRF, citation graph,
Hybrid-RRF+graph, and the corresponding cross-encoder reranked runs. Every
system sees exactly the papers published on or before the query date. Seed
papers are excluded from their own result lists. Pool contributions and
cross-encoder candidate depth are frozen in the manifest.

The master pool retains method ranks and scores for audit. Assessor CSV files
hide all retrieval evidence. Candidate order is deterministic but differs by
assessor to reduce ordering effects.

## Relevance scale

- `0`: not useful for satisfying the stated information need;
- `1`: partially useful, background-only, or addresses a substantial subset;
- `2`: directly useful and substantially satisfies the information need.

Confidence:

- `1`: low;
- `2`: moderate;
- `3`: high.

Judge from the supplied title and abstract. Record a short rationale for low
confidence or ambiguous cases. Do not infer relevance from system order.

## Agreement and adjudication

Each pooled item must be independently judged by at least two assessors.
The analysis reports exact agreement, pairwise Cohen's kappa, quadratic
weighted kappa, and interval Krippendorff's alpha. Files with missing or extra
items are rejected.

Unanimous labels are copied into the adjudication sheet. Every conflict
requires a final label and an adjudication rationale. Final qrels are frozen
with SHA-256 provenance.

## Evaluation

nDCG uses graded gains `2^relevance - 1`. Precision, Recall, and MRR treat
grades 1 and 2 as relevant. Runs can only be summarized together when corpus,
queries, qrels, temporal boundaries, protocol, and query count match.

Beyond-accuracy reporting uses the same temporally eligible catalog:

- topic diversity: mean pairwise Jaccard distance over non-empty topic sets;
- citation novelty: mean self-information under add-one-smoothed citation
  popularity in the eligible catalog;
- long-tail share: fraction at or below the eligible-catalog median citations;
- mean age: days from publication to query date;
- catalog coverage: unique recommended eligible documents divided by the
  catalog eligible for at least one evaluated query.

Unknown-topic pairs are omitted from topic diversity. These metrics are
descriptive secondary outcomes and never replace the pre-registered primary
relevance metric.

## Minimum publication checks

- query authors are independent from final assessors where feasible;
- at least two assessors per pooled item;
- report pool depth and unique candidate count;
- report agreement and adjudication policy;
- report unjudged-document handling;
- paired uncertainty estimates across queries;
- separate development queries from the untouched final test queries.
- a priori primary metric and correction policy for multiple confirmatory
  comparisons.
