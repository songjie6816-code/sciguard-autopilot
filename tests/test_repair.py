from core.impact import FieldImpact
from core.investigation_models import RootCause
from core.repair import (
    ApprovalStatus,
    ArtifactKind,
    RepairStatus,
    create_unit_repair_bundle,
)


def _root_cause() -> RootCause:
    return RootCause(
        batch_id="B042",
        instrument_firmware_before="v4.1",
        instrument_firmware_after="v4.2",
        expected_unit="degC",
        observed_units=["degC", "K"],
        normalization_version="tg-normalizer-v1",
        affected_rows=187,
        explanation="Firmware v4.2 emitted Kelvin while v1 copied values as Celsius.",
    )


def _impact() -> FieldImpact:
    return FieldImpact(
        source_urn="urn:raw",
        source_fields=["tg_value"],
        affected_urns=["urn:raw", "urn:tg-model", "urn:rank"],
        affected_names=["raw", "tg-model", "rank"],
        unaffected_urns=["urn:mw-model", "urn:formulation"],
        unaffected_names=["mw-model", "formulation"],
        tainted_field_urns=["urn:field:tg"],
    )


def test_unit_repair_bundle_is_deterministic_reviewable_and_starts_locked() -> None:
    first = create_unit_repair_bundle(
        incident_id="inc-repair",
        root_cause=_root_cause(),
        impact=_impact(),
        evidence_ids=["e-lineage", "e-contract"],
        approver_urn="urn:li:corpuser:research_lead",
    )
    second = create_unit_repair_bundle(
        incident_id="inc-repair",
        root_cause=_root_cause(),
        impact=_impact(),
        evidence_ids=["e-lineage", "e-contract"],
        approver_urn="urn:li:corpuser:research_lead",
    )

    assert first == second
    assert first.status is RepairStatus.PROPOSED
    assert first.external_action_receipt is None
    assert first.approval.status is ApprovalStatus.REQUIRED
    assert first.approval.approver_urn == "urn:li:corpuser:research_lead"
    assert len(first.artifacts) == 5
    assert len(first.verification_checks) == 3
    assert set(first.affected_urns).isdisjoint(first.preserved_urns)


def test_patch_is_fail_closed_and_every_claim_carries_evidence() -> None:
    bundle = create_unit_repair_bundle(
        incident_id="inc-proof",
        root_cause=_root_cause(),
        impact=_impact(),
        evidence_ids=["e-contract"],
        approver_urn="urn:li:corpuser:research_lead",
    )
    patch = next(
        artifact for artifact in bundle.artifacts if artifact.kind is ArtifactKind.CODE_PATCH
    )

    assert 'normalized == "K"' in patch.content
    assert "- 273.15" in patch.content
    assert "UnitContractError" in patch.content
    assert all(artifact.evidence_ids == ["e-contract"] for artifact in bundle.artifacts)
    assert all(check.evidence_ids == ["e-contract"] for check in bundle.verification_checks)


def test_bundle_explicitly_proves_the_safe_branch() -> None:
    bundle = create_unit_repair_bundle(
        incident_id="inc-safe-proof",
        root_cause=_root_cause(),
        impact=_impact(),
        evidence_ids=["e-impact"],
        approver_urn="urn:li:corpuser:research_lead",
    )

    safe_artifact = next(
        artifact
        for artifact in bundle.artifacts
        if artifact.kind is ArtifactKind.SAFE_BRANCH_TEST
    )
    assert "b042_decision_fixture.csv" in safe_artifact.content
    assert "rank_candidates(candidates, normalizer=normalize_tg)" in safe_artifact.content
    assert "publish_molecular_weight_artifact" in safe_artifact.content
    assert "destination.read_bytes() == before" in safe_artifact.content
    assert "TRUSTED_MW_SHA256" in safe_artifact.content
    assert "urn:formulation" in bundle.preserved_urns


def test_unsupported_root_cause_cannot_generate_a_plausible_patch() -> None:
    root = _root_cause().model_copy(update={"observed_units": ["degC", "degF"]})
    try:
        create_unit_repair_bundle(
            incident_id="inc-unsupported",
            root_cause=root,
            impact=_impact(),
            evidence_ids=["e-contract"],
            approver_urn="urn:li:corpuser:research_lead",
        )
    except ValueError as exc:
        assert "only supports" in str(exc)
    else:
        raise AssertionError("unsupported unit evidence must fail closed")
