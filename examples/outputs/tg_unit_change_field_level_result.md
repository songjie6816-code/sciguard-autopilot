# SciGuard final field-level result: selective control

> **Final field-level result.** This report is derived from the existing deterministic
> synthetic flagship replay; it does not rewrite or regenerate the immutable event stream.
> It complements `tg_unit_change_report.md`, which preserves the earlier conservative
> dataset-level review scope.

## What field lineage proved

DataHub field lineage followed `raw_polymer_experiments.tg_value` only through consumers
that receive the contaminated Tg value. Replay event 13 (`IMPACT_MAPPED`) records evidence
ID `field-impact:bb47513135e033a4` and an exact cone of six affected assets and three
preserved assets.

### Affected Tg branch

| asset | deterministic decision | reason |
|---|---|---|
| `instrument_batch_B042` | HALT | affected source batch |
| `raw_polymer_experiments` | WARN | affected dataset |
| `cleaned_polymer_dataset` | WARN | affected dataset |
| `tg_feature_table` | WARN | affected feature table |
| `exploratory_dashboard` | WARN | affected dashboard |
| `tg_prediction_model` | HALT | affected model |
| `candidate_ranking_report` | HALT | affected decision report |

### Preserved molecular-weight branch

| asset | deterministic decision | reason |
|---|---|---|
| `molecular_weight_feature_table` | ALLOW | no contaminated Tg field reaches this branch |
| `durability_model` | ALLOW | consumes the preserved molecular-weight branch |
| `formulation_report` | ALLOW | downstream decision output remains outside the Tg cone |

## Why this reduces over-isolation

Dataset-level lineage correctly opened a conservative review of every downstream asset,
including the molecular-weight path. Field-level mappings then proved that `tg_value`
propagates only into the Tg path. The deterministic controller therefore halted the source
batch, Tg model, and ranking report while allowing the molecular-weight feature table,
durability model, and formulation report to continue.

The LLM did not authorize any decision. Events 14–23 contain the deterministic
`WARN`/`HALT`/`ALLOW` policy results that consume the field-level affected flag.

## Provenance

- source: `examples/replays/inc-wp6-flagship/events.jsonl`
- mode: `RECORDED_REPLAY`
- backend declared by the source manifest: `DATAHUB_SDK`
- data: deterministic and synthetic
- integrity boundary: the bundled SHA-256 is an internal consistency check, not a digital
  signature or independent source authentication
