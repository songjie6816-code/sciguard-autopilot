"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  EvidenceRecord,
  EventFrame,
  JsonValue,
  RunManifest,
  RunMode,
  SciGuardEvent,
} from "./types";
import {
  DATAHUB_CAPABILITY_BOUNDARY,
  DATAHUB_DECISION_EXPLANATION,
  JUDGE_STAGES,
  WHY_DATAHUB_RESULTS,
  stageIndexForEvent,
  stageIndexFromEvents,
} from "./judge-experience.mjs";

const CONFIGURED_API_BASE = process.env.NEXT_PUBLIC_SCIGUARD_API_URL ?? "";
const STATIC_JUDGE_BUILD =
  process.env.NEXT_PUBLIC_SCIGUARD_JUDGE_BUILD === "true";
const REPLAY_ID = "inc-sciguard-b042-unit-contract";
const REPLAY_DURATION_MS = 15_000;
const REPLAY_EVENT_DISCLOSURE =
  "55 immutable events: one live DataHub incident, one exact repair revision, and two fresh recovery verifications.";
const LOCAL_API_BASE = STATIC_JUDGE_BUILD ? "" : "http://127.0.0.1:8000";
const LOCAL_DATAHUB_BASE = STATIC_JUDGE_BUILD ? "" : "http://localhost:9002";
type ExperienceView = "BRIEF" | "OPERATE" | "AUDIT";

const RECOVERY_CHECKS = [
  "verified_k_to_degc_conversion",
  "unit_contract_assertion",
  "batch_consistency_assertion",
  "tg_model_revalidation",
  "candidate_ranking_stability",
];

const evaluationEvidence: EvidenceRecord = {
  evidence_id: "evaluation:harness-2026-07-21",
  source: "CONTROLLED_EVALUATION_ARTIFACT",
  kind: "GATED_EVALUATION",
  summary: "13 labelled scenarios; lineage and search-only arms executed against DataHub",
  payload: {
    scenarios: 13,
    full_datahub_precision: 100,
    full_datahub_recall: 100,
    full_datahub_exact_cones: "3/3",
    search_only_precision: 60,
    search_only_recall: 100,
    search_only_f1: 75,
    search_only_exact_cones: "0/3",
    no_datahub_predictions: 0,
    no_datahub_recall: 0,
    no_datahub_exact_cones: "0/3",
    no_datahub_call_count: 0,
    false_alarm_rate: 0,
  },
};

const dataHubCapabilityEvidence: EvidenceRecord = {
  evidence_id: "datahub-capability:mcp-context-sdk-field-lineage",
  source: "EXECUTABLE_INTEGRATION_PROOF",
  kind: "DATAHUB_REQUIRED_COMPONENT",
  summary: "DataHub MCP Server is a real context backend with an explicit SDK capability boundary",
  payload: {
    required_component: "DataHub MCP Server",
    mcp_decision_inputs: "schema, units, directed lineage, ownership, governance context",
    sdk_fallbacks: "fine-grained lineage and metadata write-back",
    verification_test: "tests/test_mcp_client.py",
    replay_disclosure: "This immutable replay was captured with DATAHUB_SDK",
  },
};

const DATAHUB_LIVE_RECEIPT_EVIDENCE_ID =
  "datahub-live-receipt:inc-sciguard-b042-unit-contract";
const GITHUB_LIVE_EVIDENCE_ID =
  "github-live-evidence:inc-sciguard-b042-unit-contract";

const actorLabels: Record<string, string> = {
  SYSTEM: "System",
  SENTINEL: "Sentinel",
  COORDINATOR: "Coordinator",
  SCIENTIFIC_INVESTIGATOR: "Scientific Investigator",
  REALITY_CHECKER: "Reality Checker",
  POLICY_GUARDIAN: "Policy Guardian",
  ENFORCER: "Enforcer",
  REMEDIATION_AGENT: "Remediation Agent",
  VERIFICATION_ENGINE: "Verification Engine",
  HUMAN_APPROVER: "Human Approver",
  RECOVERY_CONTROLLER: "Recovery Controller",
};

const actorGlyphs: Record<string, string> = {
  SYSTEM: "◎",
  SENTINEL: "⌁",
  COORDINATOR: "◇",
  SCIENTIFIC_INVESTIGATOR: "⌁",
  REALITY_CHECKER: "◉",
  POLICY_GUARDIAN: "⬡",
  ENFORCER: "■",
  REMEDIATION_AGENT: "⌘",
  VERIFICATION_ENGINE: "✓",
  HUMAN_APPROVER: "◆",
  RECOVERY_CONTROLLER: "↻",
};

function objectValue(value: JsonValue | undefined): Record<string, JsonValue> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value
    : {};
}

function stringValue(value: JsonValue | undefined, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function numberValue(value: JsonValue | undefined, fallback = 0): number {
  return typeof value === "number" ? value : fallback;
}

function booleanValue(value: JsonValue | undefined): boolean {
  return value === true;
}

function stringArray(value: JsonValue | undefined): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function formatName(value: string): string {
  return value.replaceAll("_", " ");
}

function shortEvidence(value: string): string {
  const [kind, hash] = value.split(":");
  return hash ? `${kind}:${hash.slice(0, 7)}` : value;
}

function assetReceiptId(name: string): string {
  return `datahub-asset-receipt:${name}`;
}

function eventSpanMs(events: SciGuardEvent[]): number {
  if (events.length < 2) return 0;
  const start = Date.parse(events[0].timestamp);
  const end = Date.parse(events.at(-1)?.timestamp ?? events[0].timestamp);
  return Math.max(0, end - start);
}

function formatSeconds(milliseconds: number): string {
  return `${(milliseconds / 1000).toFixed(1)}s`;
}

function stateFromEvents(events: SciGuardEvent[], fallback: string): string {
  let state = events.some((event) => event.event_type === "SIGNAL_DETECTED")
    ? "DETECTED"
    : fallback;
  for (const event of events) {
    const next = stringValue(event.payload.to_state);
    const recovery = stringValue(event.payload.incident_state);
    if (next) state = next;
    if (recovery) state = recovery;
  }
  return state;
}

async function sha256Hex(value: string): Promise<string> {
  if (!globalThis.crypto?.subtle) {
    throw new Error("This browser cannot verify SHA-256 replay integrity");
  }
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value),
  );
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

async function verifyReplayBundle(
  manifest: RunManifest,
  rawEvents: string,
): Promise<SciGuardEvent[]> {
  const replayEvents = rawEvents
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line) as SciGuardEvent);
  const digest = await sha256Hex(rawEvents);
  const sequencesAreContiguous = replayEvents.every(
    (event, index) => event.sequence === index,
  );
  const eventIds = new Set(replayEvents.map((event) => event.event_id));
  const oneIncident = replayEvents.every(
    (event) => event.incident_id === manifest.incident_id,
  );
  if (
    digest !== manifest.events_sha256 ||
    replayEvents.length !== manifest.event_count ||
    !sequencesAreContiguous ||
    eventIds.size !== replayEvents.length ||
    !oneIncident
  ) {
    throw new Error("Replay integrity verification failed; nothing was rendered");
  }
  return replayEvents;
}

async function verifyRepairCapture(
  replayManifest: RunManifest,
  rawRepairManifest: string,
  rawRepairBundle: string,
  rawDataHubReceipt: string,
  rawEvaluationReport: string,
  rawGitHubEvidence: string,
): Promise<{
  bundle: Record<string, JsonValue>;
  dataHubReceipt: Record<string, JsonValue>;
}> {
  const capture = JSON.parse(rawRepairManifest) as Record<string, JsonValue>;
  const bundleDigest = await sha256Hex(rawRepairBundle);
  const dataHubReceiptDigest = await sha256Hex(rawDataHubReceipt);
  const evaluationReportDigest = await sha256Hex(rawEvaluationReport);
  const githubEvidenceDigest = await sha256Hex(rawGitHubEvidence);
  if (
    stringValue(capture.capture_type) !== "RECORDED_DATAHUB_END_TO_END" ||
    stringValue(capture.source_events_sha256) !== replayManifest.events_sha256 ||
    stringValue(capture.repair_bundle_sha256) !== bundleDigest ||
    stringValue(capture.datahub_native_receipt_sha256) !== dataHubReceiptDigest ||
    stringValue(capture.evaluation_report_sha256) !== evaluationReportDigest
  ) {
    throw new Error("Linked repair capture integrity verification failed");
  }
  const bundle = JSON.parse(rawRepairBundle) as Record<string, JsonValue>;
  const dataHubReceipt = JSON.parse(rawDataHubReceipt) as Record<string, JsonValue>;
  const change = objectValue(bundle.external_action_receipt);
  const verification = objectValue(bundle.verification_receipt);
  const approval = objectValue(bundle.approval_receipt);
  const application = objectValue(bundle.application_receipt);
  const boundaries = objectValue(bundle.linked_capture);
  const captureBoundaries = objectValue(capture.boundaries);
  const repairLifecycle = objectValue(dataHubReceipt.repair_lifecycle);
  const incidentLifecycle = objectValue(dataHubReceipt.incident_lifecycle);
  const resolvedIncident = objectValue(incidentLifecycle.resolved);
  const decisionLogLifecycle = objectValue(dataHubReceipt.decision_log_lifecycle);
  const finalDecisionLog = objectValue(decisionLogLifecycle.final);
  const receiptModels = Array.isArray(dataHubReceipt.native_model_context)
    ? dataHubReceipt.native_model_context.map(objectValue)
    : [];
  const bundleModels = Array.isArray(bundle.native_ml_context)
    ? bundle.native_ml_context.map(objectValue)
    : [];
  const receiptModelUrns = new Set(
    receiptModels.map((context) => stringValue(context.native_model_urn)),
  );
  const checks = Array.isArray(verification.checks)
    ? verification.checks.map(objectValue)
    : [];
  if (
    stringValue(capture.capture_type) !== "RECORDED_DATAHUB_END_TO_END" ||
    !booleanValue(capture.canonical_single_run) ||
    stringValue(capture.source_incident_id) !== replayManifest.incident_id ||
    stringValue(bundle.bundle_id) !== stringValue(capture.bundle_id) ||
    stringValue(bundle.status) !== "APPLIED" ||
    stringValue(change.commit_sha) !== stringValue(capture.commit_sha) ||
    stringValue(verification.commit_sha) !== stringValue(change.commit_sha) ||
    stringValue(approval.commit_sha) !== stringValue(change.commit_sha) ||
    stringValue(application.commit_sha) !== stringValue(change.commit_sha) ||
    stringValue(verification.receipt_id) !==
      stringValue(capture.verification_receipt_id) ||
    stringValue(approval.receipt_id) !== stringValue(capture.approval_receipt_id) ||
    stringValue(application.receipt_id) !==
      stringValue(capture.application_receipt_id) ||
    stringValue(application.status) !== "APPLIED" ||
    stringValue(application.target_environment) !==
      "SCIGUARD_SYNTHETIC_STAGING" ||
    booleanValue(application.production_authorized) ||
    checks.length !== 3 ||
    checks.some((check) => stringValue(check.status) !== "PASS") ||
    !booleanValue(boundaries.canonical_single_run) ||
    !booleanValue(boundaries.remote_pull_request_claimed) ||
    stringValue(boundaries.change_provider) !== "GITHUB" ||
    booleanValue(boundaries.production_authorized) ||
    stringValue(boundaries.source_incident_id) !== replayManifest.incident_id ||
    stringValue(boundaries.public_event_stream_sha256) !==
      replayManifest.events_sha256 ||
    stringValue(boundaries.datahub_native_receipt_sha256) !== dataHubReceiptDigest ||
    stringValue(boundaries.github_live_evidence_sha256) !== githubEvidenceDigest ||
    stringValue(boundaries.evaluation_report_sha256) !== evaluationReportDigest ||
    stringValue(captureBoundaries.datahub_native_receipt_sha256) !== dataHubReceiptDigest ||
    stringValue(dataHubReceipt.capture_type) !==
      "LIVE_DATAHUB_END_TO_END_CLOSURE" ||
    stringValue(dataHubReceipt.incident_id) !== replayManifest.incident_id ||
    stringValue(dataHubReceipt.public_event_stream_sha256) !==
      replayManifest.events_sha256 ||
    stringValue(dataHubReceipt.evaluation_report_sha256) !==
      evaluationReportDigest ||
    !booleanValue(dataHubReceipt.all_verified) ||
    numberValue(dataHubReceipt.entity_count) !== 19 ||
    stringValue(repairLifecycle.bundle_id) !== stringValue(bundle.bundle_id) ||
    stringValue(repairLifecycle.commit_sha) !== stringValue(change.commit_sha) ||
    stringValue(repairLifecycle.application_receipt_id) !==
      stringValue(application.receipt_id) ||
    stringValue(repairLifecycle.status) !== "APPLIED" ||
    stringValue(boundaries.datahub_server_version) !==
      stringValue(dataHubReceipt.server_version) ||
    bundleModels.length !== receiptModels.length ||
    bundleModels.some(
      (context) => !receiptModelUrns.has(stringValue(context.native_model_urn)),
    ) ||
    stringValue(bundle.datahub_incident_urn) !==
      stringValue(resolvedIncident.incident_urn) ||
    stringValue(bundle.datahub_decision_log_urn) !==
      stringValue(finalDecisionLog.document_urn)
  ) {
    throw new Error("Linked repair receipts do not satisfy the public honesty boundary");
  }
  return { bundle, dataHubReceipt };
}

