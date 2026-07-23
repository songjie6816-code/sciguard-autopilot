# Deterministic synthetic polymer incident

This directory contains only generated, non-confidential records. No laboratory,
collaborator, patient, or proprietary data is used.

Run from the repository root:

```bash
PYTHONPATH=. python data/synthetic_polymer/generate.py
PYTHONPATH=. python data/synthetic_polymer/ingest_to_datahub.py
```

The fixed seed produces 420 candidates. Batch `B042` contains 240 rows; firmware `v4.2`
emits exactly 187 of their Tg measurements in Kelvin. The still-deployed
`tg-normalizer-v1` incorrectly copies every numeric value into a `tg_degC` column. The
construction guarantees the judge-facing symptom:

```text
P-204 trusted rank:  #18
P-204 current rank:   #1
pipeline status: SUCCESS
```

## Generated files

| file | purpose |
|---|---|
| `trusted_polymer_baseline.csv` | clean all-Celsius reference |
| `raw_polymer_experiments.csv` | current batches with instrument and unit provenance |
| `cleaned_polymer_dataset.csv` | buggy normalization output |
| `tg_feature_table.csv` | contaminated Tg branch |
| `molecular_weight_feature_table.csv` | preserved branch with no Tg column |
| `candidate_ranking_before.csv` | trusted ranking |
| `candidate_ranking_after.csv` | corrupted but successfully produced ranking |
| `trusted_release_manifest.json` | trusted model/code versions and scientific contract |
| `polymer_feature_table.csv` | compatibility artifact for the original regression suite |

`build(output_dir)` is deterministic and is tested by hashing two independently generated
directories. Tests also assert the 187 affected rows and the exact P-204 rank shift.

## DataHub graph

```text
instrument_batch_B042 -> raw_polymer_experiments -> cleaned_polymer_dataset
                                                   |-> tg_feature_table
                                                   |   |-> tg_prediction_model
                                                   |   |   `-> candidate_ranking_report
                                                   |   `-> exploratory_dashboard
                                                   `-> molecular_weight_feature_table
                                                       `-> durability_model
                                                           `-> formulation_report
```

Every asset receives schema, owner, criticality, synthetic/role tags, custom governance
properties, dataset lineage, and field lineage. Field lineage is the evidence that
`tg_degC` enters only the Tg branch.

The installed DataHub SDK contains native ML model classes, but the competition version of
the MCP Server and SciGuard's SDK parity contract expose schema, units, and lineage most
reliably through dataset URNs. The two models therefore use an explicit
`dataset_entity_fallback` with queryable `entity_role`, `model_version`, and
`ml_metadata_mode` properties. This is a disclosed compatibility decision, not a claim that
the assets are native DataHub MLModel entities.
