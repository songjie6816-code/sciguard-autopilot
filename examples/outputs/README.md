# Expected outputs

Curated impact reports and metadata write-back examples live here.

- `tg_unit_change_report.md` preserves the conservative initial dataset-level review scope.
- `tg_unit_change_field_level_result.md` records the final field-level affected and
  preserved cones from the immutable flagship replay.
- `evaluation_report.md` is the deterministic curated golden. Runtime timing is excluded;
  `evaluation/harness.py` writes non-deterministic performance samples only to ignored
  `evaluation/outputs/`.
