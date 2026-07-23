# SciGuard evaluation report

> Controlled synthetic benchmark on hand-labelled scenarios. Both ablation arms are executed against DataHub (no number is hardcoded). Purpose: regression safety, false-alarm control, and a measured DataHub ablation.

- scenarios: 13 (9 actionable, 4 negative controls)
- change detection accuracy: 100.0% (13/13)
- risk-severity accuracy: 100.0% (13/13)
- false-alarm rate on negatives: 0.0% (0/4)
- owner-notification precision/recall: 100.0% / 100.0%
- model control targeting: 100.0% (9/9)

## Impact analysis over 3 distinct lineage cones
| approach | precision | recall | F1 | exact cone |
|---|---|---|---|---|
| WITH DataHub lineage | 100.0% | 100.0% | 100.0% | 3/3 |
| SEARCH-ONLY DataHub (without lineage) | 60.0% | 83.3% | 69.8% | 0/3 |

The no-lineage search baseline cannot tell dependency direction, so it
flags upstream/sibling datasets as affected (false positives: ['candidate_report', 'durability_model', 'instrument_batch_B042', 'molecular_weight_feature_table', 'polymer_feature_table', 'raw_polymer_experiments']).
Only lineage recovers the exact downstream cone with correct direction.

## Per-scenario
| scenario | detect | severity | note |
|---|---|---|---|
| tg-unit-raw | ok | ok |  |
| mn-unit-raw | ok | ok |  |
| mw-unit-raw | ok | ok |  |
| remove-sampleid-raw | ok | ok |  |
| remove-smiles-raw | ok | ok |  |
| tg-unit-cleaned | ok | ok |  |
| tg-unit-features | ok | ok |  |
| multi-tg-and-mn-raw | ok | ok |  |
| remove-sampleid-cleaned | ok | ok |  |
| neg-pdi-unit-raw | ok | ok | negative control |
| neg-remove-protocol-raw | ok | ok | negative control |
| neg-remove-measuredon-raw | ok | ok | negative control |
| neg-add-notes-raw | ok | ok | negative control |
