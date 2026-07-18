# SciGuard incident: Risk on 'raw_polymer_experiments': CRITICAL

- **Change site:** `raw_polymer_experiments`
- **Overall severity:** CRITICAL
- **Owners to notify:** data_engineer, ml_engineer, research_lead

## Detected changes and rules
- unit of 'tg_value' changed degC -> K; matched rule 'tg-unit-change' (polymer profile) -> critical
  - accepted units: degC, K

## Affected downstream (via DataHub lineage)
- hop 1: `cleaned_polymer_dataset` [dataset] — owner: data_engineer
- hop 2: `polymer_feature_table` [dataset] — owner: ml_engineer
- hop 3: `tg_prediction_model` [model] — owner: ml_engineer
- hop 4: `candidate_report` [report] — owner: research_lead

## Recommended remediation
1. verify source unit and conversion provenance
2. update preprocessing conversion
3. revalidate affected models and reports
4. Revalidate downstream artifacts before use: tg_prediction_model, candidate_report
