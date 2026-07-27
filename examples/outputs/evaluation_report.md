# SciGuard evaluation report

> Controlled synthetic benchmark on hand-labelled scenarios. Lineage and search-only arms execute against DataHub; the no-DataHub arm receives no backend and explicitly abstains. No number is hardcoded.

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
| SEARCH-ONLY DataHub (without lineage) | 60.0% | 100.0% | 75.0% | 0/3 |
| NO DataHub (zero-context abstention) | N/A (0 predictions) | 0.0% | 0.0% | 0/3 |

The no-lineage search baseline cannot tell dependency direction, so it
flags upstream/sibling datasets as affected (false positives: ['candidate_report', 'cleaned_polymer_dataset', 'instrument_batch_B042', 'molecular_weight_feature_table', 'polymer_feature_table', 'raw_polymer_experiments']).
Only lineage recovers the exact downstream cone with correct direction.
With DataHub access prohibited, SciGuard has no defensible dependency or owner context and abstains rather than inventing an impact cone.

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
