# Online/offline retrieval evaluation

PaperMetrix records one `RetrievalEvent` for each accepted live-search request.
The event contains end-to-end latency, component latencies, result IDs, and the
component rank of each returned document. Query text is **not** stored by
default. A keyed HMAC digest supports repeated-query analysis without making
short or predictable queries recoverable through a plain hash dictionary.

The staff-only dashboard is available at `/evaluation/`; its JSON export is
`/evaluation/export.json`. The online summary is intentionally bounded to the
latest 5,000 events so the operational view stays inexpensive. Publication
analysis should query/export the underlying table with a declared date window.

Import existing benchmark outputs with:

```shell
python manage.py import_offline_evaluations results/scope_v1_registered_smoke \
  --dataset scope-v1 --split development
```

Use `--frozen` only for an artifact whose inputs, split, configuration, and
checksum have been frozen. The importer accepts only result JSON objects with
an `aggregate` map and preserves their artifact SHA-256.

## LLM query-expansion experiment

Expansion is a separate intent-to-treat arm, disabled by default. When enabled,
a keyed deterministic bucket assigns `LLM_QUERY_EXPANSION_TRAFFIC_PERCENT` of
queries to the arm. The original and expanded query rankings are fused as the
named `baseline` and `llm_expansion` RRF channels. Provider errors fall back to
the original ranking but remain attributed to the selected arm as
`provider_failed`; this avoids survivorship bias.

Enabling the arm authorizes selected raw queries to leave PaperMetrix for the
configured OpenAI-compatible endpoint. Complete an ethics/privacy review first.
Keep `RETRIEVAL_TELEMETRY_STORE_QUERY_TEXT=false` unless participants explicitly
consent to raw-query retention.

Required runtime variables:

```dotenv
LLM_QUERY_EXPANSION_ENABLED=true
LLM_QUERY_EXPANSION_TRAFFIC_PERCENT=10
LLM_QUERY_EXPANSION_ENDPOINT=https://provider.example/v1/chat/completions
LLM_QUERY_EXPANSION_API_KEY=...
LLM_QUERY_EXPANSION_MODEL=...
```

Staff can force a diagnostic request with `expansion=on`; public callers may
use only `auto` or `off`. `off` provides a clean baseline request regardless of
traffic allocation.

Telemetry retention is explicit and dry-run by default:

```shell
python manage.py prune_retrieval_events --days 180
python manage.py prune_retrieval_events --days 180 --confirm
```

## Interaction outcomes

Every rendered top-10 result is recorded as one idempotent `impression` tied to
the retrieval `request_id`. Title/detail navigation records one unique `click`;
a successful library write records `save`; signed-in users can submit a
positive or negative `relevance` judgment. The server derives the document rank
and experiment arm from the original retrieval event, so clients cannot claim a
different rank, paper, or treatment. Events for a paper that was not exposed by
that request are rejected.

The dashboard reports CTR, save rate, positive-judgment rate, and successful
search rate separately by intent-to-treat arm. Staff traffic is excluded from
these online summaries. Missing explicit judgments are never interpreted as
negative relevance.

## Frozen A/B protocol

The confirmatory specification is
`experiments/specs/llm_query_expansion_ab_v1.json`. It fixes a 50/50 assignment,
top-10 display depth, `successful_search_at_10` as the primary outcome, 1,700
eligible requests per arm, secondary outcomes, exclusions, latency/provider
guardrails, and the analysis rule. It was frozen while expansion traffic was
zero with SHA-256:

```text
0e716aa83cad7cc9c8af140e4c0672101ad1ba32fcb7dce5cab0ae805d308ae3
```

Every new retrieval trace stores this protocol checksum, a keyed anonymous
actor digest, and `APP_VERSION`. Re-freezing the same version with different
content is rejected. Verify the frozen artifact with:

```shell
python manage.py freeze_ab_protocol experiments/specs/llm_query_expansion_ab_v1.json
```

After data collection, produce an aggregate-only, preregistration-aligned
analysis artifact with:

```shell
python manage.py export_ab_analysis results/llm_expansion_ab_v1.json \
  --protocol-version 1
```

Before enabling traffic, pin the provider/model revision and deployment/corpus
checksums, complete the ethics/consent decision, set a real `APP_VERSION`, and
only then change `LLM_QUERY_EXPANSION_TRAFFIC_PERCENT` from zero to 50.
