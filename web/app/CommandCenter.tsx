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
const SOURCE_REPOSITORY_URL =
  "https://github.com/songjie6816-code/sciguard-autopilot";
const DEMO_VIDEO_URL =
  process.env.NEXT_PUBLIC_SCIGUARD_VIDEO_URL?.trim() ?? "";
type ExperienceView = "BRIEF" | "OPERATE" | "AUDIT";
type JudgePage = "OVERVIEW" | "INCIDENT" | "CONTEXT" | "STUDIO" | "EVIDENCE";

const JUDGE_PAGE_HEADING_IDS: Record<JudgePage, string> = {
  OVERVIEW: "portal-overview-title",
  INCIDENT: "decision-brief-title",
  CONTEXT: "context-page-title",
  STUDIO: "studio-page-title",
  EVIDENCE: "evidence-page-title",
};

const JUDGE_PAGES: Array<{
  id: JudgePage;
  hash: string;
  label: string;
  shortLabel: string;
}> = [
  { id: "OVERVIEW", hash: "overview", label: "Overview", shortLabel: "Overview" },
  { id: "INCIDENT", hash: "incident", label: "The Incident", shortLabel: "Incident" },
  { id: "CONTEXT", hash: "context", label: "DataHub Context", shortLabel: "Context" },
  { id: "STUDIO", hash: "studio", label: "Recovery Studio", shortLabel: "Studio" },
  { id: "EVIDENCE", hash: "evidence", label: "Evidence", shortLabel: "Evidence" },
];

const JUDGE_TOUR_STEPS: Array<{
  page: JudgePage;
  time: string;
  label: string;
  prompt: string;
}> = [
  { page: "OVERVIEW", time: "10s", label: "Incident", prompt: "What failed?" },
  { page: "CONTEXT", time: "30s", label: "Why DataHub", prompt: "Why is lineage essential?" },
  { page: "STUDIO", time: "60s", label: "Delivery", prompt: "Find patch, PR, and CI" },
  { page: "INCIDENT", time: "90s", label: "Safe branch", prompt: "Why did MW continue?" },
  { page: "EVIDENCE", time: "120s", label: "Audit", prompt: "Open writeback and ablation" },
];

const CONTROL_STAGES = [
  {
    label: "SIGNAL",
    title: "Detect the silent change",
    datahub: "Read contract",
    description: "A scientific contract changes while every pipeline stays green.",
  },
  {
    label: "IMPACT",
    title: "Prove the decision cone",
    datahub: "Trace lineage",
    description: "Directed field lineage separates affected decisions from safe work.",
  },
  {
    label: "CONTROL",
    title: "Contain selectively",
    datahub: "Read governance",
    description: "Deterministic policy blocks the unsafe output and preserves independence.",
  },
  {
    label: "REPAIR",
    title: "Deliver a reviewed fix",
    datahub: "Write incident",
    description: "A commit-bound patch, hosted checks, and an owner approval gate carry the proof.",
  },
  {
    label: "RECOVERY",
    title: "Verify before resume",
    datahub: "Publish closure",
    description: "Two clean runs resolve the incident and write new knowledge back.",
  },
];

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
const REPLAY_INTEGRITY_EVIDENCE_ID =
  "replay-integrity:inc-sciguard-b042-unit-contract";

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

