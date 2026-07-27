from __future__ import annotations

import pytest

from core.impact import FieldImpact
from core.investigation_models import RootCause
from core.repair import ArtifactKind, create_unit_repair_bundle
from core.unified_patch import UnifiedPatchError, apply_unified_patch


def _bundle():
    return create_unit_repair_bundle(
        incident_id="inc-patch-test",
        root_cause=RootCause(
            batch_id="B042",
            instrument_firmware_before="v4.1",
            instrument_firmware_after="v4.2",
            expected_unit="degC",
            observed_units=["degC", "K"],
            normalization_version="tg-normalizer-v1",
            affected_rows=187,
            explanation="Verified mixed-unit root cause.",
        ),
        impact=FieldImpact(
            source_urn="urn:raw",
            source_fields=["tg_value"],
            affected_urns=["urn:raw"],
            affected_names=["raw"],
            unaffected_urns=["urn:safe"],
            unaffected_names=["safe"],
            tainted_field_urns=["urn:field:tg"],
        ),
        evidence_ids=["e-contract", "e-lineage"],
        approver_urn="urn:li:corpuser:research_lead",
    )


def test_flagship_patch_materializes_the_reviewed_normalizer() -> None:
    artifact = next(
        item for item in _bundle().artifacts if item.kind is ArtifactKind.CODE_PATCH
    )
    original = (
        "def normalize_tg(value: float, unit: str) -> float:\n"
        "    # v1 trusted the destination column label and silently copied mixed units.\n"
        "    return float(value)\n"
    )

    applied = apply_unified_patch(original, artifact.content)

    assert applied.path == "pipeline/normalize.py"
    assert "class UnitContractError" in applied.content
    assert 'if normalized == "K":' in applied.content
    assert "273.15" in applied.content


def test_patch_context_drift_and_path_traversal_fail_closed() -> None:
    artifact = next(
        item for item in _bundle().artifacts if item.kind is ArtifactKind.CODE_PATCH
    )
    with pytest.raises(UnifiedPatchError, match="context drift"):
        apply_unified_patch("def normalize_tg():\n    return 0\n", artifact.content)

    malicious = artifact.content.replace(
        "--- a/pipeline/normalize.py",
        "--- a/../../outside.py",
        1,
    ).replace(
        "+++ b/pipeline/normalize.py",
        "+++ b/../../outside.py",
        1,
    )
    with pytest.raises(UnifiedPatchError, match="unsafe"):
        apply_unified_patch("", malicious)
