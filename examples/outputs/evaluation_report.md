# SciGuard evaluation report

> Controlled synthetic benchmark on hand-labelled scenarios. Its value is regression safety, the DataHub ablation, and false-alarm control on negative cases — not a claim of real-world accuracy.

- scenarios: 13 (9 actionable, 4 negative controls)
- change detection accuracy: 100.0% (13/13)
- risk-severity accuracy: 100.0% (13/13)
- false-alarm rate on negatives: 0.0% (0/4)

## Impact analysis (actionable scenarios)
- impacted-entity precision: 100.0%
- impacted-entity recall: 100.0%
- impacted-entity F1: 100.0%
- owner-notification recall: 100.0%
- model-at-risk tag targeting: 100.0% (9/9)

## Ablation: with vs without DataHub lineage
- impacted-entity recall WITH DataHub:    100.0%
- impacted-entity recall WITHOUT DataHub:  0.0%
- Without the lineage graph, downstream models and reports are invisible,
  so every downstream artifact at risk is missed.

## Latency
- mean per-scenario: 55.5 ms

## Per-scenario
| scenario | detect | severity | impact recall | note |
|---|---|---|---|---|
| tg-unit-raw | ok | ok | 100.0% |  |
| mn-unit-raw | ok | ok | 100.0% |  |
| mw-unit-raw | ok | ok | 100.0% |  |
| remove-sampleid-raw | ok | ok | 100.0% |  |
| remove-smiles-raw | ok | ok | 100.0% |  |
| tg-unit-cleaned | ok | ok | 100.0% |  |
| tg-unit-features | ok | ok | 100.0% |  |
| multi-tg-and-mn-raw | ok | ok | 100.0% |  |
| remove-sampleid-cleaned | ok | ok | 100.0% |  |
| neg-pdi-unit-raw | ok | ok | - | negative control |
| neg-remove-protocol-raw | ok | ok | - | negative control |
| neg-remove-measuredon-raw | ok | ok | - | negative control |
| neg-add-notes-raw | ok | ok | - | negative control |