function liveSession(): string {
  const storageKey = "sciguard-live-session";
  const existing = window.sessionStorage.getItem(storageKey);
  if (existing) return existing;
  const created = `judge-${globalThis.crypto.randomUUID()}`;
  window.sessionStorage.setItem(storageKey, created);
  return created;
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

function macroStageIndex(technicalStage: number): number {
  if (technicalStage <= 1) return 0;
  if (technicalStage === 2) return 1;
  if (technicalStage === 3) return 2;
  if (technicalStage === 4) return 3;
  return 4;
}

function DecisionControlMap({
  activeIndex,
  complete,
  compact = false,
  onSelect,
}: {
  activeIndex: number;
  complete: boolean;
  compact?: boolean;
  onSelect: (index: number) => void;
}) {
  return (
    <section
      aria-label="SciGuard decision recovery map"
      className={`decision-control-map ${compact ? "is-compact" : ""}`}
    >
      {!compact && (
        <div className="context-spine">
          <div>
            <i aria-hidden="true" />
            <span>DATAHUB CONTEXT GRAPH</span>
          </div>
          <p>
            Contract, lineage, ownership, governance, incidents, and recovery
            knowledge remain connected to every action.
          </p>
        </div>
      )}
      <div className="control-stage-row">
        {CONTROL_STAGES.map((stage, index) => {
          const achieved = index < activeIndex || (complete && index === activeIndex);
          const current = index === activeIndex && !complete;
          return (
            <div className="control-stage-segment" key={stage.label}>
              <button
                aria-current={current ? "step" : undefined}
                aria-label={`${stage.label}: ${stage.title}`}
                className={`${achieved ? "is-complete" : ""} ${current ? "is-current" : ""}`}
                onClick={() => onSelect(index)}
                type="button"
              >
                {!compact && <small>{stage.datahub}</small>}
                <span className="control-stage-icon" aria-hidden="true">
                  {achieved ? "✓" : String(index + 1).padStart(2, "0")}
                </span>
                <strong>{stage.label}</strong>
                {!compact && (
                  <>
                    <b>{stage.title}</b>
                    <em>{stage.description}</em>
                  </>
                )}
              </button>
              {index < CONTROL_STAGES.length - 1 && (
                <i
                  aria-hidden="true"
                  className={`control-connector ${
                    index < activeIndex || complete ? "is-flowing" : ""
                  }`}
                />
              )}
            </div>
          );
        })}
      </div>
      {!compact && (
        <div className="decision-branch-summary">
          <div className="branch-risk">
            <span aria-hidden="true">!</span>
            <p><small>UNSAFE DECISION</small><strong>Candidate ranking blocked</strong></p>
          </div>
          <div className="branch-safe">
            <span aria-hidden="true">✓</span>
            <p><small>INDEPENDENT WORK</small><strong>Formulation analysis preserved</strong></p>
          </div>
        </div>
      )}
    </section>
  );
}

export function CommandCenter({ judgeMode = false }: { judgeMode?: boolean }) {
  const [experienceView, setExperienceView] = useState<ExperienceView>(
    judgeMode ? "BRIEF" : "OPERATE",
  );
  const [judgePage, setJudgePage] = useState<JudgePage>(
    judgeMode ? "OVERVIEW" : "STUDIO",
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
  const [judgeTourActive, setJudgeTourActive] = useState(false);
  const [studioDetailsOpen, setStudioDetailsOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerEventId, setDrawerEventId] = useState<string | null>(null);
  const eventSource = useRef<EventSource | null>(null);
  const liveTimeout = useRef<number | null>(null);
  const drawerRef = useRef<HTMLElement | null>(null);
  const drawerCloseRef = useRef<HTMLButtonElement | null>(null);
  const drawerTriggerRef = useRef<HTMLElement | null>(null);

  const apiBase = useMemo(() => {
    if (CONFIGURED_API_BASE) return CONFIGURED_API_BASE.replace(/\/$/, "");
    if (typeof window !== "undefined" && ["localhost", "127.0.0.1"].includes(window.location.hostname)) {
      return LOCAL_API_BASE;
    }
    return "";
  }, []);

  const navigateJudgePage = useCallback(
    (page: JudgePage, replace = false) => {
      setJudgePage(page);
      setExperienceView(
        page === "STUDIO" ? "OPERATE" : page === "EVIDENCE" ? "AUDIT" : "BRIEF",
      );
      if (typeof window === "undefined" || !judgeMode) return;
      const pageDefinition = JUDGE_PAGES.find((item) => item.id === page);
      const nextHash = `#${pageDefinition?.hash ?? "overview"}`;
      if (window.location.hash !== nextHash) {
        window.history[replace ? "replaceState" : "pushState"](
          { sciguardPage: page },
          "",
          nextHash,
        );
      }
      const reduceMotion = window.matchMedia(
        "(prefers-reduced-motion: reduce)",
      ).matches;
      window.scrollTo({
        top: 0,
        behavior: replace || reduceMotion ? "auto" : "smooth",
      });
      window.requestAnimationFrame(() => {
        document.getElementById(JUDGE_PAGE_HEADING_IDS[page])?.focus({
          preventScroll: true,
        });
      });
    },
    [judgeMode],
  );

  useEffect(() => {
    if (!judgeMode) return;
    const syncPageFromLocation = () => {
      const requestedHash = window.location.hash.replace(/^#/, "").toLowerCase();
      const requestedPage =
        JUDGE_PAGES.find((item) => item.hash === requestedHash)?.id ?? "OVERVIEW";
      setJudgePage(requestedPage);
      setExperienceView(
        requestedPage === "STUDIO"
          ? "OPERATE"
          : requestedPage === "EVIDENCE"
            ? "AUDIT"
            : "BRIEF",
      );
    };
    syncPageFromLocation();
    window.addEventListener("hashchange", syncPageFromLocation);
    window.addEventListener("popstate", syncPageFromLocation);
    return () => {
      window.removeEventListener("hashchange", syncPageFromLocation);
      window.removeEventListener("popstate", syncPageFromLocation);
    };
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
      if (!apiBase) {
        setApiHealth("offline");
        setApiReason("No public live backend is configured for this hosted build.");
      } else {
        void fetch(`${apiBase}/healthz`)
          .then(async (response) => {
            if (!response.ok) throw new Error(`health check returned ${response.status}`);
            const health = (await response.json()) as {
              status?: string;
              capabilities?: {
                live_calculation?: boolean;
                server_sent_events?: boolean;
                isolated_state?: boolean;
                mutating_actions?: boolean;
              };
            };
            if (
              health.status !== "ok" ||
              !health.capabilities?.live_calculation ||
              !health.capabilities.server_sent_events ||
              !health.capabilities.isolated_state ||
              health.capabilities.mutating_actions !== false
            ) {
              throw new Error("the bounded live capability contract is degraded");
            }
            setApiHealth("ok");
            setApiReason(
              "Edge compute and isolated state are healthy · DataHub context uses the verified Module 1 read-back.",
            );
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
      if (liveTimeout.current !== null) window.clearTimeout(liveTimeout.current);
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
    if (liveTimeout.current !== null) window.clearTimeout(liveTimeout.current);
    if (!apiBase) return;
    const source = new EventSource(`${apiBase}/api/runs/${runManifest.incident_id}/events`);
    eventSource.current = source;
    liveTimeout.current = window.setTimeout(() => {
      source.close();
      void loadReplay(false)
        .then(() => {
          setNotice(
            "LIVE TIMED OUT · automatically switched to the verified immutable replay",
          );
        })
        .catch(() => {
          setNotice(
            "LIVE TIMED OUT · verified replay fallback is also unavailable",
          );
        });
    }, 15_000);
    source.addEventListener("sciguard-event", (message) => {
      const frame = JSON.parse((message as MessageEvent).data) as EventFrame;
      setEvents((current) => {
        if (current.some((event) => event.event_id === frame.event.event_id)) return current;
        return [...current, frame.event].sort((a, b) => a.sequence - b.sequence);
      });
      setVisibleCount((count) => count + 1);
    });
    source.addEventListener("sciguard-complete", (message) => {
      const completed = JSON.parse((message as MessageEvent).data) as {
        manifest: RunManifest;
      };
      setManifest(completed.manifest);
      setNotice(
        "LIVE CONTROL PASS · calculation, DataHub context, policy, repair plan, and enforcement verified · recovery remains gated",
      );
      if (liveTimeout.current !== null) {
        window.clearTimeout(liveTimeout.current);
        liveTimeout.current = null;
      }
      source.close();
    });
    source.addEventListener("sciguard-error", () => {
      source.close();
      if (liveTimeout.current !== null) {
        window.clearTimeout(liveTimeout.current);
        liveTimeout.current = null;
      }
      void loadReplay(false).then(() => {
        setNotice(
          "LIVE BACKEND INTERRUPTED · automatically switched to the verified immutable replay",
        );
      });
    });
    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED) source.close();
    };
  }, [apiBase, loadReplay]);

  const startLive = useCallback(async () => {
    setNotice("Requesting an isolated live scientific calculation…");
    if (!apiBase) throw new Error(apiReason);
    const idempotencyKey = `judge-${globalThis.crypto.randomUUID()}`;
    const response = await fetch(`${apiBase}/api/runs`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
        "X-SciGuard-Session": liveSession(),
      },
      body: JSON.stringify({ scenario: "KELVIN_CELSIUS_B042" }),
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(`Live run unavailable: ${detail}`);
    }
    const view = (await response.json()) as { manifest: RunManifest };
    setManifest(view.manifest);
    setEvents([]);
    setRepairOverride(null);
    setVisibleCount(0);
    setMode("LIVE");
    setPlaying(false);
    setNotice(
      "LIVE · new events are arriving from edge compute; DataHub context is a verified read-back snapshot",
    );
    connectLiveStream(view.manifest);
  }, [apiBase, apiReason, connectLiveStream]);

  const playStory = useCallback(async () => {
    const replayEvents = await loadReplay(false);
    if (!replayEvents.length) return;
    setVisibleCount(1);
    setPlaying(true);
    setNotice("Playing · deterministic 15s narration over verified event order");
  }, [loadReplay]);

  const resetLive = useCallback(async () => {
    if (!apiBase || mode !== "LIVE" || !manifest) return;
    const response = await fetch(`${apiBase}/api/reset`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-SciGuard-Session": liveSession(),
      },
      body: JSON.stringify({ incident_id: manifest.incident_id }),
    });
    if (!response.ok) throw new Error(await response.text());
    await loadReplay(false);
    setNotice("LIVE SANDBOX RESET · verified replay restored");
  }, [apiBase, loadReplay, manifest, mode]);

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
  const recoveryStarted = visibleEvents.some((event) =>
    [
      "RECOVERY_EVIDENCE_REFRESHED",
      "RECOVERY_CHECKED",
      "INCIDENT_RESOLVED",
    ].includes(event.event_type),
  );
  const activeControlStage = recoveryStarted
    ? CONTROL_STAGES.length - 1
    : Math.min(macroStageIndex(activeStage), CONTROL_STAGES.length - 2);
  const controlRunComplete = visibleEvents.some(
    (event) => event.event_type === "INCIDENT_RESOLVED",
  );

  const displayedFocusedStage =
    playing || playbackState === "COMPLETE" ? activeStage : focusedStage;

  const evidence = useMemo(() => {
    const records = new Map<string, EvidenceRecord>();
    records.set(evaluationEvidence.evidence_id, evaluationEvidence);
    records.set(dataHubCapabilityEvidence.evidence_id, dataHubCapabilityEvidence);
    if (manifest) {
      records.set(REPLAY_INTEGRITY_EVIDENCE_ID, {
        evidence_id: REPLAY_INTEGRITY_EVIDENCE_ID,
        source: "CANONICAL_REPLAY_MANIFEST",
        kind: "INTEGRITY_CHECKED_REPLAY",
        summary: `${manifest.event_count} immutable events passed the canonical replay checks`,
        payload: {
          incident_id: manifest.incident_id,
          event_count: manifest.event_count,
          events_sha256: manifest.events_sha256,
          source_commit: manifest.source_commit,
          source_worktree_dirty: manifest.source_worktree_dirty,
          validation: manifest.validation ?? {},
          integrity_boundary:
            "Internal package consistency only; not a digital signature or proof of origin",
        },
      });
    }
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
      if (Array.isArray(entries)) {
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
  }, [dataHubLiveReceipt, githubLiveEvidence, manifest, visibleEvents]);

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
  const canonicalRecoveryResults = Array.isArray(
    objectValue(dataHubLiveReceipt?.repair_lifecycle).recovery_results,
  )
    ? (objectValue(dataHubLiveReceipt?.repair_lifecycle).recovery_results as JsonValue[]).map(
        objectValue,
      )
    : [];
  const canonicalRecoveryResult = canonicalRecoveryResults.at(-1) ?? {};
  const canonicalResumeAllowed =
    judgeMode &&
    mode === "RECORDED_REPLAY" &&
    booleanValue(canonicalRecoveryResult.resume_allowed);
  const repairPatch = repairArtifacts.find(
    (artifact) => artifact.kind === "CODE_PATCH",
  );
  const canOperateRepair = Boolean(
    !judgeMode &&
      mode === "LIVE" &&
      apiBase &&
      manifest?.incident_id &&
      apiHealth === "ok",
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
  const drawerGitHubChange = objectValue(drawerPayload.change_receipt);
  const drawerGitHubVerification = objectValue(
    drawerPayload.verification_receipt,
  );
  const drawerGitHubChecks = Array.isArray(drawerGitHubVerification.checks)
    ? drawerGitHubVerification.checks.map(objectValue)
    : [];
  const publicPullRequest = objectValue(githubLiveEvidence?.pull_request);
  const publicVerification = objectValue(
    githubLiveEvidence?.verification_receipt,
  );
  const publicChecks = Array.isArray(publicVerification.checks)
    ? publicVerification.checks.map(objectValue)
    : [];
  const judgeTourIndex = Math.max(
    0,
    JUDGE_TOUR_STEPS.findIndex((step) => step.page === judgePage),
  );
  const nextJudgeTourStep = JUDGE_TOUR_STEPS[judgeTourIndex + 1];

  return (
    <main className={`command-center ${judgeMode ? "judge-mode judge-portal" : "product-mode"} experience-${experienceView.toLowerCase()} page-${judgePage.toLowerCase()} stage-focus-${activeStage + 1} ${studioDetailsOpen ? "studio-details-open" : "studio-summary-open"}`}>
      {judgeMode ? (
        <>
          <button
            className="skip-link"
            onClick={() =>
              document
                .getElementById(JUDGE_PAGE_HEADING_IDS[judgePage])
                ?.focus()
            }
            type="button"
          >
            Skip to main content
          </button>
          <header className="portal-header">
            <button
              aria-label="Return to SciGuard overview"
              className="portal-brand"
              onClick={() => navigateJudgePage("OVERVIEW")}
              type="button"
            >
              <span className="brand-mark" aria-hidden="true"><b>SG</b></span>
              <span><strong>SciGuard</strong><small>Autopilot</small></span>
            </button>
            <nav aria-label="SciGuard judge experience pages" className="portal-navigation">
              {JUDGE_PAGES.map((page) => (
                <button
                  aria-current={judgePage === page.id ? "page" : undefined}
                  className={judgePage === page.id ? "is-active" : ""}
                  key={page.id}
                  onClick={() => navigateJudgePage(page.id)}
                  type="button"
                >
                  <span>{page.label}</span>
                  <small>{page.shortLabel}</small>
                </button>
              ))}
            </nav>
            <div className="portal-resources">
              <a href={SOURCE_REPOSITORY_URL} rel="noreferrer" target="_blank">
                GitHub <span aria-hidden="true">↗</span>
              </a>
              {DEMO_VIDEO_URL ? (
                <a href={DEMO_VIDEO_URL} rel="noreferrer" target="_blank">
                  Video <span aria-hidden="true">↗</span>
                </a>
              ) : (
                <span className="resource-pending" title="The final public video URL will appear here after upload">
                  Video soon
                </span>
              )}
            </div>
          </header>
          {judgePage !== "OVERVIEW" && (
            <div className="portal-context-bar">
              <div>
                <span className="mono">{manifest?.incident_id ?? "SG-LOADING"}</span>
                <StatusMark status={incidentState} />
                <span className={`mode-badge mode-${mode.toLowerCase()}`}><i /> {mode.replace("_", " ")}</span>
                <span className="backend-pill"><i /> {manifest?.datahub_backend ?? "DATAHUB"}</span>
              </div>
              <div className="portal-run-actions">
                <button
                  className="button primary"
                  disabled={apiHealth !== "ok"}
                  onClick={() => {
                    navigateJudgePage("STUDIO");
                    void startLive().catch((error: unknown) => {
                      setNotice(error instanceof Error ? error.message : "Live run failed");
                    });
                  }}
                  type="button"
                >
                  Run live
                </button>
                <button
                  className="button ghost"
                  disabled={integrity === "failed"}
                  onClick={() => {
                    navigateJudgePage("STUDIO");
                    void playStory().catch((error: unknown) => {
                      setIntegrity("failed");
                      setNotice(error instanceof Error ? error.message : "Replay failed");
                    });
                  }}
                  type="button"
                >
                  {playing ? "Playing replay" : "Watch replay"}
                </button>
              </div>
            </div>
          )}
        </>
      ) : (
        <>
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
                aria-label={
                  apiHealth === "ok"
                    ? "Run a live scientific incident"
                    : "Watch the verified champion run"
                }
                className="button primary"
                disabled={apiHealth !== "ok" && integrity === "failed"}
                onClick={() => {
                  const action = apiHealth === "ok" ? startLive() : playStory();
                  void action.catch((error: unknown) => {
                    setNotice(error instanceof Error ? error.message : "Run failed");
                  });
                }}
                type="button"
              >
                {apiHealth === "ok"
                  ? "RUN LIVE SCIENTIFIC INCIDENT"
                  : playing
                    ? "PLAYING VERIFIED RUN"
                    : "WATCH VERIFIED CHAMPION RUN"}
              </button>
              <button
                className="button ghost"
                onClick={() => void playStory().catch((error: unknown) => {
                  setIntegrity("failed");
                  setNotice(error instanceof Error ? error.message : "Replay failed");
                })}
                type="button"
              >
                {playing ? "PLAYING VERIFIED RUN" : "WATCH VERIFIED CHAMPION RUN"}
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
        </>
      )}

      {judgeMode && judgeTourActive && (
        <aside className="judge-tour-bar" aria-label="Two-minute judge tour">
          <div className="judge-tour-title">
            <small>2-MINUTE JUDGE TOUR</small>
            <strong>{JUDGE_TOUR_STEPS[judgeTourIndex].prompt}</strong>
          </div>
          <ol>
            {JUDGE_TOUR_STEPS.map((step, index) => (
              <li key={`${step.time}-${step.page}`}>
                <button
                  aria-current={index === judgeTourIndex ? "step" : undefined}
                  className={index === judgeTourIndex ? "is-active" : index < judgeTourIndex ? "is-complete" : ""}
                  onClick={() => navigateJudgePage(step.page)}
                  type="button"
                >
                  <small>{step.time}</small>
                  <strong>{step.label}</strong>
                </button>
              </li>
            ))}
          </ol>
          {nextJudgeTourStep ? (
            <button
              className="judge-tour-next"
              onClick={() => navigateJudgePage(nextJudgeTourStep.page)}
              type="button"
            >
              Next · {nextJudgeTourStep.label} <span aria-hidden="true">→</span>
            </button>
          ) : (
            <button
              className="judge-tour-next is-complete"
              onClick={() => setJudgeTourActive(false)}
              type="button"
            >
              Tour complete <span aria-hidden="true">✓</span>
            </button>
          )}
          <button
            aria-label="Close two-minute judge tour"
            className="judge-tour-close"
            onClick={() => setJudgeTourActive(false)}
            type="button"
          >
            ×
          </button>
        </aside>
      )}

      {judgeMode && judgePage === "OVERVIEW" && (
        <section className="portal-overview" aria-labelledby="portal-overview-title">
          <div className="overview-hero">
            <div className="overview-copy">
              <div className="overview-kicker">
                <span>DATAHUB-NATIVE SCIENTIFIC DECISION AGENT</span>
                <i />
                <strong>PUBLIC JUDGE EXPERIENCE</strong>
              </div>
              <h1 id="portal-overview-title" tabIndex={-1}>
                Protect the scientific decision,
                <em>not just the data pipeline.</em>
              </h1>
              <p>
                SciGuard detects silent scientific drift, proves its exact
                downstream impact with DataHub, delivers a reviewed repair, and
                verifies recovery before decisions resume.
              </p>
              <div className="overview-actions">
                <button
                  className="button primary overview-primary"
                  onClick={() => {
                    navigateJudgePage("STUDIO");
                    void startLive().catch((error: unknown) => {
                      setNotice(
                        `${error instanceof Error ? error.message : "Live run failed"} · loading verified replay`,
                      );
                      void playStory();
                    });
                  }}
                  type="button"
                >
                  Run live scenario <span aria-hidden="true">→</span>
                </button>
                <button
                  className="button ghost overview-video"
                  disabled={integrity === "failed"}
                  onClick={() => {
                    navigateJudgePage("STUDIO");
                    void playStory().catch((error: unknown) => {
                      setIntegrity("failed");
                      setNotice(
                        error instanceof Error ? error.message : "Replay failed",
                      );
                    });
                  }}
                  type="button"
                >
                  <span aria-hidden="true">▶</span> Watch verified replay
                </button>
                <button
                  className="button text overview-incident"
                  onClick={() => {
                    setJudgeTourActive(true);
                  }}
                  type="button"
                >
                  Start 2-minute judge tour
                </button>
                <a
                  className="button text overview-github"
                  href={SOURCE_REPOSITORY_URL}
                  rel="noreferrer"
                  target="_blank"
                >
                  GitHub repository <span aria-hidden="true">↗</span>
                </a>
              </div>
              <div className="overview-proof-line">
                <span><i /> Real PR + hosted CI</span>
                <span><i /> Owner approval gate</span>
                <span><i /> DataHub writeback</span>
              </div>
            </div>
            <div className="overview-decision-visual" aria-label="Candidate P-204 scientific decision changed from trusted rank 18 to unsafe rank 1">
              <div className="decision-visual-header">
                <span>SCIENTIFIC DECISION · P-204</span>
                <StatusMark status={controlRunComplete ? "VERIFIED" : "AT RISK"} />
              </div>
              <div className="decision-rank-scene">
                <button
                  aria-label="Inspect evidence for trusted rank 18"
                  className="decision-rank trusted"
                  onClick={(event) => openEvidence(rankEvidence, event.currentTarget)}
                  type="button"
                >
                  <small>TRUSTED</small>
                  <strong>#18</strong>
                  <span>validated baseline</span>
                </button>
                <button
                  aria-label="Inspect evidence for 187 mixed-unit rows"
                  className="decision-shift"
                  onClick={(event) => openEvidence(unitEvidence, event.currentTarget)}
                  type="button"
                >
                  <i aria-hidden="true" />
                  <span>187 mixed-unit rows</span>
                </button>
                <button
                  aria-label="Inspect evidence for unsafe rank 1"
                  className="decision-rank unsafe"
                  onClick={(event) => openEvidence(rankEvidence, event.currentTarget)}
                  type="button"
                >
                  <small>UNSAFE</small>
                  <strong>#1</strong>
                  <span>publication blocked</span>
                </button>
              </div>
              <div className="decision-contradiction">
                <span><b aria-hidden="true">✓</b> Pipeline passed</span>
                <span><b aria-hidden="true">!</b> Scientific contract failed</span>
              </div>
              <div className="decision-control-outcomes">
                <button
                  onClick={(event) =>
                    openEvidence(
                      blockedEvent?.evidence_ids[0] ?? "stage:enforce",
                      event.currentTarget,
                    )
                  }
                  type="button"
                >
                  <small>UNSAFE PATH</small><strong>Blocked</strong>
                </button>
                <button
                  onClick={(event) =>
                    openEvidence(
                      allowedEvent?.evidence_ids[0] ?? impactEvidence,
                      event.currentTarget,
                    )
                  }
                  type="button"
                >
                  <small>SAFE WORK</small><strong>Continues</strong>
                </button>
              </div>
              <div className="decision-datahub-readout">
                <button
                  onClick={(event) =>
                    openEvidence(
                      dataHubLiveReceipt
                        ? DATAHUB_LIVE_RECEIPT_EVIDENCE_ID
                        : dataHubCapabilityEvidence.evidence_id,
                      event.currentTarget,
                    )
                  }
                  type="button"
                ><small>DATAHUB ENTITIES</small><strong>{dataHubEntityCount || 19}</strong></button>
                <button
                  onClick={(event) =>
                    openEvidence(REPLAY_INTEGRITY_EVIDENCE_ID, event.currentTarget)
                  }
                  type="button"
                ><small>IMMUTABLE EVENTS</small><strong>{manifest?.event_count ?? 55}</strong></button>
                <button
                  aria-label="DataHub lineage found 3 of 3 exact decision cones versus 0 of 3 for search-only"
                  onClick={(event) =>
                    openEvidence(evaluationEvidence.evidence_id, event.currentTarget)
                  }
                  type="button"
                ><small>EXACT CONES</small><strong>3 / 3</strong><em>vs 0 / 3 search-only</em></button>
              </div>
            </div>
          </div>

          <div className="overview-system-map">
            <div className="overview-section-heading">
              <div>
                <span>ONE CONTINUOUS CONTROL LOOP</span>
                <h2>From silent drift to verifiable recovery.</h2>
              </div>
              <p>
                Select any stage to enter the corresponding judge experience.
              </p>
            </div>
            <DecisionControlMap
              activeIndex={activeControlStage}
              complete={controlRunComplete}
              onSelect={(index) => {
                if (index === 0) navigateJudgePage("INCIDENT");
                else if (index === 1) navigateJudgePage("CONTEXT");
                else navigateJudgePage("STUDIO");
              }}
            />
          </div>

          <div className="overview-trust-strip">
            <div><small>DATAHUB DEPTH</small><strong>Context graph → native writeback</strong></div>
            <div><small>TECHNICAL EXECUTION</small><strong>Real PR · checks · exact SHA</strong></div>
            <div><small>SAFETY BOUNDARY</small><strong>Policy controls every mutation</strong></div>
            <div><small>MEASURED VALUE</small><strong>3/3 exact cones with lineage</strong></div>
          </div>
        </section>
      )}

      {judgeMode && judgePage === "INCIDENT" && (
        <section className="decision-brief" aria-labelledby="decision-brief-title">
          <div className="brief-signal">
            <div className="brief-eyebrow">
              <span>SCIENTIFIC DECISION INCIDENT</span>
              <i />
              <strong>POLYMER R&amp;D</strong>
            </div>
            <h1 id="decision-brief-title" tabIndex={-1}>
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
                disabled={apiHealth !== "ok"}
                onClick={() => void startLive().catch((error: unknown) => {
                  setNotice(error instanceof Error ? error.message : "Live run failed");
                })}
                type="button"
              >
                RUN LIVE SCIENTIFIC INCIDENT
              </button>
              <button
                className="button ghost"
                disabled={integrity === "failed"}
                onClick={() =>
                  void playStory().catch((error: unknown) => {
                    setIntegrity("failed");
                    setNotice(error instanceof Error ? error.message : "Replay failed");
                  })
                }
                type="button"
              >
                {playing ? "PLAYING VERIFIED RUN" : "WATCH VERIFIED CHAMPION RUN"}
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
                <button
                  className="inline-evidence-number"
                  onClick={(event) =>
                    openEvidence(evaluationEvidence.evidence_id, event.currentTarget)
                  }
                  type="button"
                >
                  Exact cone: 3 / 3
                </button>
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
                onClick={() => navigateJudgePage("EVIDENCE")}
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
          <div className="page-journey">
            <div>
              <small>NEXT · DATAHUB CONTEXT</small>
              <strong>The pipeline could not explain the impact. DataHub could.</strong>
            </div>
            <button
              className="button primary"
              onClick={() => navigateJudgePage("CONTEXT")}
              type="button"
            >
              Trace the impact <span aria-hidden="true">→</span>
            </button>
          </div>
        </section>
      )}

      {judgeMode && judgePage === "CONTEXT" && (
        <section className="context-page" aria-labelledby="context-page-title">
          <div className="context-page-intro">
            <div>
              <span className="page-number">02 · DATAHUB CONTEXT</span>
              <h1 id="context-page-title" tabIndex={-1}>
                One changed field.
                <em>One exact decision cone.</em>
              </h1>
              <p>
                Search can find similar names. DataHub&apos;s directed,
                field-level lineage proves exactly which feature, model, and
                decision consumed the changed value—and which work did not.
              </p>
              <p className="plain-language-note">
                <strong>Decision cone</strong> means every downstream decision
                that actually consumed the changed field.
              </p>
            </div>
            <button
              aria-label="Inspect the three-arm DataHub evaluation"
              className="context-score"
              onClick={(event) =>
                openEvidence(evaluationEvidence.evidence_id, event.currentTarget)
              }
              type="button"
            >
              <span>WHY DATAHUB</span>
              <strong>3 / 3</strong>
              <small>exact cones with lineage</small>
              <b>0 / 3 search-only</b>
            </button>
          </div>

          <div className="context-workspace">
            <div className="context-graph-card">
              <div className="context-card-heading">
                <div>
                  <span>INTERACTIVE IMPACT MAP</span>
                  <strong>Affected path highlighted · safe branch preserved</strong>
                </div>
                <div className="context-legend">
                  <span><i className="legend-context" /> DataHub context</span>
                  <span><i className="legend-risk" /> affected</span>
                  <span><i className="legend-safe" /> preserved</span>
                </div>
              </div>
              <div className="context-lineage-canvas">
                <button
                  className="context-entity source-entity"
                  onClick={(event) => openEvidence(unitEvidence, event.currentTarget)}
                  type="button"
                >
                  <small>DATASET · SNOWFLAKE</small>
                  <strong>experimental_data</strong>
                  <span>B042 · owner: Polymer R&amp;D</span>
                </button>
                <i className="lineage-link source-link"><span>tg_value</span></i>
                <button
                  className="context-entity field-entity"
                  onClick={(event) => openEvidence(unitEvidence, event.currentTarget)}
                  type="button"
                >
                  <small>CHANGED FIELD</small>
                  <strong>temperature</strong>
                  <span>Kelvin → mixed K / °C</span>
                </button>
                <i className="lineage-link split-link"><span>field lineage</span></i>
                <div className="context-branch affected-context-branch">
                  <span className="branch-label">AFFECTED · HALT</span>
                  <button
                    className="context-entity"
                    onClick={(event) => openEvidence(impactEvidence, event.currentTarget)}
                    type="button"
                  >
                    <small>NATIVE ML FEATURE</small>
                    <strong>heat_resistance_tg</strong>
                    <span>critical scientific feature</span>
                  </button>
                  <i className="lineage-link" />
                  <button
                    className="context-entity"
                    onClick={(event) => openEvidence(impactEvidence, event.currentTarget)}
                    type="button"
                  >
                    <small>NATIVE ML MODEL</small>
                    <strong>Tg Model · v3</strong>
                    <span>training · deployment · inference</span>
                  </button>
                  <i className="lineage-link" />
                  <button
                    className="context-entity decision-entity"
                    onClick={(event) => openEvidence(rankEvidence, event.currentTarget)}
                    type="button"
                  >
                    <small>SCIENTIFIC DECISION</small>
                    <strong>Candidate ranking</strong>
                    <StatusMark status="HALT" />
                  </button>
                </div>
                <div className="context-branch safe-context-branch">
                  <span className="branch-label">PRESERVED · ALLOW</span>
                  <button
                    className="context-entity"
                    onClick={(event) => openEvidence(impactEvidence, event.currentTarget)}
                    type="button"
                  >
                    <small>NATIVE ML FEATURE</small>
                    <strong>molecular_weight</strong>
                    <span>independent field lineage</span>
                  </button>
                  <i className="lineage-link" />
                  <button
                    className="context-entity"
                    onClick={(event) => openEvidence(impactEvidence, event.currentTarget)}
                    type="button"
                  >
                    <small>NATIVE ML MODEL</small>
                    <strong>Durability Model · v2</strong>
                    <span>unchanged input digest</span>
                  </button>
                  <i className="lineage-link" />
                  <button
                    className="context-entity decision-entity"
                    onClick={(event) => openEvidence(impactEvidence, event.currentTarget)}
                    type="button"
                  >
                    <small>SCIENTIFIC DECISION</small>
                    <strong>Formulation report</strong>
                    <StatusMark status="ALLOW" />
                  </button>
                </div>
              </div>
            </div>

            <aside className="context-inspector" aria-label="DataHub context explanation">
              <span className="inspector-eyebrow">WHY THIS MATTERS</span>
              <h2>DataHub turns metadata into a control boundary.</h2>
              <p>
                The same graph supplies scope, ownership, criticality, and
                governance context before any mutating action is authorized.
              </p>
              <dl>
                <div><dt>Changed field</dt><dd>temperature · unit contract</dd></div>
                <div><dt>Affected</dt><dd>6 assets · 1 decision</dd></div>
                <div><dt>Preserved</dt><dd>3 independent assets</dd></div>
                <div><dt>Owner</dt><dd>Polymer R&amp;D</dd></div>
                <div><dt>Criticality</dt><dd>Mission critical</dd></div>
              </dl>
              <button
                className="button ghost"
                onClick={(event) =>
                  openEvidence(
                    dataHubLiveReceipt
                      ? DATAHUB_LIVE_RECEIPT_EVIDENCE_ID
                      : dataHubCapabilityEvidence.evidence_id,
                    event.currentTarget,
                  )
                }
                type="button"
              >
                Inspect DataHub receipt
              </button>
            </aside>
          </div>

          <div className="context-ablation">
            {WHY_DATAHUB_RESULTS.map((result) => (
              <button
                className={result.id === "full-lineage" ? "is-best" : ""}
                key={result.id}
                onClick={(event) =>
                  openEvidence(evaluationEvidence.evidence_id, event.currentTarget)
                }
                type="button"
              >
                <small>{result.label}</small>
                <strong>{result.exactCone}</strong>
                <span>exact decision cones</span>
                <StatusMark status={result.status} />
              </button>
            ))}
          </div>

          <div className="page-journey">
            <div>
              <small>NEXT · RECOVERY STUDIO</small>
              <strong>See the agent turn context into a controlled repair.</strong>
            </div>
            <button
              className="button primary"
              onClick={() => navigateJudgePage("STUDIO")}
              type="button"
            >
              Open Recovery Studio <span aria-hidden="true">→</span>
            </button>
          </div>
        </section>
      )}

      {judgeMode && judgePage === "STUDIO" && (
        <div className="studio-process-header">
          <h1 className="sr-only" id="studio-page-title" tabIndex={-1}>
            Recovery Studio
          </h1>
          <div>
            <small>DECISION RECOVERY MAP</small>
            <strong>{notice}</strong>
          </div>
          <DecisionControlMap
            activeIndex={activeControlStage}
            compact
            complete={controlRunComplete}
            onSelect={(index) => setFocusedStage([0, 2, 3, 4, 5][index] ?? 0)}
          />
        </div>
      )}

      {judgeMode && judgePage === "STUDIO" && (
        <section className="studio-proof-rail" aria-label="Canonical repair delivery evidence">
          <div className="studio-proof-heading">
            <small>CANONICAL DELIVERY PROOF</small>
            <strong>Patch → PR → CI → recovery</strong>
            <span>The live run is isolated; these receipts bind the completed reference incident.</span>
            <div className="studio-scope-legend" aria-label="Evidence scope">
              <i>LIVE RUN · isolated</i>
              <i>CANONICAL REFERENCE · completed</i>
            </div>
          </div>
          <button
            onClick={() => {
              const reduceMotion = window.matchMedia(
                "(prefers-reduced-motion: reduce)",
              ).matches;
              document.getElementById("repair-patch")?.scrollIntoView({
                behavior: reduceMotion ? "auto" : "smooth",
                block: "center",
              });
            }}
            type="button"
          >
            <small>REPAIR BUNDLE</small>
            <strong>Patch + 4 proof files</strong>
            <span>Open patch · tests · rollback</span>
          </button>
          {stringValue(publicPullRequest.url) ? (
            <a href={stringValue(publicPullRequest.url)} rel="noreferrer" target="_blank">
              <small>REAL GITHUB PR</small>
              <strong>PR #{numberValue(publicPullRequest.number, 2)} · OPEN</strong>
              <span>Exact revision <b>↗</b></span>
            </a>
          ) : (
            <button disabled type="button"><small>REAL GITHUB PR</small><strong>Loading receipt</strong></button>
          )}
          <button
            onClick={(event) => openEvidence(GITHUB_LIVE_EVIDENCE_ID, event.currentTarget)}
            type="button"
          >
            <small>HOSTED CI</small>
            <strong>{publicChecks.length || 3} / 3 PASS</strong>
            <span>Bound to exact SHA</span>
          </button>
          <button
            onClick={(event) => openEvidence(DATAHUB_LIVE_RECEIPT_EVIDENCE_ID, event.currentTarget)}
            type="button"
          >
            <small>APPROVAL + RECOVERY</small>
            <strong>Owner gate · 2 clean runs</strong>
            <span>DataHub closure published</span>
          </button>
        </section>
      )}

      {judgeMode && judgePage === "STUDIO" && (
        <div className="studio-view-toggle" aria-label="Recovery Studio detail level">
          <div>
            <small>DEFAULT JUDGE VIEW</small>
            <strong>
              {studioDetailsOpen
                ? "Technical telemetry and policy controls"
                : "Review the patch, PR, CI, approval, and recovery first"}
            </strong>
          </div>
          <div role="group" aria-label="Choose Studio detail level">
            <button
              aria-pressed={!studioDetailsOpen}
              className={!studioDetailsOpen ? "is-active" : ""}
              onClick={() => setStudioDetailsOpen(false)}
              type="button"
            >
              Judge summary
            </button>
            <button
              aria-pressed={studioDetailsOpen}
              className={studioDetailsOpen ? "is-active" : ""}
              onClick={() => setStudioDetailsOpen(true)}
              type="button"
            >
              Technical details
            </button>
          </div>
        </div>
      )}

      {((!judgeMode && experienceView !== "BRIEF") ||
        (judgeMode && judgePage === "STUDIO")) && <section className="runtime-strip" aria-label="Runtime and replay status">
        <div className={`live-backend live-${apiHealth}`}>
          <b className="runtime-scope-chip">
            CURRENT · {mode === "LIVE" ? "LIVE RUN" : "VERIFIED REPLAY"}
          </b>
          <span><i /> {apiHealth === "ok" ? "LIVE SANDBOX READY" : apiHealth === "offline" ? "VERIFIED RUN READY" : "VERIFYING LIVE SANDBOX"}</span>
          <small>
            {apiHealth === "ok"
              ? "Session-isolated live controller and event stream"
              : apiHealth === "offline"
                ? "The integrity-checked replay preserves the complete judge path"
                : "The verified replay remains available while the live check completes"}
          </small>
          {apiHealth === "ok" && (
            <button
              className="button text"
              onClick={() => void startLive().catch((error: unknown) => {
                setNotice(error instanceof Error ? error.message : "Live run failed");
              })}
              type="button"
            >
              RUN LIVE SCIENTIFIC INCIDENT
            </button>
          )}
          <button
            className="button text"
            onClick={() => void playStory().catch((error: unknown) => {
              setIntegrity("failed");
              setNotice(error instanceof Error ? error.message : "Replay failed");
            })}
            type="button"
          >
            WATCH VERIFIED CHAMPION RUN
          </button>
          {mode === "LIVE" && manifest?.status === "COMPLETED" && (
            <button
              className="button text"
              onClick={() => void resetLive().catch((error: unknown) => {
                setNotice(error instanceof Error ? error.message : "Reset failed");
              })}
              type="button"
            >
              RESET ISOLATED RUN
            </button>
          )}
        </div>
        <div className="timing-facts">
          <span><small>CONTROLLER EVENT SPAN</small><strong>{controllerRuntime}</strong></span>
          <span><small>NARRATED REPLAY DURATION</small><strong>15.0s</strong></span>
          <span aria-live="polite"><small>PLAYBACK</small><strong>{playbackState}</strong></span>
        </div>
      </section>}

      {judgeMode && judgePage === "EVIDENCE" && (
        <section className="evidence-page" aria-labelledby="evidence-page-title">
          <div className="evidence-page-hero">
            <div>
              <span className="page-number">04 · VERIFIABLE DELIVERY</span>
              <h1 id="evidence-page-title" tabIndex={-1}>
                The incident is resolved.
                <em>The proof remains inspectable.</em>
              </h1>
              <p>
                Every claim below is bound to the same incident, exact repair
                revision, hosted checks, approval boundary, recovery runs, and
                DataHub read-back.
              </p>
            </div>
            <div className="evidence-verdict">
              <span aria-hidden="true">✓</span>
              <small>FINAL STATE</small>
              <strong>RESOLVED</strong>
              <p>Two clean runs · resume authorized</p>
            </div>
          </div>

          <div className="proof-passport" aria-label="End-to-end proof passport">
            <div className="proof-passport-heading">
              <div>
                <span>PROOF PASSPORT</span>
                <h2>One incident. Seven independently inspectable receipts.</h2>
              </div>
              <code>{manifest?.incident_id ?? REPLAY_ID}</code>
            </div>
            <div className="proof-passport-chain">
              {[
                ["DETECTION", unitEvidence],
                ["CONTEXT", impactEvidence],
                ["CONTROL", blockedEvent?.evidence_ids[0] ?? "stage:enforce"],
                ["REPAIR", GITHUB_LIVE_EVIDENCE_ID],
                ["APPROVAL", GITHUB_LIVE_EVIDENCE_ID],
                ["RECOVERY", recoveryEvent?.evidence_ids[0] ?? "stage:verify-recovery"],
                ["WRITEBACK", DATAHUB_LIVE_RECEIPT_EVIDENCE_ID],
              ].map(([label, evidenceId], index) => (
                <div className="passport-segment" key={label}>
                  <button
                    onClick={(event) =>
                      openEvidence(String(evidenceId), event.currentTarget)
                    }
                    type="button"
                  >
                    <span aria-hidden="true">✓</span>
                    <small>0{index + 1}</small>
                    <strong>{label}</strong>
                    <em>Verified</em>
                  </button>
                  {index < 6 && <i aria-hidden="true" />}
                </div>
              ))}
            </div>
          </div>

          <div className="evidence-source-grid">
            <article className="evidence-source-card datahub-source-card">
              <div className="source-card-top">
                <span className="source-icon">DH</span>
                <StatusMark status="VERIFIED" />
              </div>
              <small>DATAHUB LIVE RECEIPT</small>
              <h2>Context, incident, ML entities, and closure.</h2>
              <p>
                {dataHubEntityCount || 19} native entities were read back from
                the same DataHub server after the repair lifecycle completed.
              </p>
              <p className="plain-language-definition">
                <strong>Writeback</strong> means the incident status and new
                recovery knowledge were saved into DataHub.
              </p>
              <dl>
                <div><dt>Incident</dt><dd>RESOLVED</dd></div>
                <div><dt>Decision log</dt><dd>PUBLISHED</dd></div>
                <div><dt>Repair lifecycle</dt><dd>APPLIED</dd></div>
              </dl>
              <button
                className="button ghost"
                onClick={(event) =>
                  openEvidence(
                    DATAHUB_LIVE_RECEIPT_EVIDENCE_ID,
                    event.currentTarget,
                  )
                }
                type="button"
              >
                Inspect DataHub proof
              </button>
            </article>

            <article className="evidence-source-card github-source-card">
              <div className="source-card-top">
                <span className="source-icon">GH</span>
                <StatusMark status={stringValue(publicVerification.status, "PASS")} />
              </div>
              <small>GITHUB PR + HOSTED CI</small>
              <h2>
                PR #{numberValue(publicPullRequest.number, 2)} · exact revision
              </h2>
              <p>
                A real public pull request, {publicChecks.length || 3} hosted
                checks, and an account-bound review remain linked to the repair
                receipt.
              </p>
              <code>
                {stringValue(publicPullRequest.head_sha) ||
                  "ea1a4760520fcb299d8b8f73d955e5c66cc03ee3"}
              </code>
              <div className="source-card-actions">
                {stringValue(publicPullRequest.url) && (
                  <a
                    className="button ghost"
                    href={stringValue(publicPullRequest.url)}
                    rel="noreferrer"
                    target="_blank"
                  >
                    Open repair PR <span aria-hidden="true">↗</span>
                  </a>
                )}
                <button
                  className="button text"
                  onClick={(event) =>
                    openEvidence(GITHUB_LIVE_EVIDENCE_ID, event.currentTarget)
                  }
                  type="button"
                >
                  Inspect receipt
                </button>
              </div>
            </article>

            <article className="evidence-source-card evaluation-source-card">
              <div className="source-card-top">
                <span className="source-icon">EV</span>
                <StatusMark status="PASS" />
              </div>
              <small>MEASURED DATAHUB ABLATION</small>
              <h2>Lineage changes the decision boundary.</h2>
              <p>
                Full context recovered 3/3 exact cones. Search-only recovered
                0/3; without DataHub the agent abstained instead of inventing
                dependencies.
              </p>
              <p className="plain-language-definition">
                <strong>Ablation</strong> means the same task was tested with
                full DataHub context, search-only context, and no DataHub.
              </p>
              <div className="evaluation-mini-metrics">
                <span><strong>100%</strong><small>precision</small></span>
                <span><strong>100%</strong><small>recall</small></span>
                <span><strong>3/3</strong><small>exact cones</small></span>
              </div>
              <button
                className="button ghost"
                onClick={(event) =>
                  openEvidence(evaluationEvidence.evidence_id, event.currentTarget)
                }
                type="button"
              >
                Inspect evaluation
              </button>
            </article>
          </div>

          <section className="audit-boundaries" aria-labelledby="audit-boundaries-title">
            <div className="audit-boundaries-heading">
              <span>HONESTY BOUNDARIES</span>
              <h2 id="audit-boundaries-title">What is live, verified, and intentionally not claimed.</h2>
            </div>
            <button
              onClick={(event) =>
                openEvidence(DATAHUB_LIVE_RECEIPT_EVIDENCE_ID, event.currentTarget)
              }
              type="button"
            >
              <small>PUBLIC LIVE MODE</small>
              <strong>Controller + SSE are live</strong>
              <span>DataHub context is a captured read-back; each public run is isolated and synthetic.</span>
            </button>
            <button
              onClick={(event) => openEvidence(GITHUB_LIVE_EVIDENCE_ID, event.currentTarget)}
              type="button"
            >
              <small>IDENTITY</small>
              <strong>GitHub account review</strong>
              <span>Not enterprise SSO, not an independent reviewer, and not production authorization.</span>
            </button>
            <button
              onClick={(event) =>
                openEvidence(REPLAY_INTEGRITY_EVIDENCE_ID, event.currentTarget)
              }
              type="button"
            >
              <small>REPLAY INTEGRITY</small>
              <strong>Hash-consistent package</strong>
              <span>Internal consistency only; not a digital signature or proof of origin.</span>
            </button>
          </section>

          <div className="submission-resources">
            <div>
              <span>SUBMISSION RESOURCES</span>
              <h2>Continue from product experience to public proof.</h2>
            </div>
            <a href={SOURCE_REPOSITORY_URL} rel="noreferrer" target="_blank">
              <small>SOURCE CODE</small>
              <strong>GitHub repository</strong>
              <span>Apache-2.0 · public <b>↗</b></span>
            </a>
            {DEMO_VIDEO_URL ? (
              <a href={DEMO_VIDEO_URL} rel="noreferrer" target="_blank">
                <small>DEMO VIDEO</small>
                <strong>Watch on YouTube</strong>
                <span>Public · under 3 minutes <b>↗</b></span>
              </a>
            ) : (
              <div className="submission-resource-pending">
                <small>DEMO VIDEO</small>
                <strong>YouTube link pending</strong>
                <span>Final video will be connected after upload</span>
              </div>
            )}
            <button onClick={() => navigateJudgePage("STUDIO")} type="button">
              <small>LIVE PRODUCT</small>
              <strong>Run another incident</strong>
              <span>Bounded public sandbox <b>→</b></span>
            </button>
          </div>
        </section>
      )}

      {!judgeMode && experienceView === "AUDIT" && (
        <section className="judge-cockpit" aria-labelledby="judge-cockpit-title">
          <div className="cockpit-lead">
            <span className="kicker">PUBLIC JUDGE MODE · DETERMINISTIC SYNTHETIC DATA</span>
            <h1 id="judge-cockpit-title">A model succeeded. <em>The science did not.</em></h1>
            <p>
              P-204 jumped from trusted rank <strong>#18</strong> to <strong>#1</strong> after
              187 B042 rows violated the Kelvin / Celsius contract.
            </p>
            <button
              aria-label={
                apiHealth === "ok"
                  ? "Run a live scientific incident from the Judge Cockpit"
                  : "Watch the verified champion run from the Judge Cockpit"
              }
              className="button primary cockpit-run"
              disabled={apiHealth !== "ok" && integrity === "failed"}
              onClick={() => {
                const action = apiHealth === "ok" ? startLive() : playStory();
                void action.catch((error: unknown) => {
                  setNotice(error instanceof Error ? error.message : "Run failed");
                });
              }}
              type="button"
            >
              {apiHealth === "ok"
                ? "RUN LIVE SCIENTIFIC INCIDENT"
                : playing
                  ? "PLAYING VERIFIED RUN"
                  : "WATCH VERIFIED CHAMPION RUN"}
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

      {!judgeMode && experienceView !== "BRIEF" && <nav className="story-rail" aria-label="Six event-driven investigation stages">
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

      {((!judgeMode && experienceView !== "BRIEF") ||
        (judgeMode && judgePage === "STUDIO" && studioDetailsOpen)) && <section className="operations-grid">
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

      {((!judgeMode && experienceView !== "BRIEF") ||
        (judgeMode && judgePage === "STUDIO")) && (repairEvent || repairOverride) && (
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
                  CANONICAL REFERENCE · {stringValue(linkedCapture.capture_type)} · Dataset
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
            <div className={resumeAllowed || canonicalResumeAllowed ? "complete" : ""}>
              <span>05</span><small>RECOVER</small>
              <strong>{resumeAllowed || canonicalResumeAllowed ? "AUTHORIZED" : "LOCKED"}</strong>
            </div>
          </div>
          {(!judgeMode || studioDetailsOpen) && nativeMLContext.length > 0 && (
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
          {(!judgeMode || studioDetailsOpen) && (stringValue(repairPayload.datahub_incident_urn) ||
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
          {(!judgeMode || studioDetailsOpen) && verificationReceipts.length > 0 && (
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
            <div className="repair-diff" id="repair-patch">
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
                <small>OWNER APPROVAL GATE</small>
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

      {((!judgeMode && experienceView !== "BRIEF") ||
        (judgeMode && judgePage === "STUDIO" && studioDetailsOpen)) && <section className="control-deck">
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

      {((!judgeMode && experienceView === "AUDIT") ||
        (judgeMode && judgePage === "EVIDENCE")) && <section className="evaluation-theatre panel">
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
        <div className="footer-meta"><span>{latestEvent ? `${playbackState} · evidence stream verified` : "Preparing verified evidence"}</span><span>All demo data is deterministic and synthetic</span><span>DataHub-powered</span></div>
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
                  <strong>REPAIR BUNDLE · REVIEWABLE PATCH</strong>
                  <span>
                    {stringValue(drawerGitHubChange.bundle_id)} · {stringArray(
                      drawerGitHubChange.changed_files,
                    ).length || 5} changed files
                  </span>
                  <span>
                    {stringArray(drawerGitHubChange.changed_files).join(" · ")}
                  </span>
                </div>
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