function verifyGitHubLiveEvidence(
  rawEvidence: string,
  canonicalBundle: Record<string, JsonValue>,
): Record<string, JsonValue> {
  const evidence = JSON.parse(rawEvidence) as Record<string, JsonValue>;
  const pullRequest = objectValue(evidence.pull_request);
  const review = objectValue(evidence.authenticated_review);
  const actor = objectValue(evidence.authenticated_actor);
  const change = objectValue(evidence.change_receipt);
  const verification = objectValue(evidence.verification_receipt);
  const approvalBinding = objectValue(evidence.approval_binding);
  const canonicalBindings = objectValue(evidence.canonical_bindings);
  const canonicalChange = objectValue(canonicalBundle.external_action_receipt);
  const canonicalVerification = objectValue(canonicalBundle.verification_receipt);
  const canonicalApproval = objectValue(canonicalBundle.approval_receipt);
  const canonicalApplication = objectValue(canonicalBundle.application_receipt);
  const checks = Array.isArray(verification.checks)
    ? verification.checks.map(objectValue)
    : [];
  const headSha = stringValue(pullRequest.head_sha);
  const baseSha = stringValue(pullRequest.base_sha);
  const pullRequestUrl = stringValue(pullRequest.url);
  const expectedRepository =
    "https://github.com/songjie6816-code/sciguard-repair-sandbox";
  const expectedCheckPrefix = `${expectedRepository}/actions/runs/`;

  if (
    numberValue(evidence.schema_version) !== 2 ||
    stringValue(evidence.evidence_type) !==
      "GITHUB_REMOTE_REPAIR_AND_IDENTITY_BOUNDARY" ||
    stringValue(evidence.repository) !== expectedRepository ||
    !pullRequestUrl.startsWith(`${expectedRepository}/pull/`) ||
    stringValue(pullRequest.state) !== "open" ||
    !/^[0-9a-f]{40}$/.test(headSha) ||
    !/^[0-9a-f]{40}$/.test(baseSha) ||
    !stringValue(pullRequest.author_login) ||
    !numberValue(pullRequest.author_id) ||
    stringValue(change.provider) !== "GITHUB" ||
    stringValue(change.status) !== "PULL_REQUEST_OPEN" ||
    stringValue(change.remote_url) !== pullRequestUrl ||
    stringValue(change.commit_sha) !== headSha ||
    stringValue(change.base_commit_sha) !== baseSha ||
    numberValue(change.pull_request_number) !== numberValue(pullRequest.number) ||
    stringValue(verification.provider) !== "GITHUB_CHECK_RUNS" ||
    stringValue(verification.status) !== "PASS" ||
    stringValue(verification.commit_sha) !== headSha ||
    checks.length !== 3 ||
    checks.some(
      (check) =>
        stringValue(check.status) !== "PASS" ||
        !stringValue(check.details_url).startsWith(expectedCheckPrefix),
    ) ||
    stringValue(review.commit_id) !== headSha ||
    stringValue(review.reviewer_login) !== stringValue(actor.login) ||
    numberValue(review.reviewer_id) !== numberValue(actor.id) ||
    stringValue(review.identity_assurance) !== "GITHUB_ACCOUNT_REVIEW" ||
    booleanValue(review.enterprise_sso_verified) ||
    booleanValue(review.production_authorized) ||
    stringValue(evidence.incident_id) !== stringValue(canonicalBundle.incident_id) ||
    stringValue(evidence.bundle_id) !== stringValue(canonicalBundle.bundle_id) ||
    stringValue(change.commit_sha) !== stringValue(canonicalChange.commit_sha) ||
    stringValue(verification.receipt_id) !==
      stringValue(canonicalVerification.receipt_id) ||
    stringValue(approvalBinding.receipt_id) !==
      stringValue(canonicalApproval.receipt_id) ||
    stringValue(approvalBinding.commit_sha) !== headSha ||
    stringValue(canonicalBindings.incident_id) !==
      stringValue(canonicalBundle.incident_id) ||
    stringValue(canonicalBindings.bundle_id) !==
      stringValue(canonicalBundle.bundle_id) ||
    [canonicalBindings.publication_sha,
      canonicalBindings.verification_sha,
      canonicalBindings.approval_sha,
      canonicalBindings.application_sha,
      canonicalChange.commit_sha,
      canonicalVerification.commit_sha,
      canonicalApproval.commit_sha,
      canonicalApplication.commit_sha,
    ].some((value) => stringValue(value) !== headSha)
  ) {
    throw new Error("GitHub live evidence does not satisfy the public identity boundary");
  }
  return evidence;
}

function EvidenceLink({
  id,
  onSelect,
}: {
  id: string;
  onSelect: (id: string, trigger: HTMLButtonElement) => void;
}) {
  return (
    <button
      className="evidence-link"
      onClick={(event) => onSelect(id, event.currentTarget)}
      type="button"
    >
      <span>↗</span> {shortEvidence(id)}
    </button>
  );
}

