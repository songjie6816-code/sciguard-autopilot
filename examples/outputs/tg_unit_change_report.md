# SciGuard incident: Risk on 'raw_polymer_experiments': CRITICAL

> **Conservative initial dataset-level scope.** This report records the broad downstream
> review cone produced before field-level lineage refinement. It is intentionally retained
> as historical evidence of the safe first response; it is not the final selective-control
> result. See `tg_unit_change_field_level_result.md` for the affected Tg branch and
> preserved molecular-weight branch.

- **Change site:** `raw_polymer_experiments`
- **Overall severity:** CRITICAL
- **Owners to notify:** data_engineer, ml_engineer, research_analyst, research_lead

## Detected changes and rules
- unit of 'tg_value' changed mixed:degC|K -> K; matched rule 'tg-unit-change' (polymer profile) -> critical
  - accepted units: degC, K

## Conservative initial dataset-level scope (via DataHub lineage)
- hop 1: `cleaned_polymer_dataset` [dataset] — owner: data_engineer
- hop 2: `molecular_weight_feature_table` [dataset] — owner: ml_engineer
- hop 2: `tg_feature_table` [dataset] — owner: ml_engineer
- hop 3: `durability_model` [model] — owner: ml_engineer
- hop 3: `exploratory_dashboard` [dataset] — owner: research_analyst
- hop 3: `tg_prediction_model` [model] — owner: ml_engineer
- hop 4: `candidate_ranking_report` [report] — owner: research_lead
- hop 4: `formulation_report` [report] — owner: research_lead

## Recommended remediation
1. verify source unit and conversion provenance
2. update preprocessing conversion
3. revalidate affected models and reports
4. Revalidate downstream artifacts before use: durability_model, tg_prediction_model, candidate_ranking_report, formulation_report
