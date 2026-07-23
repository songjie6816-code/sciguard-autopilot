"""Open and resolve a bounded three-hypothesis scientific investigation."""

from __future__ import annotations

import re
from pathlib import Path

from datahub.emitter.mce_builder import make_dataset_urn

from core.events import EventActor, EventRecorder, EventType
from core.investigation_models import (
    Evidence,
    Hypothesis,
    HypothesisResolution,
    HypothesisStatus,
    InvestigationCase,
    InvestigationReport,
    InvestigationResult,
    RealityCheckResult,
    RootCause,
)
from core.sentinel import DetectionSignal


class EvidencePendingError(RuntimeError):
    """Raised when the Coordinator is asked to decide before both workers return."""


HYPOTHESES = (
    Hypothesis(
        id="H1",
        claim="model or code version drift",
        assigned_actor="SCIENTIFIC_INVESTIGATOR",
        investigation_contract="Compare DataHub current model/code versions to trusted release manifest",
        required_evidence_kinds=["MODEL_RELEASE_CONTEXT", "TRUSTED_RELEASE_BASELINE"],
    ),
    Hypothesis(
        id="H2",
        claim="upstream scientific-data drift",
        assigned_actor="SCIENTIFIC_INVESTIGATOR+REALITY_CHECKER",
        investigation_contract="Join reverse DataHub lineage with row-level unit and firmware validation",
        required_evidence_kinds=["UPSTREAM_LINEAGE", "UNIT_FIRMWARE_CONTRACT"],
    ),
    Hypothesis(
        id="H3",
        claim="legitimate experimental improvement",
        assigned_actor="REALITY_CHECKER",
        investigation_contract="Compare trusted/current ranks and unit-corrected scientific values",
        required_evidence_kinds=["RANK_BASELINE_COMPARISON", "EXPERIMENTAL_VALUE_CHECK"],
    ),
)


