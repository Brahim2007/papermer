# Retrieval metric validation

## Status

PaperMetrix metric definition `trec-eval-compatible-v2` is checked against
`ir-measures==0.4.3`, which uses the `pytrec_eval` provider for AP, reciprocal
rank, precision, recall, and nDCG.

The reference tests cover binary and graded relevance, unjudged documents,
rank cutoffs, missing positives, and aggregation across queries. The acceptance
tolerance is an absolute difference of `1e-9`.

## Corrected discrepancy

The earlier local nDCG implementation used the exponential gain
`2^relevance - 1`. The TREC-compatible reference used for this project applies
the relevance grade directly as gain. This produced materially different nDCG
values for graded qrels. The implementation now follows the reference, and MAP
has been added as the mean of per-query Average Precision.

## Interpretation and artifact boundary

- Unjudged documents are treated as nonrelevant, matching the default TREC
  convention used in the tests.
- Relevance grades greater than zero count as relevant for AP, RR, precision,
  and recall.
- Graded values are retained for nDCG.
- Metrics in artifacts produced before this correction must not be mixed with
  `trec-eval-compatible-v2` results. Re-run those evaluations before using their
  nDCG values in a paper.

The executable reference contract is
`retrieval/tests/test_metrics_reference.py`.