function StatusMark({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  const symbol = ["resolved", "allow", "healthy", "confirmed", "pass"].some((item) =>
    normalized.includes(item),
  )
    ? "✓"
    : ["halt", "quarantined", "blocked", "fail"].some((item) =>
          normalized.includes(item),
        )
      ? "!"
      : normalized.includes("rejected")
        ? "×"
        : "•";
  return (
    <span className={`status-mark status-${normalized.replaceAll("_", "-")}`}>
      <span aria-hidden="true">{symbol}</span> {status}
    </span>
  );
}

export function CommandCenter({ judgeMode = false }: { judgeMode?: boolean }) {
  const [experienceView, setExperienceView] = useState<ExperienceView>(
    judgeMode ? "BRIEF" : "OPERATE",
  );
  const [manifest, setManifest] = useState<RunManifest | null>(null);
  const [events, setEvents] = useState<SciGuardEvent[]>([]);
  const [visibleCount, setVisibleCount] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [selectedEvidence, setSelectedEvidence] = useState<string>(
    "unit-firmware-contract:711d085fe8869ed0",
  );
  const [notice, setNotice] = useState("Loading verified recorded run…");
  const [apiHealth, setApiHealth] = useState<"unknown" | "ok" | "offline">("unknown");
  const [apiReason, setApiReason] = useState("Checking bounded API health…");
  const [integrity, setIntegrity] = useState<"pending" | "verified" | "failed">(
    "pending",
  );
  const [mode, setMode] = useState<RunMode>("RECORDED_REPLAY");
  const [repairOverride, setRepairOverride] = useState<Record<string, JsonValue> | null>(
    null,
  );
  const [dataHubLiveReceipt, setDataHubLiveReceipt] = useState<
    Record<string, JsonValue> | null
  >(null);
  const [githubLiveEvidence, setGithubLiveEvidence] = useState<
    Record<string, JsonValue> | null
  >(null);
  const [repairAction, setRepairAction] = useState<
    "idle" | "publish" | "verify" | "approval" | "apply" | "recover"
  >("idle");
  const [localDataHubEnabled, setLocalDataHubEnabled] = useState(false);
  const [focusedStage, setFocusedStage] = useState(0);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerEventId, setDrawerEventId] = useState<string | null>(null);
  const eventSource = useRef<EventSource | null>(null);
  const drawerRef = useRef<HTMLElement | null>(null);
  const drawerCloseRef = useRef<HTMLButtonElement | null>(null);
  const drawerTriggerRef = useRef<HTMLElement | null>(null);

  const apiBase = useMemo(() => {
    if (judgeMode) return "";
    if (CONFIGURED_API_BASE) return CONFIGURED_API_BASE.replace(/\/$/, "");
    if (typeof window !== "undefined" && ["localhost", "127.0.0.1"].includes(window.location.hostname)) {
      return LOCAL_API_BASE;
    }
    return "";
  }, [judgeMode]);

  const loadReplay = useCallback(async (showFinal = false) => {
    setPlaying(false);
    setIntegrity("pending");
    eventSource.current?.close();
    const [
      manifestResponse,
      eventsResponse,
      repairManifestResponse,
      repairBundleResponse,
      dataHubReceiptResponse,
      evaluationReportResponse,
      githubEvidenceResponse,
    ] = await Promise.all([
      fetch(`/replays/${REPLAY_ID}/manifest.json`, { cache: "no-store" }),
      fetch(`/replays/${REPLAY_ID}/events.jsonl`, { cache: "no-store" }),
      fetch(`/replays/${REPLAY_ID}/repair-manifest.json`, { cache: "no-store" }),
      fetch(`/replays/${REPLAY_ID}/repair-bundle.json`, { cache: "no-store" }),
      fetch("/evidence/datahub_live_receipt.json", { cache: "no-store" }),
      fetch("/evidence/evaluation_report.json", { cache: "no-store" }),
      fetch("/evidence/github_live_evidence.json", { cache: "no-store" }),
    ]);
    if (
      !manifestResponse.ok ||
      !eventsResponse.ok ||
      !repairManifestResponse.ok ||
      !repairBundleResponse.ok ||
      !dataHubReceiptResponse.ok ||
      !evaluationReportResponse.ok ||
      !githubEvidenceResponse.ok
    ) {
      throw new Error("Recorded replay bundle is unavailable");
    }
    const replayManifest = (await manifestResponse.json()) as RunManifest;
    const rawEvents = await eventsResponse.text();
    const replayEvents = await verifyReplayBundle(replayManifest, rawEvents);
    const rawRepairManifest = await repairManifestResponse.text();
    const rawRepairBundle = await repairBundleResponse.text();
    const rawDataHubReceipt = await dataHubReceiptResponse.text();
    const rawEvaluationReport = await evaluationReportResponse.text();
    const rawGitHubEvidence = await githubEvidenceResponse.text();
    const verifiedRepair = await verifyRepairCapture(
      replayManifest,
      rawRepairManifest,
      rawRepairBundle,
      rawDataHubReceipt,
      rawEvaluationReport,
      rawGitHubEvidence,
    );
    const verifiedGitHubEvidence = verifyGitHubLiveEvidence(
      rawGitHubEvidence,
      verifiedRepair.bundle,
    );
    setManifest(replayManifest);
    setEvents(replayEvents);
    setRepairOverride(verifiedRepair.bundle);
    setDataHubLiveReceipt(verifiedRepair.dataHubReceipt);
    setGithubLiveEvidence(verifiedGitHubEvidence);
    setVisibleCount(showFinal ? replayEvents.length : 0);
    setMode("RECORDED_REPLAY");
    setIntegrity("verified");
    setNotice(
      showFinal
        ? `Final state · ${REPLAY_EVENT_DISCLOSURE}`
        : `Ready · ${REPLAY_EVENT_DISCLOSURE}`,
    );
    return replayEvents;
  }, []);

  useEffect(() => {
    const replayTimer = window.setTimeout(() => {
      setLocalDataHubEnabled(
        !judgeMode &&
          ["localhost", "127.0.0.1"].includes(window.location.hostname),
      );
      void loadReplay(false).catch((error: unknown) => {
        setIntegrity("failed");
        setNotice(error instanceof Error ? error.message : "Replay failed to load");
      });
      if (judgeMode) {
        setApiHealth("offline");
        setApiReason(
          "Judge Mode is intentionally static: no keys, paid API, or local DataHub required.",
        );
      } else if (!apiBase) {
        setApiHealth("offline");
        setApiReason("No public live backend is configured for this hosted build.");
      } else {
        void fetch(`${apiBase}/healthz`)
          .then(async (response) => {
            if (!response.ok) throw new Error(`health check returned ${response.status}`);
            const health = (await response.json()) as { status?: string };
            if (health.status !== "ok") throw new Error("a live dependency is degraded");
            setApiHealth("ok");
            setApiReason("Bounded API and required dependencies are healthy.");
          })
          .catch((error: unknown) => {
            setApiHealth("offline");
            setApiReason(
              `Live backend unavailable: ${error instanceof Error ? error.message : "health check failed"}.`,
            );
          });
      }
    }, 0);
    return () => {
      window.clearTimeout(replayTimer);
      eventSource.current?.close();
    };
  }, [apiBase, judgeMode, loadReplay]);

  useEffect(() => {
    if (!playing) return;
    const interval = events.length > 1 ? REPLAY_DURATION_MS / (events.length - 1) : 0;
    const timer = window.setTimeout(() => {
      if (visibleCount >= events.length) {
        setPlaying(false);
        setNotice(`Complete · ${REPLAY_EVENT_DISCLOSURE}`);
      } else {
        setVisibleCount((count) => Math.min(events.length, count + 1));
      }
    }, visibleCount >= events.length ? 0 : interval);
    return () => window.clearTimeout(timer);
  }, [events.length, playing, visibleCount]);

  useEffect(() => {
    if (!drawerOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.setTimeout(() => drawerCloseRef.current?.focus(), 0);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setDrawerOpen(false);
        window.setTimeout(() => drawerTriggerRef.current?.focus(), 0);
        return;
      }
      if (event.key !== "Tab" || !drawerRef.current) return;
      const focusable = Array.from(
        drawerRef.current.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), summary, [tabindex]:not([tabindex="-1"])',
        ),
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable.at(-1) ?? first;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [drawerOpen]);

  const closeDrawer = useCallback(() => {
    setDrawerOpen(false);
    window.setTimeout(() => drawerTriggerRef.current?.focus(), 0);
  }, []);

  const connectLiveStream = useCallback((runManifest: RunManifest) => {
    eventSource.current?.close();
    if (!apiBase) return;
    const source = new EventSource(`${apiBase}/api/runs/${runManifest.incident_id}/events`);
    eventSource.current = source;
    source.addEventListener("sciguard-event", (message) => {
      const frame = JSON.parse((message as MessageEvent).data) as EventFrame;
      setEvents((current) => {
        if (current.some((event) => event.event_id === frame.event.event_id)) return current;
        return [...current, frame.event].sort((a, b) => a.sequence - b.sequence);
      });
      setVisibleCount((count) => count + 1);
    });
    source.onerror = () => source.close();
  }, [apiBase]);

  const startLive = useCallback(async () => {
    setNotice("Requesting a real DataHub-backed run…");
    if (!apiBase) throw new Error(apiReason);
    const response = await fetch(`${apiBase}/api/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(`Live run unavailable: ${detail}`);
    }
    const view = (await response.json()) as { manifest: RunManifest };
    setManifest(view.manifest);
    setEvents([]);
    setRepairOverride(null);
    setDataHubLiveReceipt(null);
    setGithubLiveEvidence(null);
    setVisibleCount(0);
    setMode("LIVE");
    setPlaying(false);
    setNotice("LIVE · events are arriving from the bounded API");
    connectLiveStream(view.manifest);
  }, [apiBase, apiReason, connectLiveStream]);

  const playStory = useCallback(async () => {
    const replayEvents = await loadReplay(false);
    if (!replayEvents.length) return;
    setVisibleCount(1);
    setPlaying(true);
    setNotice("Playing · deterministic 15s narration over verified event order");
  }, [loadReplay]);

  const visibleEvents = useMemo(
    () => events.slice(0, visibleCount),
    [events, visibleCount],
  );
  const activeStage = stageIndexFromEvents(visibleEvents);
  const incidentState = stateFromEvents(visibleEvents, manifest ? "READY" : "LOADING");
  const latestEvent = visibleEvents.at(-1);
  const controllerRuntime = formatSeconds(eventSpanMs(events));
  const playbackState = playing
    ? "PLAYING"
    : visibleCount > 0 && visibleCount === events.length
      ? "COMPLETE"
      : manifest
        ? "READY"
        : "LOADING";

  const displayedFocusedStage =
    playing || playbackState === "COMPLETE" ? activeStage : focusedStage;

  const evidence = useMemo(() => {
    const records = new Map<string, EvidenceRecord>();
    records.set(evaluationEvidence.evidence_id, evaluationEvidence);
    records.set(dataHubCapabilityEvidence.evidence_id, dataHubCapabilityEvidence);
    if (dataHubLiveReceipt) {
      const incidentLifecycle = objectValue(dataHubLiveReceipt.incident_lifecycle);
      const resolvedIncident = objectValue(incidentLifecycle.resolved);
      const decisionLogLifecycle = objectValue(
        dataHubLiveReceipt.decision_log_lifecycle,
      );
      const finalDecisionLog = objectValue(decisionLogLifecycle.final);
      const repairLifecycle = objectValue(dataHubLiveReceipt.repair_lifecycle);
      records.set(DATAHUB_LIVE_RECEIPT_EVIDENCE_ID, {
        evidence_id: DATAHUB_LIVE_RECEIPT_EVIDENCE_ID,
        source: stringValue(
          dataHubLiveReceipt.capture_type,
          "LIVE_DATAHUB_END_TO_END_CLOSURE",
        ),
        kind: "DATAHUB_LIVE_RECEIPT",
        summary: "DataHub Incident, Decision Log, ML context, and repair closure",
        payload: {
          datahub_urn: stringValue(resolvedIncident.incident_urn),
          incident_state: stringValue(incidentLifecycle.readback_state),
          incident_stage: stringValue(incidentLifecycle.readback_stage),
          decision_log_urn: stringValue(finalDecisionLog.document_urn),
          decision_log_status: stringValue(finalDecisionLog.status),
          native_entity_count: dataHubLiveReceipt.entity_count ?? 0,
          repair_status: stringValue(repairLifecycle.status),
          actions: [
            "INCIDENT_RESOLVED",
            "DECISION_LOG_PUBLISHED",
            "ML_CONTEXT_READ_BACK",
            "REPAIR_APPLIED",
          ],
          receipt: dataHubLiveReceipt,
        },
      });
    }
    if (githubLiveEvidence) {
      const pullRequest = objectValue(githubLiveEvidence.pull_request);
      const review = objectValue(githubLiveEvidence.authenticated_review);
      const verification = objectValue(githubLiveEvidence.verification_receipt);
      records.set(GITHUB_LIVE_EVIDENCE_ID, {
        evidence_id: GITHUB_LIVE_EVIDENCE_ID,
        source: "GITHUB_REMOTE_VERIFICATION",
        kind: "GITHUB_PR_CHECKS_AND_IDENTITY_BOUNDARY",
        summary: "Real GitHub PR, exact-SHA hosted checks, and truthful identity boundary",
        payload: {
          ...githubLiveEvidence,
          deterministic_effect:
            "A reviewable repair exists at the exact verified head SHA",
          reason_code: "PRODUCTION_AUTHORIZATION_REMAINS_FALSE",
          actions: [
            "PULL_REQUEST_OPEN",
            "THREE_HOSTED_CHECKS_PASS",
            "AUTHENTICATED_REVIEW_RECORDED",
          ],
          pull_request_url: stringValue(pullRequest.url),
          review_url: stringValue(review.url),
          verification_status: stringValue(verification.status),
        },
      });
    }
    for (const event of visibleEvents) {
      const entries = event.payload.evidence;
      if (!Array.isArray(entries)) continue;
      for (const item of entries) {
        const entry = objectValue(item);
        const evidenceId = stringValue(entry.evidence_id);
        if (!evidenceId) continue;
        records.set(evidenceId, {
          evidence_id: evidenceId,
          source: stringValue(entry.source, "EVENT_STREAM"),
          kind: stringValue(entry.kind, event.event_type),
          summary: stringValue(entry.summary, event.summary),
          payload: objectValue(entry.payload),
        });
      }
      for (const evidenceId of event.evidence_ids) {
        if (!records.has(evidenceId)) {
          records.set(evidenceId, {
            evidence_id: evidenceId,
            source: event.actor,
            kind: event.event_type,
            summary: event.summary,
            payload: event.payload,
          });
        }
      }
    }
    const impactRecordEvent = visibleEvents.find(
      (event) => event.event_type === "IMPACT_MAPPED",
    );
    if (impactRecordEvent) {
      const affectedUrns = stringArray(impactRecordEvent.payload.affected_urns);
      const unaffectedUrns = stringArray(impactRecordEvent.payload.unaffected_urns);
      stringArray(impactRecordEvent.payload.affected_names).forEach((name, index) => {
        records.set(assetReceiptId(name), {
          evidence_id: assetReceiptId(name),
          source: "RECORDED_DATAHUB_FIELD_LINEAGE",
          kind: "PUBLIC_ASSET_RECEIPT",
          summary: `${formatName(name)} is inside the affected Tg field cone`,
          payload: {
            datahub_urn: affectedUrns[index] ?? "not recorded",
            field_cone: "AFFECTED",
            deterministic_effect: "HALT or WARN according to asset role",
            hosted_link_status:
              "Public read-only receipt; local catalog link is intentionally disabled",
          },
        });
      });
      stringArray(impactRecordEvent.payload.unaffected_names).forEach((name, index) => {
        records.set(assetReceiptId(name), {
          evidence_id: assetReceiptId(name),
          source: "RECORDED_DATAHUB_FIELD_LINEAGE",
          kind: "PUBLIC_ASSET_RECEIPT",
          summary: `${formatName(name)} is outside the affected Tg field cone`,
          payload: {
            datahub_urn: unaffectedUrns[index] ?? "not recorded",
            field_cone: "PRESERVED",
            deterministic_effect: "ALLOW",
            hosted_link_status:
              "Public read-only receipt; local catalog link is intentionally disabled",
          },
        });
      });
    }
    return records;
  }, [dataHubLiveReceipt, githubLiveEvidence, visibleEvents]);

  const hypotheses = visibleEvents.filter((event) =>
    ["HYPOTHESIS_PROPOSED", "HYPOTHESIS_RESOLVED"].includes(event.event_type),
  );
  const resolvedById = new Map(
    hypotheses
      .filter((event) => event.event_type === "HYPOTHESIS_RESOLVED")
      .map((event) => [stringValue(event.payload.hypothesis_id), event]),
  );
  const proposed = hypotheses.filter((event) => event.event_type === "HYPOTHESIS_PROPOSED");
  const impactEvent = visibleEvents.find((event) => event.event_type === "IMPACT_MAPPED");
  const affected = new Set(stringArray(impactEvent?.payload.affected_names));
  const unaffected = new Set(stringArray(impactEvent?.payload.unaffected_names));
  const policyEvents = visibleEvents.filter((event) => event.event_type === "POLICY_DECIDED");
  const signalEvent = visibleEvents.find((event) => event.event_type === "SIGNAL_DETECTED");
  const escalationEvent = visibleEvents.find(
    (event) => event.event_type === "ESCALATION_DECIDED",
  );
  const initialScope = Array.isArray(signalEvent?.payload.initial_scope)
    ? signalEvent.payload.initial_scope.length + 1
    : 0;
  const policyCount = (decision: string) =>
    policyEvents.filter((event) => event.payload.decision === decision).length;
  const blockedEvent = visibleEvents.find(
    (event) => numberValue(event.payload.exit_code, -1) === 42,
  );
  const allowedEvent = visibleEvents.find(
    (event) =>
      numberValue(event.payload.exit_code, -1) === 0 &&
      event.payload.asset_name === "formulation_report",
  );
  const recoveryEvent = [...visibleEvents]
    .reverse()
    .find((event) => ["RECOVERY_CHECKED", "INCIDENT_RESOLVED"].includes(event.event_type));
  const recoveryPayload = recoveryEvent?.payload ?? {};
  const failedChecks = new Set(stringArray(recoveryPayload.failed_checks));
  const cleanRunCount = numberValue(recoveryPayload.clean_run_count);
  const resumeAllowed = booleanValue(recoveryPayload.resume_allowed);
  const recoveryVerificationEvent = [...visibleEvents]
    .reverse()
    .find((event) => event.event_type === "RECOVERY_EVIDENCE_REFRESHED");
  const recoveryVerificationChecks = Array.isArray(
    recoveryVerificationEvent?.payload.checks,
  )
    ? recoveryVerificationEvent.payload.checks.map(objectValue)
    : [];
  const recoveryCheckIds = recoveryVerificationChecks.length
    ? recoveryVerificationChecks.map((check) => stringValue(check.check_id))
    : RECOVERY_CHECKS;
  const repairEvent = [...visibleEvents].reverse().find((event) =>
    [
      "REPAIR_BUNDLE_CREATED",
      "REPAIR_PUBLISHED",
      "REPAIR_VERIFIED",
      "APPROVAL_RECORDED",
      "REPAIR_APPLIED",
    ].includes(event.event_type),
  );
  const repairPayload = repairOverride ?? repairEvent?.payload ?? {};
  const repairArtifacts = Array.isArray(repairPayload.artifacts)
    ? repairPayload.artifacts.map(objectValue)
    : [];
  const nativeMLContext = Array.isArray(repairPayload.native_ml_context)
    ? repairPayload.native_ml_context.map(objectValue)
    : [];
  const hasNativeMLReceipt = nativeMLContext.length > 0;
  const affectedNativeContext =
    nativeMLContext.find((context) => booleanValue(context.affected)) ?? {};
  const preservedNativeContext =
    nativeMLContext.find((context) => !booleanValue(context.affected)) ?? {};
  const dataHubEntityCount = numberValue(dataHubLiveReceipt?.entity_count);
  const dataHubServerVersion = stringValue(dataHubLiveReceipt?.server_version);
  const dataHubIncidentLifecycle = objectValue(
    dataHubLiveReceipt?.incident_lifecycle,
  );
  const dataHubDecisionLogLifecycle = objectValue(
    dataHubLiveReceipt?.decision_log_lifecycle,
  );
  const repairChecks = Array.isArray(repairPayload.verification_checks)
    ? repairPayload.verification_checks.map(objectValue)
    : [];
  const repairApproval = objectValue(repairPayload.approval);
  const changeReceipt = objectValue(repairPayload.external_action_receipt);
  const verificationReceipt = objectValue(repairPayload.verification_receipt);
  const verificationReceipts = Array.isArray(verificationReceipt.checks)
    ? verificationReceipt.checks.map(objectValue)
    : [];
  const verificationById = new Map(
    verificationReceipts.map((receipt) => [stringValue(receipt.check_id), receipt]),
  );
  const approvalReceipt = objectValue(repairPayload.approval_receipt);
  const applicationReceipt = objectValue(repairPayload.application_receipt);
  const linkedCapture = objectValue(repairPayload.linked_capture);
  const repairStatus = stringValue(repairPayload.status, "PROPOSED");
  const repairPatch = repairArtifacts.find(
    (artifact) => artifact.kind === "CODE_PATCH",
  );
  const canOperateRepair = Boolean(
    mode === "LIVE" && apiBase && manifest?.incident_id && apiHealth === "ok",
  );

  const runRepairAction = async (
    action: "publish" | "verify" | "approval" | "apply" | "recover",
  ) => {
    if (!canOperateRepair || !manifest) {
      throw new Error("Repair actions require a healthy local live sandbox.");
    }
    setRepairAction(action);
    setNotice(`${action.toUpperCase()} · executing against the bounded backend…`);
    try {
      const actionUrl =
        action === "recover"
          ? `${apiBase}/api/runs/${manifest.incident_id}/recovery`
          : `${apiBase}/api/runs/${manifest.incident_id}/repair/${action}`;
      const response = await fetch(
        actionUrl,
        {
          method: "POST",
          headers:
            action === "approval" || action === "recover"
              ? { "Content-Type": "application/json" }
              : {},
          body:
            action === "approval"
              ? JSON.stringify({
                  reviewer_urn: stringValue(repairApproval.approver_urn),
                  decision: "APPROVE",
                  note:
                    "Reviewed the commit-bound unit contract, scientific decision, and safe-branch evidence.",
                })
              : action === "recover"
                ? JSON.stringify({})
              : undefined,
        },
      );
      if (!response.ok) {
        throw new Error(await response.text());
      }
      const actionReceipt = (await response.json()) as Record<string, JsonValue>;
      if (action !== "recover") {
        setRepairOverride(actionReceipt);
      }

      const lastSequence = events.at(-1)?.sequence ?? -1;
      const eventResponse = await fetch(
        `${apiBase}/api/runs/${manifest.incident_id}/events?after_sequence=${lastSequence}`,
      );
      if (eventResponse.ok) {
        const newEvents = (await eventResponse.text())
          .split("\n")
          .filter((line) => line.startsWith("data: "))
          .map((line) => JSON.parse(line.slice(6)) as EventFrame)
          .map((frame) => frame.event);
        if (newEvents.length) {
          setEvents((current) => [...current, ...newEvents]);
          setVisibleCount((current) => current + newEvents.length);
        }
      }
      setNotice(
        action === "recover"
          ? `RECOVERY · clean run ${numberValue(actionReceipt.clean_run_count)} of 2 recorded`
          : `${action.toUpperCase()} · receipt recorded in the immutable event stream`,
      );
    } finally {
      setRepairAction("idle");
    }
  };

  const nodeClass = (name: string) => {
    if (!impactEvent) return "node-datahub";
    if (affected.has(name)) return "node-critical";
    if (unaffected.has(name)) return "node-healthy";
    return "node-datahub";
  };

  const rankEvidence = "rank-baseline-comparison:55a5b1ad73eb48b1";
  const unitEvidence = "unit-firmware-contract:711d085fe8869ed0";
  const modelEvidence = "model-release-context:4a4561dbb638527d";
  const experimentEvidence = "experimental-value-check:916960df3b3c41fa";
  const impactEvidence = impactEvent?.evidence_ids[0] ?? "field-impact:pending";

  const selectedRecord = evidence.get(selectedEvidence) ?? evidence.values().next().value;
  const selectedUrn = stringValue(selectedRecord?.payload.datahub_urn);
  const localDataHubHref =
    localDataHubEnabled && selectedUrn.startsWith("urn:li:dataset:")
      ? `${LOCAL_DATAHUB_BASE}/dataset/${encodeURIComponent(selectedUrn)}`
      : null;

  const openEvidence = useCallback(
    (id: string, trigger: HTMLElement, eventId: string | null = null) => {
      drawerTriggerRef.current = trigger;
      setSelectedEvidence(id);
      setDrawerEventId(eventId);
      setDrawerOpen(true);
    },
    [],
  );

  const inspectStage = useCallback(
    (index: number, trigger: HTMLButtonElement) => {
      setFocusedStage(index);
      const matchingEvent = [...visibleEvents]
        .reverse()
        .find((event) => stageIndexForEvent(event) === index);
      openEvidence(
        matchingEvent?.evidence_ids[0] ?? `stage:${JUDGE_STAGES[index].id}`,
        trigger,
        matchingEvent?.event_id ?? null,
      );
    },
    [openEvidence, visibleEvents],
  );

  const drawerEvent =
    visibleEvents.find((event) => event.event_id === drawerEventId) ??
    visibleEvents.find((event) => event.evidence_ids.includes(selectedEvidence));
  const drawerRecord = evidence.get(selectedEvidence);
  const drawerPayload = drawerRecord?.payload ?? drawerEvent?.payload ?? {};
  const drawerChanges = Array.isArray(drawerPayload.changes)
    ? objectValue(drawerPayload.changes[0])
    : {};
  const drawerUrn =
    stringValue(drawerPayload.datahub_urn) ||
    stringValue(drawerPayload.urn) ||
    stringValue(drawerPayload.source_urn) ||
    stringValue(drawerPayload.changed_urn) ||
    stringValue(drawerPayload.start_urn) ||
    stringValue(drawerPayload.model_urn) ||
    "Not present in this evidence";
  const drawerField =
    stringArray(drawerPayload.source_fields)[0] ||
    stringValue(drawerPayload.field) ||
    stringValue(drawerChanges.field) ||
    (selectedEvidence.startsWith("unit-") ? "tg_value" : "Not present in this evidence");
  const downstreamImpact =
    stringValue(drawerPayload.deterministic_effect) ||
    stringValue(drawerPayload.field_cone) ||
    stringValue(drawerPayload.reason_code) ||
    stringValue(drawerPayload.decision) ||
    (stringArray(drawerPayload.affected_names).length
      ? `${stringArray(drawerPayload.affected_names).length} affected / ${stringArray(drawerPayload.unaffected_names).length} preserved assets`
      : "Not present in this evidence");
  const policyRule =
    stringArray(drawerPayload.matched_rule_ids).join(", ") ||
    stringValue(drawerPayload.reason_code) ||
    "Not present in this evidence";
  const enforcementAction =
    stringArray(drawerPayload.actions).join(", ") ||
    stringValue(drawerPayload.decision) ||
    (typeof drawerPayload.exit_code === "number"
      ? `Process exit ${drawerPayload.exit_code}`
      : "Not present in this evidence");
  const drawerStageIndex = drawerEvent
    ? stageIndexForEvent(drawerEvent)
    : JUDGE_STAGES.findIndex(
        (stage) => selectedEvidence === `stage:${stage.id}`,
      );
  const drawerResolvedStageIndex =
    drawerStageIndex >= 0 ? drawerStageIndex : displayedFocusedStage;
  const drawerStage = JUDGE_STAGES[drawerResolvedStageIndex];
  const drawerIsCrossRunEvaluation =
    selectedEvidence === evaluationEvidence.evidence_id;
  const drawerIsDataHubReceipt =
    selectedEvidence === DATAHUB_LIVE_RECEIPT_EVIDENCE_ID;
  const drawerIsGitHubEvidence =
    selectedEvidence === GITHUB_LIVE_EVIDENCE_ID;
  const drawerGitHubPullRequest = objectValue(drawerPayload.pull_request);
  const drawerGitHubReview = objectValue(drawerPayload.authenticated_review);
  const drawerGitHubVerification = objectValue(
    drawerPayload.verification_receipt,
  );
  const drawerGitHubChecks = Array.isArray(drawerGitHubVerification.checks)
    ? drawerGitHubVerification.checks.map(objectValue)
    : [];

  return (
    <main className={`command-center ${judgeMode ? "judge-mode" : "product-mode"} experience-${experienceView.toLowerCase()} stage-focus-${activeStage + 1}`}>
      <header className="global-header">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true"><span>SG</span></div>
          <div>
            <strong>SciGuard Autopilot</strong>
            <small>Scientific Decision Control Plane</small>
          </div>
        </div>
        <div className="header-status" aria-label="Incident status">
          <span className="mono incident-id">{manifest?.incident_id ?? "SG-LOADING"}</span>
          <StatusMark status={incidentState} />
          <span className={`mode-badge mode-${mode.toLowerCase()}`}><i /> {mode.replace("_", " ")}</span>
          <span className="backend-pill"><i /> {manifest?.datahub_backend ?? "DATAHUB"}</span>
        </div>
        <div className="header-actions">
          <button
            aria-label="Open Evidence Center"
            className="button evidence-center-trigger"
            onClick={(event) =>
              openEvidence(
                dataHubLiveReceipt
                  ? DATAHUB_LIVE_RECEIPT_EVIDENCE_ID
                  : evaluationEvidence.evidence_id,
                event.currentTarget,
              )
            }
            type="button"
          >
            <span aria-hidden="true">⌁</span> EVIDENCE CENTER
          </button>
          <button
            aria-label="Run the 15 second verified replay"
            className="button primary"
            disabled={integrity === "failed"}
            onClick={() => void playStory().catch((error: unknown) => {
              setIntegrity("failed");
              setNotice(error instanceof Error ? error.message : "Replay failed");
            })}
            type="button"
          >
            {playing ? "PLAYING VERIFIED REPLAY" : "RUN 15s VERIFIED REPLAY"}
          </button>
          <button
            className="button ghost"
            onClick={() => void loadReplay(true).catch((error: unknown) => {
              setIntegrity("failed");
              setNotice(error instanceof Error ? error.message : "Replay failed to load");
            })}
            type="button"
          >
            SHOW FINAL STATE
          </button>
        </div>
      </header>

      <nav className="experience-switcher" aria-label="Experience detail level">
        {(["BRIEF", "OPERATE", "AUDIT"] as ExperienceView[]).map((view) => (
          <button
            aria-pressed={experienceView === view}
            className={experienceView === view ? "active" : ""}
            key={view}
            onClick={() => setExperienceView(view)}
            type="button"
          >
            <span>{view}</span>
            <small>
              {view === "BRIEF"
                ? "Understand the decision"
                : view === "OPERATE"
                  ? "Inspect impact and action"
                  : "Verify every receipt"}
            </small>
          </button>
        ))}
      </nav>

      {judgeMode && experienceView === "BRIEF" && (
        <section className="decision-brief" aria-labelledby="decision-brief-title">
          <div className="brief-signal">
            <div className="brief-eyebrow">
              <span>SCIENTIFIC DECISION INCIDENT</span>
              <i />
              <strong>POLYMER R&amp;D</strong>
            </div>
            <h1 id="decision-brief-title">
              The pipeline passed.
              <em>The decision became unsafe.</em>
            </h1>
            <p>
              An instrument changed temperature units without breaking the pipeline.
              SciGuard used DataHub to prove which scientific path was contaminated,
              blocked only the unsafe recommendation, and kept independent work running.
            </p>
            <div className="brief-actions">
              <button
                className="button primary"
                disabled={integrity === "failed"}
                onClick={() =>
                  void playStory().catch((error: unknown) => {
                    setIntegrity("failed");
                    setNotice(error instanceof Error ? error.message : "Replay failed");
                  })
                }
                type="button"
              >
                {playing ? "RUNNING VERIFIED STORY" : "RUN VERIFIED STORY"}
              </button>
              <button
                className="button ghost"
                onClick={() => setExperienceView("OPERATE")}
                type="button"
              >
                EXPLORE DECISION GRAPH
              </button>
            </div>
            <div className="brief-trust">
              <span className={`live-${apiHealth}`}>
                <i />
                {apiHealth === "ok" ? "LIVE SANDBOX READY" : "VERIFIED REPLAY READY"}
              </span>
              <span>
                {integrity === "verified"
                  ? `55 events + ${dataHubEntityCount} native entities verified`
                  : "Verifying evidence"}
              </span>
              <span>Deterministic safety policy</span>
            </div>
          </div>

          <div className="brief-rank" aria-label="Candidate P-204 moved from trusted rank 18 to unsafe rank 1">
            <div className="brief-rank-top">
              <span>CANDIDATE POLYMER · P-204</span>
              <StatusMark status={resumeAllowed ? "RESOLVED" : blockedEvent ? "BLOCKED" : "AT RISK"} />
            </div>
            <div className="brief-rank-change">
              <div>
                <small>TRUSTED DECISION</small>
                <strong>#18</strong>
              </div>
              <div className="brief-causal-arrow">
                <span>→</span>
                <small>187 mixed-unit rows</small>
              </div>
              <div>
                <small>UNSAFE OUTPUT</small>
                <strong>#1</strong>
              </div>
            </div>
            <div className="brief-contradiction">
              <span><i /> PIPELINE SUCCESS</span>
              <strong>SCIENTIFIC CONTRACT FAILED</strong>
            </div>
          </div>

          <div className="brief-outcomes">
            <article>
              <span className="outcome-icon critical">!</span>
              <div>
                <small>UNSAFE DECISION</small>
                <strong>{blockedEvent ? "Publication blocked" : "Candidate ranking at risk"}</strong>
                <p>Heat-resistance recommendation cannot reach the research meeting.</p>
              </div>
            </article>
            <article>
              <span className="outcome-icon healthy">✓</span>
              <div>
                <small>SAFE WORK PRESERVED</small>
                <strong>{allowedEvent ? "Formulation continued" : "Independent branch proven"}</strong>
                <p>Molecular-weight analysis remains available throughout the incident.</p>
              </div>
            </article>
            <article>
              <span className="outcome-icon evidence">⌁</span>
              <div>
                <small>WHY DATAHUB</small>
                <strong>Exact cone: 3 / 3</strong>
                <p>Search-only recovered 0 / 3 exact decision cones.</p>
              </div>
            </article>
          </div>

          <div className="brief-graph-shell">
            <div className="brief-section-heading">
              <div>
                <span>DATAHUB DECISION GRAPH</span>
                <h2>One changed field. Two very different outcomes.</h2>
              </div>
              <button
                className="button text"
                onClick={() => setExperienceView("AUDIT")}
                type="button"
              >
                AUDIT THE EVIDENCE →
              </button>
            </div>
            <div className="brief-graph" aria-label="DataHub decision graph with affected and preserved branches">
              <div className="brief-node source">
                <small>INSTRUMENT</small>
                <strong>B042 · DSC-07</strong>
                <span>firmware v4.2</span>
              </div>
              <span className="brief-edge critical">tg_value</span>
              <div className="brief-node context">
                <small>DATASET</small>
                <strong>Experimental data</strong>
                <span>unit contract · owner</span>
              </div>
              <span className="brief-edge split">field lineage</span>
              <div className="brief-branches">
                <div className="brief-branch affected">
                  <div className="brief-node">
                    <small>{hasNativeMLReceipt ? "NATIVE ML FEATURE" : "FEATURE PROJECTION"}</small>
                    <strong>Heat resistance · Tg</strong>
                  </div>
                  <div className="brief-node">
                    <small>{hasNativeMLReceipt ? "NATIVE ML MODEL" : "MODEL VERSION"}</small>
                    <strong>Tg Model · v3</strong>
                    {hasNativeMLReceipt && (
                      <span>
                        {Array.isArray(affectedNativeContext.training_job_urns)
                          ? affectedNativeContext.training_job_urns.length
                          : 0}{" "}
                        train ·{" "}
                        {stringValue(
                          objectValue(
                            Array.isArray(affectedNativeContext.deployment_context)
                              ? affectedNativeContext.deployment_context[0]
                              : undefined,
                          ).status,
                          "deployment",
                        )}{" "}
                        ·{" "}
                        {Array.isArray(affectedNativeContext.inference_job_urns)
                          ? affectedNativeContext.inference_job_urns.length
                          : 0}{" "}
                        infer
                      </span>
                    )}
                  </div>
                  <div className="brief-node decision">
                    <small>SCIENTIFIC DECISION</small>
                    <strong>Candidate ranking</strong>
                    <StatusMark status={impactEvent ? "HALT" : "PENDING"} />
                  </div>
                </div>
                <div className="brief-branch preserved">
                  <div className="brief-node">
                    <small>{hasNativeMLReceipt ? "NATIVE ML FEATURE" : "FEATURE PROJECTION"}</small>
                    <strong>Molecular weight · MW</strong>
                  </div>
                  <div className="brief-node">
                    <small>{hasNativeMLReceipt ? "NATIVE ML MODEL" : "MODEL VERSION"}</small>
                    <strong>Durability Model · v2</strong>
                    {hasNativeMLReceipt && (
                      <span>
                        {Array.isArray(preservedNativeContext.training_job_urns)
                          ? preservedNativeContext.training_job_urns.length
                          : 0}{" "}
                        train ·{" "}
                        {stringValue(
                          objectValue(
                            Array.isArray(preservedNativeContext.deployment_context)
                              ? preservedNativeContext.deployment_context[0]
                              : undefined,
                          ).status,
                          "deployment",
                        )}{" "}
                        ·{" "}
                        {Array.isArray(preservedNativeContext.inference_job_urns)
                          ? preservedNativeContext.inference_job_urns.length
                          : 0}{" "}
                        infer
                      </span>
                    )}
                  </div>
                  <div className="brief-node decision">
                    <small>SCIENTIFIC DECISION</small>
                    <strong>Formulation report</strong>
                    <StatusMark status={impactEvent ? "ALLOW" : "PENDING"} />
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="brief-progress" aria-label="Verified incident progress">
            {[
              ["01", "CHANGE", activeStage >= 0],
              ["02", "PROVE", activeStage >= 2],
              ["03", "PROTECT", activeStage >= 4],
              ["04", "RECOVER", activeStage >= 5 && resumeAllowed],
            ].map(([number, label, achieved]) => (
              <div className={achieved ? "achieved" : ""} key={String(label)}>
                <span>{String(number)}</span>
                <strong>{String(label)}</strong>
                <small>{achieved ? "VERIFIED" : "WAITING"}</small>
              </div>
            ))}
          </div>
        </section>
      )}

      {experienceView !== "BRIEF" && <section className="runtime-strip" aria-label="Runtime and replay status">
        <div className={`live-backend live-${apiHealth}`}>
          <span><i /> LIVE BACKEND · {apiHealth === "ok" ? "ONLINE" : apiHealth === "offline" ? "OFFLINE" : "CHECKING"}</span>
          <small>{apiReason}</small>
          {apiHealth === "ok" && !judgeMode && (
            <button
              className="button text"
              onClick={() => void startLive().catch((error: unknown) => {
                setNotice(error instanceof Error ? error.message : "Live run failed");
              })}
              type="button"
            >
              Run live backend
            </button>
          )}
        </div>
        <div className="timing-facts">
          <span><small>CONTROLLER EVENT SPAN</small><strong>{controllerRuntime}</strong></span>
          <span><small>NARRATED REPLAY DURATION</small><strong>15.0s</strong></span>
          <span aria-live="polite"><small>PLAYBACK</small><strong>{playbackState}</strong></span>
        </div>
      </section>}

      {judgeMode && experienceView === "AUDIT" && (
        <section className="judge-cockpit" aria-labelledby="judge-cockpit-title">
          <div className="cockpit-lead">
            <span className="kicker">PUBLIC JUDGE MODE · DETERMINISTIC SYNTHETIC DATA</span>
            <h1 id="judge-cockpit-title">A model succeeded. <em>The science did not.</em></h1>
            <p>
              P-204 jumped from trusted rank <strong>#18</strong> to <strong>#1</strong> after
              187 B042 rows violated the Kelvin / Celsius contract.
            </p>
            <button
              aria-label="Run the 15 second verified replay from the Judge Cockpit"
              className="button primary cockpit-run"
              disabled={integrity === "failed"}
              onClick={() =>
                void playStory().catch((error: unknown) => {
                  setIntegrity("failed");
                  setNotice(error instanceof Error ? error.message : "Replay failed");
                })
              }
              type="button"
            >
              {playing ? "PLAYING VERIFIED REPLAY" : "RUN 15s VERIFIED REPLAY"}
            </button>
          </div>
          <button
            className={`cockpit-card signal-card ${activeStage === 0 ? "stage-current" : ""}`}
            onClick={(event) => openEvidence(rankEvidence, event.currentTarget)}
            type="button"
          >
            <small>SIGNAL · WHY DANGEROUS</small>
            <strong>P-204&nbsp; #18 → #1</strong>
            <span>Pipeline SUCCESS · scientific contract FAILED</span>
          </button>
          <button
            className={`cockpit-card cause-card ${[1, 2].includes(activeStage) ? "stage-current" : ""}`}
            onClick={(event) => openEvidence(unitEvidence, event.currentTarget)}
            type="button"
          >
            <small>ROOT CAUSE · DATAHUB TRACE</small>
            <strong>187 rows · K / °C</strong>
            <span>Field lineage proves 6 affected and 3 preserved assets</span>
          </button>
          <button
            className={`cockpit-card decision-card ${[3, 4].includes(activeStage) ? "stage-current" : ""}`}
            onClick={(event) => openEvidence(impactEvidence, event.currentTarget)}
            type="button"
          >
            <small>DETERMINISTIC CONTROL</small>
            <strong><b>HALT</b> Tg · <i>ALLOW</i> MW</strong>
            <span>LLM investigates; policy alone authorizes control</span>
          </button>
          <button
            className={`cockpit-card recovery-card ${activeStage === 5 ? "stage-current" : ""}`}
            onClick={(event) =>
              openEvidence(
                recoveryEvent?.evidence_ids[0] ?? "stage:verify-recovery",
                event.currentTarget,
                recoveryEvent?.event_id ?? null,
              )
            }
            type="button"
          >
            <small>RECOVERY GATE</small>
            <strong>{playbackState === "COMPLETE" ? "RESOLVED · COMPLETE" : "EVIDENCE BEFORE RESUME"}</strong>
            <span>{controllerRuntime} controller span · 15.0s narrated replay</span>
          </button>
          <button
            aria-label="Open the measured Why DataHub comparison"
            className="cockpit-datahub"
            onClick={(event) =>
              openEvidence(evaluationEvidence.evidence_id, event.currentTarget)
            }
            type="button"
          >
            <strong>WHY DATAHUB</strong>
            <b>EXACT CONE · 3/3 WITH LINEAGE → 0/3 SEARCH-ONLY</b>
            <small>NO DATAHUB · MEASURED ABSTENTION · 0/3</small>
          </button>
        </section>
      )}

      {!judgeMode && <section className="hero-section" aria-labelledby="incident-title">
        <div className="hero-copy">
          <div className="eyebrow"><span>INCIDENT SIGNAL</span><i /> POLYMER R&amp;D · DECISION REPORT</div>
          <h1 id="incident-title">A model succeeded.<br /><em>The science did not.</em></h1>
          <p>
            Candidate P-204 jumped to the top of the selection list while every pipeline
            reported success. SciGuard traced the decision backward through DataHub before
            the morning research meeting.
          </p>
          <div className="hero-meta">
            <EvidenceLink id={rankEvidence} onSelect={openEvidence} />
            <span aria-live="polite">{notice}</span>
          </div>
        </div>
        <div className="rank-shock" aria-label="P-204 rank changed from 18 to 1">
          <div className="shock-label"><span>P-204</span> CANDIDATE RANK</div>
          <div className="sentinel-gate">
            <div><small>SENTINEL SIGNAL</small><strong>{signalEvent ? `${initialScope} assets reviewed` : "Awaiting metadata"}</strong></div>
            <div><small>ESCALATION GATE</small><strong>{escalationEvent ? "DECISION PATH REACHED" : "PENDING"}</strong></div>
          </div>
          <div className="rank-row">
            <div className="rank old"><small>TRUSTED</small><strong>#18</strong></div>
            <div className="rank-arrow"><span>→</span><small>+17 positions</small></div>
            <div className="rank new"><small>CURRENT</small><strong>#1</strong></div>
          </div>
          <div className="pipeline-success">
            <span className="success-icon">✓</span>
            <div><small>PIPELINE STATUS</small><strong>SUCCESS</strong></div>
            <span className="contradiction">SCIENTIFIC CONTRACT FAILED</span>
          </div>
        </div>
      </section>}

      {!judgeMode && <section className="eligibility-strip" aria-label="DataHub qualification proof">
        <div>
          <span className="kicker datahub-blue">WHY DATAHUB · REQUIRED COMPONENT</span>
          <strong>DataHub MCP Server supplies contract, schema, ownership, and directed lineage context.</strong>
        </div>
        <p>
          Those reads determine whether the signal reaches a decision path; DataHub field lineage then
          separates the Tg HALT cone from the molecular-weight ALLOW cone. This recorded replay used
          <b> DATAHUB_SDK</b>; the real MCP read path is opt-in and uses an explicit SDK fallback only
          where today&apos;s MCP tools do not expose fine-grained lineage or writes.
        </p>
        <EvidenceLink id={dataHubCapabilityEvidence.evidence_id} onSelect={openEvidence} />
      </section>}

      {experienceView !== "BRIEF" && <nav className="story-rail" aria-label="Six event-driven investigation stages">
        {JUDGE_STAGES.map((stage, index) => (
          <button
            aria-current={activeStage === index ? "step" : undefined}
            aria-label={`${stage.label}: ${stage.purpose}`}
            className={`beat ${activeStage === index ? "active" : ""} ${displayedFocusedStage === index ? "focused" : ""}`}
            key={stage.id}
            onClick={(event) => inspectStage(index, event.currentTarget)}
            type="button"
          >
            <span>{String(index + 1).padStart(2, "0")}</span><strong>{stage.label}</strong>
          </button>
        ))}
        <div className="playback-actions">
          <span className={`playback-state state-${playbackState.toLowerCase()}`} aria-live="polite">
            {playbackState}
          </span>
        </div>
        <span className="sr-only" aria-live="polite" aria-atomic="true">
          Stage {activeStage + 1} of 6: {JUDGE_STAGES[activeStage].label}. Playback {playbackState}.
        </span>
      </nav>}

      {experienceView !== "BRIEF" && <section className="operations-grid">
        <article className="panel timeline-panel">
          <div className="panel-heading">
            <div><span className="kicker">AGENT TIMELINE</span><h2>Verified actions</h2></div>
            <span className="event-counter mono">{visibleEvents.length}/{events.length}</span>
          </div>
          <div className="hypothesis-stack">
            {["H1", "H2", "H3"].map((id, index) => {
              const proposal = proposed[index];
              const resolution = resolvedById.get(id);
              const status = stringValue(resolution?.payload.status, proposal ? "PROPOSED" : "PENDING");
              return (
                <div className="hypothesis" key={id}>
                  <span className="hypothesis-id">{id}</span>
                  <div><strong>{proposal ? proposal.summary.replace(`${id}: `, "") : "Awaiting hypothesis"}</strong><StatusMark status={status} /></div>
                </div>
              );
            })}
          </div>
          <div className="timeline-list">
            {visibleEvents.slice(-10).map((event) => (
              <div className={`timeline-event event-${event.event_type.toLowerCase()}`} key={event.event_id}>
                <div className="actor-glyph" aria-hidden="true">{actorGlyphs[event.actor] ?? "•"}</div>
                <div className="event-copy">
                  <div className="event-meta"><strong>{actorLabels[event.actor] ?? event.actor}</strong><span className="mono">#{String(event.sequence).padStart(2, "0")}</span></div>
                  <p>{event.summary}</p>
                  <div className="event-evidence">
                    {event.evidence_ids.slice(0, 2).map((id) => <EvidenceLink id={id} key={id} onSelect={(evidenceId, trigger) => openEvidence(evidenceId, trigger, event.event_id)} />)}
                  </div>
                </div>
              </div>
            ))}
            {!visibleEvents.length && <div className="empty-state">Waiting for the first immutable event.</div>}
          </div>
        </article>

        <article className="panel graph-panel">
          <div className="panel-heading">
            <div><span className="kicker datahub-blue">DATAHUB IMPACT GRAPH</span><h2>Field-level blast radius</h2></div>
            <EvidenceLink id={impactEvidence} onSelect={openEvidence} />
          </div>
          <div className="lineage-legend">
            <span><i className="legend-critical" /> affected / halted</span>
            <span><i className="legend-healthy" /> preserved / allowed</span>
            <span><i className="legend-datahub" /> DataHub context</span>
          </div>
          <div className="lineage-map">
            <div className={`lineage-node source ${nodeClass("instrument_batch_B042")}`}>
              <small>SOURCE BATCH</small><strong>B042 · DSC-07</strong><span>firmware v4.2</span>
            </div>
            <div className="flow-arrow critical-flow"><span>tg_value</span></div>
            <div className={`lineage-node ${nodeClass("raw_polymer_experiments")}`}>
              <small>DATASET</small><strong>raw polymer experiments</strong><span>owner · lab experimentalist</span>
            </div>
            <div className="flow-arrow critical-flow"><span>tg_value → tg_degC</span></div>
            <div className={`lineage-node ${nodeClass("cleaned_polymer_dataset")}`}>
              <small>DATASET</small><strong>cleaned polymer dataset</strong><span>field lineage split</span>
            </div>
            <div className="branch-split"><span>FIELD LINEAGE DECISION</span></div>
            <div className="lineage-branches">
              <div className="branch critical-branch">
                <div className="branch-title"><span>TAINTED Tg PATH</span><StatusMark status={impactEvent ? "HALT" : "PENDING"} /></div>
                {["tg_feature_table", "tg_prediction_model", "candidate_ranking_report"].map((name) => (
                  <button className={`lineage-node compact ${nodeClass(name)}`} onClick={(event) => openEvidence(assetReceiptId(name), event.currentTarget, impactEvent?.event_id ?? null)} key={name} type="button">
                    <small>{name.includes("model") ? "MODEL" : name.includes("report") ? "DECISION REPORT" : "FEATURE TABLE"}</small>
                    <strong>{formatName(name)}</strong><span>View public DataHub evidence receipt</span>
                  </button>
                ))}
              </div>
              <div className="branch healthy-branch">
                <div className="branch-title"><span>PRESERVED MW PATH</span><StatusMark status={impactEvent ? "ALLOW" : "PENDING"} /></div>
                {["molecular_weight_feature_table", "durability_model", "formulation_report"].map((name) => (
                  <button className={`lineage-node compact ${nodeClass(name)}`} onClick={(event) => openEvidence(assetReceiptId(name), event.currentTarget, impactEvent?.event_id ?? null)} key={name} type="button">
                    <small>{name.includes("model") ? "MODEL" : name.includes("report") ? "REPORT" : "FEATURE TABLE"}</small>
                    <strong>{formatName(name)}</strong><span>View public DataHub evidence receipt</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
          <div className="impact-footer">
            <div><strong>{signalEvent ? initialScope : "—"}</strong><span>initial review scope</span></div>
            <div><strong>{impactEvent ? affected.size : "—"}</strong><span>affected assets</span></div>
            <div><strong>{impactEvent ? unaffected.size : "—"}</strong><span>preserved assets</span></div>
            <div><strong>1 field</strong><span>controls the split</span></div>
          </div>
        </article>

        <aside className="panel evidence-panel">
          <div className="panel-heading">
            <div><span className="kicker">EVIDENCE BOARD</span><h2>Observed, not inferred</h2></div>
            <span className="integrity-chip">SHA-256</span>
          </div>
          <div className="evidence-metrics">
            <button onClick={(event) => openEvidence(unitEvidence, event.currentTarget)} type="button"><small>UNIT VIOLATIONS</small><strong>{evidence.has(unitEvidence) ? "187" : "—"}</strong><span>B042 rows · K vs °C</span></button>
            <button onClick={(event) => openEvidence(unitEvidence, event.currentTarget)} type="button"><small>FIRMWARE</small><strong>{evidence.has(unitEvidence) ? "v4.2" : "—"}</strong><span>trusted release · v4.1</span></button>
            <button onClick={(event) => openEvidence(modelEvidence, event.currentTarget)} type="button"><small>MODEL DRIFT</small><strong>{evidence.has(modelEvidence) ? "NONE" : "—"}</strong><span>tg-gbr-v3 unchanged</span></button>
            <button onClick={(event) => openEvidence(experimentEvidence, event.currentTarget)} type="button"><small>TRUE Tg DELTA</small><strong>{evidence.has(experimentEvidence) ? "0.0°" : "—"}</strong><span>after correct conversion</span></button>
          </div>
          <div className="selected-evidence" aria-live="polite">
            <div className="evidence-type"><span>OBSERVED FACT</span><i>{selectedRecord?.source ?? "PENDING"}</i></div>
            <h3>{selectedRecord?.summary ?? "Select an evidence reference"}</h3>
            <code>{selectedRecord?.evidence_id ?? "evidence:pending"}</code>
            {localDataHubHref && (
              <a className="local-datahub-link" href={localDataHubHref} rel="noreferrer" target="_blank">
                Open local DataHub · local deployment only
              </a>
            )}
            <div className="payload-grid">
              {selectedRecord && Object.entries(selectedRecord.payload).slice(0, 6).map(([key, value]) => (
                <div key={key}><span>{formatName(key)}</span><strong>{Array.isArray(value) ? value.join(", ") : typeof value === "object" ? "verified object" : String(value)}</strong></div>
              ))}
            </div>
          </div>
          <div className="integrity-proof">
            <span>REPLAY INTEGRITY</span>
            <code>{manifest?.events_sha256?.slice(0, 24) ?? "pending"}…</code>
            <small>
              {integrity.toUpperCase()} · {manifest?.event_count ?? 0} events · contiguous · unique IDs
            </small>
          </div>
        </aside>
      </section>}

      {experienceView !== "BRIEF" && (repairEvent || repairOverride) && (
        <section className="repair-studio panel" aria-labelledby="repair-studio-title">
          <div className="repair-heading">
            <div>
              <span className="kicker">PROOF-CARRYING REPAIR</span>
              <h2 id="repair-studio-title">{stringValue(repairPayload.title, "Reviewable repair bundle")}</h2>
              <p>
                Every proposed change, test, rollback step, and approval gate is linked to
                validated incident evidence. Local commits and remote pull requests are reported
                as different action types, so a local receipt is never presented as a GitHub PR.
              </p>
              {stringValue(linkedCapture.capture_type) && (
                <small className="linked-capture-note">
                  CANONICAL SINGLE RUN · {stringValue(linkedCapture.capture_type)} · Dataset
                  lineage, native ML context, exact repair revision, application, and recovery
                  all share this incident ID and are bound to the live DataHub read-back.
                </small>
              )}
            </div>
            <div className="repair-heading-state">
              <StatusMark status={repairStatus} />
              {stringValue(changeReceipt.commit_sha) && (
                <code>{stringValue(changeReceipt.commit_sha).slice(0, 12)}</code>
              )}
              {stringValue(changeReceipt.remote_url) && (
                <a
                  className="remote-action-link"
                  href={stringValue(changeReceipt.remote_url)}
                  rel="noreferrer"
                  target="_blank"
                >
                  OPEN PULL REQUEST ↗
                </a>
              )}
            </div>
          </div>
          <div className="repair-receipt-strip">
            <div className={stringValue(changeReceipt.commit_sha) ? "complete" : ""}>
              <span>01</span><small>CHANGE</small>
              <strong>{stringValue(changeReceipt.commit_sha) ? "COMMITTED" : "READY"}</strong>
            </div>
            <i />
            <div className={stringValue(verificationReceipt.receipt_id) ? "complete" : ""}>
              <span>02</span><small>VERIFY</small>
              <strong>{stringValue(verificationReceipt.status, "LOCKED")}</strong>
            </div>
            <i />
            <div className={stringValue(approvalReceipt.receipt_id) ? "complete" : ""}>
              <span>03</span><small>APPROVE</small>
              <strong>{stringValue(repairApproval.status, "REQUIRED")}</strong>
            </div>
            <i />
            <div className={stringValue(applicationReceipt.receipt_id) ? "complete" : ""}>
              <span>04</span><small>APPLY</small>
              <strong>{stringValue(applicationReceipt.status, "LOCKED")}</strong>
            </div>
            <i />
            <div className={resumeAllowed ? "complete" : ""}>
              <span>05</span><small>RECOVER</small>
              <strong>{resumeAllowed ? "AUTHORIZED" : "LOCKED"}</strong>
            </div>
          </div>
          {nativeMLContext.length > 0 && (
            <div className="native-context-strip">
              <span className="repair-label">DATAHUB NATIVE PRODUCTION ML CONTEXT</span>
              {nativeMLContext.map((context) => (
                <div key={stringValue(context.native_model_urn)}>
                  <span className={booleanValue(context.affected) ? "native-risk" : "native-safe"}>
                    {booleanValue(context.affected) ? "AFFECTED" : "PRESERVED"}
                  </span>
                  <strong>
                    {stringValue(context.model_name)} · {stringValue(context.model_version)}
                  </strong>
                  <small>
                    {Array.isArray(context.feature_urns) ? context.feature_urns.length : 0} features ·{" "}
                    {Array.isArray(context.training_job_urns)
                      ? context.training_job_urns.length
                      : 0}{" "}
                    training ·{" "}
                    {Array.isArray(context.deployment_context)
                      ? context.deployment_context.length
                      : 0}{" "}
                    deployment ·{" "}
                    {Array.isArray(context.inference_job_urns)
                      ? context.inference_job_urns.length
                      : 0}{" "}
                    inference · {stringValue(context.criticality)}
                  </small>
                  <code>{stringValue(context.native_model_urn)}</code>
                </div>
              ))}
            </div>
          )}
          {(stringValue(repairPayload.datahub_incident_urn) ||
            stringValue(repairPayload.datahub_decision_log_urn)) && (
            <div className="catalog-lifecycle-strip">
              <span className="repair-label">
                DATAHUB WRITE-BACK LIFECYCLE
                {dataHubEntityCount > 0 &&
                  ` · ${dataHubEntityCount} NATIVE ENTITIES READ BACK ON ${dataHubServerVersion}`}
              </span>
              <div>
                <small>NATIVE INCIDENT</small>
                <strong>
                  {dataHubLiveReceipt
                    ? `${stringValue(dataHubIncidentLifecycle.readback_state)} · ${stringValue(dataHubIncidentLifecycle.readback_stage)}`
                    : repairStatus === "APPROVED"
                      ? "ACTIVE · REVIEWED"
                      : "ACTIVE"}
                </strong>
                <code>{stringValue(repairPayload.datahub_incident_urn)}</code>
              </div>
              <div>
                <small>NATIVE DECISION LOG</small>
                <strong>
                  {stringValue(dataHubDecisionLogLifecycle.readback_state, "PUBLISHED")} ·{" "}
                  {dataHubLiveReceipt
                    ? `${numberValue(dataHubDecisionLogLifecycle.related_asset_count)} ASSETS READ BACK`
                    : "LINKED TO DECISION CONE"}
                </strong>
                <code>{stringValue(repairPayload.datahub_decision_log_urn)}</code>
              </div>
            </div>
          )}
          {verificationReceipts.length > 0 && (
            <div className="counterfactual-lab">
              <div className="counterfactual-intro">
                <span className="repair-label">COUNTERFACTUAL VERIFICATION LAB</span>
                <strong>Did the repair restore the decision without disturbing safe work?</strong>
                <small>Executed test receipts · not an animated prediction</small>
              </div>
              <div className="counterfactual-ranks" aria-label="P-204 rank before contamination, after contamination, and after the verified repair">
                <div>
                  <small>TRUSTED BASELINE</small>
                  <strong>#18</strong>
                  <span>scientifically plausible</span>
                </div>
                <i>→</i>
                <div className="unsafe">
                  <small>MIXED-UNIT OUTPUT</small>
                  <strong>#1</strong>
                  <span>publication blocked</span>
                </div>
                <i>→</i>
                <div className="restored">
                  <small>VERIFIED REPAIR</small>
                  <strong>#18</strong>
                  <span>trusted rank restored</span>
                </div>
              </div>
              <div className="counterfactual-proofs">
                {[
                  ["unit_contract", "K = °C after normalization"],
                  ["candidate_ranking_stability", "P-204 rank #1 → #18"],
                  ["safe_branch_preservation", "MW output digest unchanged"],
                ].map(([checkId, label]) => {
                  const receipt = verificationById.get(checkId);
                  return (
                    <div key={checkId}>
                      <span>{stringValue(receipt?.status) === "PASS" ? "✓" : "○"}</span>
                      <strong>{label}</strong>
                      <code>
                        {stringValue(
                          receipt?.result_sha256,
                          stringValue(receipt?.output_sha256),
                        ).slice(0, 12)}
                        …
                      </code>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
          <div className="repair-layout">
            <div className="repair-artifacts">
              <span className="repair-label">BUNDLE ARTIFACTS</span>
              {repairArtifacts.map((artifact) => (
                <div key={stringValue(artifact.artifact_id)}>
                  <span>{stringValue(artifact.kind)}</span>
                  <strong>{stringValue(artifact.path)}</strong>
                  <small>{stringValue(artifact.description)}</small>
                </div>
              ))}
            </div>
            <div className="repair-diff">
              <div>
                <span className="repair-label">PROPOSED PATCH</span>
                <code>{stringValue(repairPatch?.content_sha256).slice(0, 14)}…</code>
              </div>
              <pre>{stringValue(repairPatch?.content, "Patch evidence is not visible at this replay position.")}</pre>
            </div>
            <div className="repair-verification">
              <span className="repair-label">VERIFICATION &amp; AUTHORITY</span>
              {repairChecks.map((check) => {
                const observed = verificationById.get(stringValue(check.check_id));
                const status = stringValue(observed?.status, "WAITING");
                return (
                <div
                  className={`repair-check ${status === "PASS" ? "passed" : ""}`}
                  key={stringValue(check.check_id)}
                >
                  <span>{status === "PASS" ? "✓" : "○"}</span>
                  <div>
                    <strong>{stringValue(check.name)} · {status}</strong>
                    <small>
                      {status === "PASS"
                        ? `exit ${numberValue(observed?.exit_code, -1)} · ${numberValue(observed?.duration_ms)}ms · receipt ${stringValue(observed?.result_sha256, stringValue(observed?.output_sha256)).slice(0, 10)}…`
                        : stringValue(check.expected_result)}
                    </small>
                    {stringValue(observed?.details_url) && (
                      <a
                        className="remote-check-link"
                        href={stringValue(observed?.details_url)}
                        rel="noreferrer"
                        target="_blank"
                      >
                        OPEN HOSTED CHECK ↗
                      </a>
                    )}
                  </div>
                </div>
                );
              })}
              <div className="repair-approval">
                <small>HUMAN APPROVAL</small>
                <strong>{formatName(stringValue(repairApproval.status, "REQUIRED"))}</strong>
                <span>{stringValue(repairApproval.approver_urn, "DataHub owner pending")}</span>
                {stringValue(approvalReceipt.identity_assurance) && (
                  <span>
                    {stringValue(approvalReceipt.identity_assurance)} · production authorization{" "}
                    {booleanValue(approvalReceipt.production_authorized) ? "YES" : "NO"}
                  </span>
                )}
              </div>
              <div className="repair-application">
                <small>EXACT-REVISION APPLICATION</small>
                <strong>{stringValue(applicationReceipt.status, "NOT APPLIED")}</strong>
                <span>
                  {stringValue(
                    applicationReceipt.target_environment,
                    "Synthetic staging is locked until approval",
                  )}
                </span>
                {stringValue(applicationReceipt.deployment_id) && (
                  <code>
                    {stringValue(applicationReceipt.deployment_id)} · tree{" "}
                    {stringValue(applicationReceipt.source_tree_sha256).slice(0, 12)}…
                  </code>
                )}
                {stringValue(applicationReceipt.receipt_id) && (
                  <span>
                    production authorization{" "}
                    {booleanValue(applicationReceipt.production_authorized) ? "YES" : "NO"}
                  </span>
                )}
              </div>
              {canOperateRepair && (
                <div className="repair-actions">
                  <button
                    className="button primary"
                    disabled={repairStatus !== "PROPOSED" || repairAction !== "idle"}
                    onClick={() => void runRepairAction("publish").catch((error: unknown) => {
                      setNotice(error instanceof Error ? error.message : "Repair publication failed");
                    })}
                    type="button"
                  >
                    {repairAction === "publish"
                      ? "PUBLISHING…"
                      : stringValue(repairPayload.target_repository).startsWith(
                            "https://github.com/",
                          )
                        ? "CREATE GITHUB PR"
                        : "CREATE REAL COMMIT"}
                  </button>
                  <button
                    className="button ghost"
                    disabled={repairStatus !== "PUBLISHED" || repairAction !== "idle"}
                    onClick={() => void runRepairAction("verify").catch((error: unknown) => {
                      setNotice(error instanceof Error ? error.message : "Repair verification failed");
                    })}
                    type="button"
                  >
                    {repairAction === "verify" ? "RUNNING TESTS…" : "VERIFY COMMIT"}
                  </button>
                  <button
                    className="button ghost"
                    disabled={repairStatus !== "VERIFIED" || repairAction !== "idle"}
                    onClick={() => void runRepairAction("approval").catch((error: unknown) => {
                      setNotice(error instanceof Error ? error.message : "Approval failed");
                    })}
                    type="button"
                  >
                    {repairAction === "approval" ? "SIGNING…" : "APPROVE AS OWNER"}
                  </button>
                  <button
                    className="button ghost"
                    disabled={repairStatus !== "APPROVED" || repairAction !== "idle"}
                    onClick={() => void runRepairAction("apply").catch((error: unknown) => {
                      setNotice(error instanceof Error ? error.message : "Repair application failed");
                    })}
                    type="button"
                  >
                    {repairAction === "apply"
                      ? "APPLYING…"
                      : "APPLY TO SYNTHETIC STAGING"}
                  </button>
                </div>
              )}
            </div>
          </div>
        </section>
      )}

      {experienceView !== "BRIEF" && <section className="control-deck">
        <article className="panel policy-panel">
          <div className="panel-heading"><div><span className="kicker">DETERMINISTIC POLICY</span><h2>Selective containment</h2></div><span className="rule-chip">YAML RULES</span></div>
          <div className="policy-strip">
            <div className="policy-decision halt"><span>!</span><div><small>HALT</small><strong>{policyEvents.length ? policyCount("HALT") : "—"}</strong><p>source · model · ranking</p></div></div>
            <div className="policy-decision warn"><span>△</span><div><small>WARN</small><strong>{policyEvents.length ? policyCount("WARN") : "—"}</strong><p>affected data surfaces</p></div></div>
            <div className="policy-decision allow"><span>✓</span><div><small>ALLOW</small><strong>{policyEvents.length ? policyCount("ALLOW") : "—"}</strong><p>molecular-weight branch</p></div></div>
          </div>
          <p className="policy-note">Policy decision, catalog status, and enforcement action remain separate. No LLM output can authorize HALT, ALLOW, or RESUME.</p>
        </article>

        <article className="panel console-panel">
          <div className="panel-heading"><div><span className="kicker">ENFORCEMENT CONSOLE</span><h2>Real process outcomes</h2></div><span className="mono">LOCAL CONTROLLER</span></div>
          <div className="console-window">
            <div className="console-bar"><i /><i /><i /><span>sciguard / publish guard</span></div>
            <div className="console-line"><span>$</span> publish candidate_ranking_report</div>
            <div className={blockedEvent ? "console-result blocked" : "console-result pending"}><strong>{blockedEvent ? "BLOCKED" : "AWAITING EVENT"}</strong><span>exit {blockedEvent ? numberValue(blockedEvent.payload.exit_code) : "—"}</span><small>{blockedEvent ? "target not created" : "no UI simulation"}</small></div>
            <div className="console-line"><span>$</span> publish formulation_report</div>
            <div className={allowedEvent ? "console-result allowed" : "console-result pending"}><strong>{allowedEvent ? "ALLOWED" : "AWAITING EVENT"}</strong><span>exit {allowedEvent ? numberValue(allowedEvent.payload.exit_code) : "—"}</span><small>{allowedEvent ? "target created" : "waiting for safe branch proof"}</small></div>
          </div>
          {blockedEvent?.evidence_ids[0] && <EvidenceLink id={blockedEvent.evidence_ids[0]} onSelect={(id, trigger) => openEvidence(id, trigger, blockedEvent.event_id)} />}
        </article>

        <article className="panel recovery-panel">
          <div className="panel-heading"><div><span className="kicker">RECOVERY GATE</span><h2>Evidence before resume</h2></div><StatusMark status={resumeAllowed ? "RESOLVED" : recoveryEvent ? "LOCKED" : "PENDING"} /></div>
          <div className="recovery-list">
            {recoveryCheckIds.map((check) => {
              const known = Boolean(recoveryEvent);
              const failed = failedChecks.has(check);
              const passed = known && !failed;
              return <div className={failed ? "recovery-check failed" : passed ? "recovery-check passed" : "recovery-check"} key={check}><span>{failed ? "×" : passed ? "✓" : "○"}</span><strong>{formatName(check)}</strong><small>{failed ? "FAIL" : passed ? "PASS" : "WAITING"}</small></div>;
            })}
          </div>
          <div className="recovery-footer"><div><small>CLEAN RUNS</small><strong>{cleanRunCount} / 2</strong></div><div><small>RESUME</small><strong>{resumeAllowed ? "AUTHORIZED" : "LOCKED"}</strong></div></div>
          {canOperateRepair && repairStatus === "APPLIED" && !resumeAllowed && (
            <button
              className="button primary recovery-action"
              disabled={repairAction !== "idle"}
              onClick={() => void runRepairAction("recover").catch((error: unknown) => {
                setNotice(error instanceof Error ? error.message : "Recovery verification failed");
              })}
              type="button"
            >
              {repairAction === "recover"
                ? "RE-RUNNING COMMIT-BOUND CHECKS…"
                : `RUN CLEAN RECOVERY CHECK ${Math.min(cleanRunCount + 1, 2)} / 2`}
            </button>
          )}
          <p>Frontend state cannot unlock recovery. This surface only renders integrity-checked event results from the deterministic controller.</p>
        </article>
      </section>}

      {experienceView === "AUDIT" && <section className="evaluation-theatre panel">
        <div className="evaluation-intro">
          <span className="kicker">WHY DATAHUB · MEASURED ABLATION</span>
          <h2>Directed lineage changes the decision boundary.</h2>
          <p>{DATAHUB_DECISION_EXPLANATION}</p>
          <small>{DATAHUB_CAPABILITY_BOUNDARY}</small>
          <EvidenceLink id={evaluationEvidence.evidence_id} onSelect={openEvidence} />
        </div>
        <div className="evaluation-modes">
          {WHY_DATAHUB_RESULTS.map((result, index) => (
            <button
              className={`evaluation-card ${result.id === "full-lineage" ? "full" : result.id === "search-only" ? "search" : "unavailable"}`}
              key={result.id}
              onClick={(event) => openEvidence(evaluationEvidence.evidence_id, event.currentTarget)}
              type="button"
            >
              <div className="mode-title"><span>0{index + 1}</span><strong>{result.label}</strong></div>
              <div className="metric-grid">
                <div><strong>{result.precision}</strong><span>precision</span></div>
                <div><strong>{result.recall}</strong><span>recall</span></div>
                <div><strong>{result.f1}</strong><span>F1</span></div>
                <div><strong>{result.exactCone}</strong><span>exact cone</span></div>
              </div>
              <p>
                {result.id === "no-datahub"
                  ? "Zero catalog calls. The agent abstains instead of inventing dependencies."
                  : result.id === "search-only"
                    ? "Name similarity without lineage direction."
                    : "Field lineage + owners + governance context."}
              </p>
              <StatusMark status={result.status} />
            </button>
          ))}
        </div>
      </section>}

      <footer className="site-footer">
        <div><span className="brand-mini">SG</span><strong>Trust the decision because you can inspect the evidence.</strong></div>
        <div className="footer-meta"><span>{latestEvent ? `Latest · ${latestEvent.event_type}` : "Awaiting events"}</span><span>All demo data is deterministic and synthetic</span><span>DataHub-powered</span></div>
      </footer>

      {drawerOpen && (
        <div className="evidence-drawer-layer">
          <button
            aria-label="Close evidence drawer"
            className="drawer-backdrop"
            onClick={closeDrawer}
            type="button"
          />
          <aside
            aria-labelledby="evidence-drawer-title"
            aria-modal="true"
            className="evidence-drawer"
            ref={drawerRef}
            role="dialog"
          >
            <div className="drawer-header">
              <div>
                <span className="kicker">EVIDENCE CENTER · PUBLIC RECEIPT</span>
                <h2 id="evidence-drawer-title">
                  {drawerRecord?.summary ?? drawerEvent?.summary ?? drawerStage.purpose}
                </h2>
              </div>
              <button
                aria-label="Close evidence drawer and return focus"
                className="drawer-close"
                onClick={closeDrawer}
                ref={drawerCloseRef}
                type="button"
              >
                ×
              </button>
            </div>
            <nav
              aria-label="Evidence Center quick access"
              className="drawer-quick-access"
            >
              <button
                aria-pressed={
                  selectedEvidence === DATAHUB_LIVE_RECEIPT_EVIDENCE_ID
                }
                className={
                  selectedEvidence === DATAHUB_LIVE_RECEIPT_EVIDENCE_ID
                    ? "active"
                    : ""
                }
                disabled={!dataHubLiveReceipt}
                onClick={(event) =>
                  openEvidence(
                    DATAHUB_LIVE_RECEIPT_EVIDENCE_ID,
                    event.currentTarget,
                  )
                }
                type="button"
              >
                <small>01</small>
                <strong>DATAHUB RECEIPT</strong>
                <span>{dataHubLiveReceipt ? "LIVE READ-BACK" : "LOADING"}</span>
              </button>
              <button
                aria-pressed={
                  selectedEvidence === evaluationEvidence.evidence_id
                }
                className={
                  selectedEvidence === evaluationEvidence.evidence_id
                    ? "active"
                    : ""
                }
                onClick={(event) =>
                  openEvidence(
                    evaluationEvidence.evidence_id,
                    event.currentTarget,
                  )
                }
                type="button"
              >
                <small>02</small>
                <strong>EVALUATION REPORT</strong>
                <span>13 SCENARIOS · PASS</span>
              </button>
              <button
                aria-pressed={selectedEvidence === GITHUB_LIVE_EVIDENCE_ID}
                className={
                  selectedEvidence === GITHUB_LIVE_EVIDENCE_ID ? "active" : ""
                }
                disabled={!githubLiveEvidence}
                onClick={(event) =>
                  openEvidence(GITHUB_LIVE_EVIDENCE_ID, event.currentTarget)
                }
                type="button"
              >
                <small>03</small>
                <strong>GITHUB PR + CI</strong>
                <span>{githubLiveEvidence ? "EXACT SHA · PASS" : "LOADING"}</span>
              </button>
            </nav>
            <div className="drawer-stage">
              <span>
                {drawerIsCrossRunEvaluation
                  ? "CONTROLLED BENCHMARK"
                  : drawerIsDataHubReceipt
                    ? "LIVE READ-BACK"
                    : drawerIsGitHubEvidence
                      ? "REMOTE ACTION PROOF"
                    : `STAGE ${drawerResolvedStageIndex + 1} / 6`}
              </span>
              <strong>
                {drawerIsCrossRunEvaluation
                  ? "WHY DATAHUB"
                  : drawerIsDataHubReceipt
                    ? "DATAHUB CLOSURE"
                    : drawerIsGitHubEvidence
                      ? "GITHUB VERIFIED"
                    : drawerStage.label}
              </strong>
            </div>
            <dl className="drawer-facts">
              <div><dt>Evidence type</dt><dd>{drawerRecord?.kind ?? drawerEvent?.event_type ?? "STAGE CONTEXT"}</dd></div>
              <div>
                <dt>{drawerIsCrossRunEvaluation ? "Evaluation scope" : "Incident ID"}</dt>
                <dd>
                  {drawerIsCrossRunEvaluation
                    ? "13 labelled scenarios / 3 lineage cones"
                    : drawerEvent?.incident_id ??
                      manifest?.incident_id ??
                      "Not present in this evidence"}
                </dd>
              </div>
              <div>
                <dt>Immutable event ID / sequence</dt>
                <dd>
                  {drawerIsCrossRunEvaluation
                    ? "Not applicable · gated evaluation artifact"
                    : drawerEvent
                      ? `${drawerEvent.event_id} / ${drawerEvent.sequence + 1} of ${manifest?.event_count ?? 38}`
                      : "Not visible at the current replay position"}
                </dd>
              </div>
              <div><dt>DataHub URN</dt><dd className="drawer-urn">{drawerUrn}</dd></div>
              <div><dt>Affected field</dt><dd>{drawerField}</dd></div>
              <div><dt>Downstream impact</dt><dd>{downstreamImpact}</dd></div>
              <div><dt>Policy rule</dt><dd>{policyRule}</dd></div>
              <div><dt>Enforcement action</dt><dd>{enforcementAction}</dd></div>
              <div>
                <dt>Provenance / backend</dt>
                <dd>{drawerRecord?.source ?? drawerEvent?.actor ?? "Recorded stage context"} · {manifest?.datahub_backend ?? "pending"}</dd>
              </div>
            </dl>
            {localDataHubHref && (
              <a className="local-datahub-link" href={localDataHubHref} rel="noreferrer" target="_blank">
                Open local DataHub · local deployment only
              </a>
            )}
            {selectedEvidence === evaluationEvidence.evidence_id && (
              <div className="drawer-ablation" aria-label="Measured Why DataHub comparison">
                {WHY_DATAHUB_RESULTS.map((result) => (
                  <div key={result.id}>
                    <strong>{result.label}</strong>
                    <span>
                      P {result.precision} · R {result.recall} · F1 {result.f1} · exact cone {result.exactCone}
                    </span>
                  </div>
                ))}
                <p>{DATAHUB_CAPABILITY_BOUNDARY}</p>
              </div>
            )}
            {drawerIsGitHubEvidence && (
              <div
                className="drawer-github-proof"
                aria-label="GitHub pull request, hosted checks, and identity boundary"
              >
                <div>
                  <strong>REAL PULL REQUEST · OPEN</strong>
                  <code>{stringValue(drawerGitHubPullRequest.head_sha)}</code>
                  <a
                    href={stringValue(drawerGitHubPullRequest.url)}
                    rel="noreferrer"
                    target="_blank"
                  >
                    OPEN PUBLIC PR #{numberValue(drawerGitHubPullRequest.number)} ↗
                  </a>
                </div>
                <div>
                  <strong>HOSTED CHECKS · 3 / 3 PASS</strong>
                  {drawerGitHubChecks.map((check) => (
                    <a
                      href={stringValue(check.details_url)}
                      key={stringValue(check.check_id)}
                      rel="noreferrer"
                      target="_blank"
                    >
                      {formatName(stringValue(check.check_id))} · PASS ↗
                    </a>
                  ))}
                </div>
                <div>
                  <strong>IDENTITY BOUNDARY</strong>
                  <span>
                    {stringValue(drawerGitHubReview.identity_assurance)} · reviewer{" "}
                    {stringValue(drawerGitHubReview.reviewer_login)}
                  </span>
                  <span>Enterprise SSO verified · NO</span>
                  <span>Independent reviewer · NO</span>
                  <span>Production authorization · NO</span>
                  <a
                    href={stringValue(drawerGitHubReview.url)}
                    rel="noreferrer"
                    target="_blank"
                  >
                    OPEN AUTHENTICATED REVIEW ↗
                  </a>
                </div>
                <p>
                  A GitHub-authenticated account created and reviewed the exact
                  revision. This is real remote identity evidence, but it is not
                  misrepresented as independent enterprise SSO/OIDC approval.
                </p>
              </div>
            )}
            <div className="drawer-integrity">
              <span>INTEGRITY VERIFICATION · {integrity.toUpperCase()}</span>
              <code>{manifest?.events_sha256 ?? "pending"}</code>
              <p>
                SHA-256 verifies internal consistency of the packaged replay. It is not a
                digital signature and not proof of origin.
              </p>
            </div>
            <details className="drawer-payload">
              <summary>Raw recorded payload</summary>
              <pre>{JSON.stringify(drawerPayload, null, 2)}</pre>
            </details>
          </aside>
        </div>
      )}
    </main>
  );
}