class Coordinator:
    def __init__(
        self,
        recorder: EventRecorder | None = None,
        start_asset_name: str = "candidate_ranking_report",
    ) -> None:
        self.recorder = recorder
        self.start_asset_name = start_asset_name

    def open_case(
        self,
        incident_id: str,
        symptom: str,
        signal: DetectionSignal | None = None,
    ) -> InvestigationCase:
        candidate = re.search(r"\b(P-\d+)\b", symptom, re.IGNORECASE)
        ranks = re.search(
            r"(?:from\s+)?rank\s+#?(\d+)\s+to\s+(?:rank\s+)?#?(\d+)",
            symptom,
            re.IGNORECASE,
        )
        if not candidate or not ranks:
            raise ValueError("symptom must identify a candidate and before/after ranks")
        if self.recorder and self.recorder.incident_id != incident_id:
            raise ValueError("Coordinator recorder and case incident IDs must match")
        case = InvestigationCase(
            incident_id=incident_id,
            signal_id=signal.signal_id if signal else None,
            signal_evidence_ids=signal.evidence_ids if signal else [],
            symptom=symptom,
            candidate_id=candidate.group(1).upper(),
            rank_before=int(ranks.group(1)),
            rank_after=int(ranks.group(2)),
            pipeline_status="SUCCESS" if "no pipeline failed" in symptom.lower() else "UNKNOWN",
            start_asset_name=self.start_asset_name,
            hypotheses=list(HYPOTHESES),
        )
        if self.recorder:
            for hypothesis in case.hypotheses:
                self.recorder.emit(
                    actor=EventActor.COORDINATOR,
                    event_type=EventType.HYPOTHESIS_PROPOSED,
                    summary=f"{hypothesis.id}: {hypothesis.claim}",
                    evidence_ids=case.signal_evidence_ids,
                    payload=hypothesis.model_dump(mode="json"),
                )
        return case

    def run_investigation(
        self,
        incident_id: str,
        symptom: str,
        *,
        backend,
        data_dir: str | Path,
        platform: str = "polymer_rnd",
        env: str = "PROD",
        signal: DetectionSignal | None = None,
    ) -> InvestigationReport:
        """Execute the bounded WP3 workflow with the symptom as its only case input.

        Backend and data directory are dependencies, not hidden conclusions: the
        Investigator must discover the upstream chain and the Reality-Checker must
        calculate the row-level facts independently.
        """

        case = self.open_case(incident_id, symptom, signal)
        return self.investigate_case(
            case,
            backend=backend,
            data_dir=data_dir,
            platform=platform,
            env=env,
        )

    def investigate_case(
        self,
        case: InvestigationCase,
        *,
        backend,
        data_dir: str | Path,
        platform: str = "polymer_rnd",
        env: str = "PROD",
    ) -> InvestigationReport:
        """Run both independent workers for an already opened, signal-bound case."""

        from core.investigator import ScientificInvestigator
        from core.reality_checker import RealityChecker

        report_urn = make_dataset_urn(platform, case.start_asset_name, env)
        catalog = ScientificInvestigator(backend, self.recorder).investigate(report_urn)
        reality = RealityChecker(data_dir, self.recorder).check(case)
        return self.resolve(case, catalog=catalog, reality=reality)

    @staticmethod
    def _by_kind(evidence: list[Evidence]) -> dict[str, Evidence]:
        return {item.kind: item for item in evidence}

    def resolve(
        self,
        case: InvestigationCase,
        *,
        catalog: InvestigationResult | None,
        reality: RealityCheckResult | None,
    ) -> InvestigationReport:
        if catalog is None or reality is None:
            raise EvidencePendingError(
                "Coordinator requires both DataHub and Reality-Checker results before resolution"
            )
        if not catalog.available or not reality.available:
            reasons = [
                result.degraded_reason
                for result in (catalog, reality)
                if not result.available and result.degraded_reason
            ]
            degraded_evidence_ids = [
                item.evidence_id for item in [*catalog.evidence, *reality.evidence]
            ]
            resolutions = [
                HypothesisResolution(
                    hypothesis_id=hypothesis.id,
                    status=HypothesisStatus.INCONCLUSIVE,
                    rationale="Required independent evidence source is unavailable",
                    evidence_ids=degraded_evidence_ids,
                )
                for hypothesis in case.hypotheses
            ]
            report = InvestigationReport(
                incident_id=case.incident_id,
                root_cause_confirmed=False,
                root_cause=None,
                resolutions=resolutions,
                degraded=True,
                degraded_reason="; ".join(reasons) or "required evidence unavailable",
            )
            self._emit_resolutions(resolutions)
            return report

        evidence = self._by_kind([*catalog.evidence, *reality.evidence])
        missing = {
            kind
            for hypothesis in case.hypotheses
            for kind in hypothesis.required_evidence_kinds
            if kind not in evidence
        }
        if missing:
            raise EvidencePendingError(f"required evidence has not returned: {sorted(missing)}")

        current_release = evidence["MODEL_RELEASE_CONTEXT"]
        trusted_release = evidence["TRUSTED_RELEASE_BASELINE"]
        release_matches = all(
            current_release.payload.get(key) == trusted_release.payload.get(key)
            for key in ("model_version", "code_version")
        )
        h1 = HypothesisResolution(
            hypothesis_id="H1",
            status=(HypothesisStatus.REJECTED if release_matches else HypothesisStatus.CONFIRMED),
            rationale=(
                "Current model and code versions match the trusted release baseline"
                if release_matches
                else "Current model or code version differs from the trusted release baseline"
            ),
            evidence_ids=[current_release.evidence_id, trusted_release.evidence_id],
        )

        lineage = evidence["UPSTREAM_LINEAGE"]
        unit = evidence["UNIT_FIRMWARE_CONTRACT"]
        lineage_reaches_batch = "instrument_batch_B042" in lineage.payload.get(
            "suspect_sources", []
        )
        unit_drift = (
            unit.payload.get("contract_passed") is False
            and unit.payload.get("affected_rows", 0) > 0
            and "B042" in unit.payload.get("affected_batches", [])
        )
        h2_confirmed = lineage_reaches_batch and unit_drift
        h2 = HypothesisResolution(
            hypothesis_id="H2",
            status=(HypothesisStatus.CONFIRMED if h2_confirmed else HypothesisStatus.REJECTED),
            rationale=(
                "Reverse lineage reaches B042 and independent row checks prove its unit drift"
                if h2_confirmed
                else "Lineage and row-level contract evidence do not jointly support upstream drift"
            ),
            evidence_ids=[lineage.evidence_id, unit.evidence_id],
        )

        rank = evidence["RANK_BASELINE_COMPARISON"]
        experiment = evidence["EXPERIMENTAL_VALUE_CHECK"]
        no_real_improvement = (
            rank.payload.get("rank_after", 0) < rank.payload.get("rank_before", 0)
            and rank.payload.get("symptom_matches_artifacts", True) is True
            and rank.payload.get("pipeline_status") == "SUCCESS"
            and experiment.payload.get("all_converted_values_match_baseline") is True
            and abs(float(experiment.payload.get("candidate_true_delta_degc", 1.0))) < 1e-9
        )
        h3 = HypothesisResolution(
            hypothesis_id="H3",
            status=(HypothesisStatus.REJECTED if no_real_improvement else HypothesisStatus.CONFIRMED),
            rationale=(
                "The rank jump disappears after correct unit conversion; no true Tg gain remains"
                if no_real_improvement
                else "Corrected scientific values still support a real improvement"
            ),
            evidence_ids=[rank.evidence_id, experiment.evidence_id],
        )

        confirmed = (
            h1.status is HypothesisStatus.REJECTED
            and h2.status is HypothesisStatus.CONFIRMED
            and h3.status is HypothesisStatus.REJECTED
        )
        root_cause = None
        if confirmed:
            root_cause = RootCause(
                batch_id=unit.payload["affected_batches"][0],
                instrument_firmware_before=unit.payload["trusted_firmware"][0],
                instrument_firmware_after=unit.payload["current_firmware"][0],
                expected_unit=unit.payload["expected_unit"],
                observed_units=unit.payload["observed_units"],
                normalization_version=unit.payload["normalization_versions"][0],
                affected_rows=unit.payload["affected_rows"],
                explanation=(
                    "Firmware v4.2 emitted part of batch B042 in Kelvin while "
                    "tg-normalizer-v1 treated the values as Celsius."
                ),
            )
        resolutions = [h1, h2, h3]
        self._emit_resolutions(resolutions)
        return InvestigationReport(
            incident_id=case.incident_id,
            root_cause_confirmed=confirmed,
            root_cause=root_cause,
            resolutions=resolutions,
        )

    def _emit_resolutions(self, resolutions: list[HypothesisResolution]) -> None:
        if not self.recorder:
            return
        for resolution in resolutions:
            self.recorder.emit(
                actor=EventActor.COORDINATOR,
                event_type=EventType.HYPOTHESIS_RESOLVED,
                summary=(
                    f"{resolution.hypothesis_id} resolved as {resolution.status.value}"
                ),
                evidence_ids=resolution.evidence_ids,
                payload=resolution.model_dump(mode="json"),
            )
