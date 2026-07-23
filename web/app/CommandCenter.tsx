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

const CONFIGURED_API_BASE = process.env.NEXT_PUBLIC_SCIGUARD_API_URL ?? "";
const STATIC_JUDGE_BUILD =
  process.env.NEXT_PUBLIC_SCIGUARD_JUDGE_BUILD === "true";
const REPLAY_ID = "inc-wp6-flagship";
const REPLAY_DURATION_MS = 15_000;
const REPLAY_EVENT_DISCLOSURE =
  "38 immutable events: 35 events reach recovery lock, followed by 3 verified recovery events.";
const LOCAL_API_BASE = STATIC_JUDGE_BUILD ? "" : "http://127.0.0.1:8000";
const LOCAL_DATAHUB_BASE = STATIC_JUDGE_BUILD ? "" : "http://localhost:9002";

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
    search_only_recall: 83.3,
    search_only_exact_cones: "0/3",
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

const actorLabels: Record<string, string> = {
  SYSTEM: "System",
  SENTINEL: "Sentinel",
  COORDINATOR: "Coordinator",
  SCIENTIFIC_INVESTIGATOR: "Scientific Investigator",
  REALITY_CHECKER: "Reality Checker",
  POLICY_GUARDIAN: "Policy Guardian",
  ENFORCER: "Enforcer",
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

function storyBeat(events: SciGuardEvent[]): number {
  if (!events.some((event) => event.event_type === "SIGNAL_DETECTED")) return 1;
  if (!events.some((event) => event.event_type === "HYPOTHESIS_PROPOSED")) return 1;
  if (!events.some((event) => event.event_type === "HYPOTHESIS_RESOLVED")) return 2;
  if (!events.some((event) => event.event_type === "IMPACT_MAPPED")) return 3;
  if (!events.some((event) => numberValue(event.payload.exit_code, -1) === 42)) return 4;
  if (!events.some((event) => event.event_type === "INCIDENT_RESOLVED")) return 5;
  return 6;
}

function EvidenceLink({
  id,
  onSelect,
}: {
  id: string;
  onSelect: (id: string) => void;
}) {
  return (
    <button className="evidence-link" onClick={() => onSelect(id)} type="button">
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
  const [localDataHubEnabled, setLocalDataHubEnabled] = useState(false);
  const eventSource = useRef<EventSource | null>(null);

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
    const [manifestResponse, eventsResponse] = await Promise.all([
      fetch(`/replays/${REPLAY_ID}/manifest.json`, { cache: "no-store" }),
      fetch(`/replays/${REPLAY_ID}/events.jsonl`, { cache: "no-store" }),
    ]);
    if (!manifestResponse.ok || !eventsResponse.ok) {
      throw new Error("Recorded replay bundle is unavailable");
    }
    const replayManifest = (await manifestResponse.json()) as RunManifest;
    const rawEvents = await eventsResponse.text();
    const replayEvents = await verifyReplayBundle(replayManifest, rawEvents);
    setManifest(replayManifest);
    setEvents(replayEvents);
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
  const beat = storyBeat(visibleEvents);
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

  const evidence = useMemo(() => {
    const records = new Map<string, EvidenceRecord>();
    records.set(evaluationEvidence.evidence_id, evaluationEvidence);
    records.set(dataHubCapabilityEvidence.evidence_id, dataHubCapabilityEvidence);
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
  }, [visibleEvents]);

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
    localDataHubEnabled && selectedUrn
      ? `${LOCAL_DATAHUB_BASE}/dataset/${encodeURIComponent(selectedUrn)}`
      : null;

  return (
    <main className="command-center">
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

      <section className="runtime-strip" aria-label="Runtime and replay status">
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
      </section>

      <section className="hero-section" aria-labelledby="incident-title">
        <div className="hero-copy">
          <div className="eyebrow"><span>INCIDENT SIGNAL</span><i /> POLYMER R&amp;D · DECISION REPORT</div>
          <h1 id="incident-title">A model succeeded.<br /><em>The science did not.</em></h1>
          <p>
            Candidate P-204 jumped to the top of the selection list while every pipeline
            reported success. SciGuard traced the decision backward through DataHub before
            the morning research meeting.
          </p>
          <div className="hero-meta">
            <EvidenceLink id={rankEvidence} onSelect={setSelectedEvidence} />
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
      </section>

      <section className="eligibility-strip" aria-label="DataHub qualification proof">
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
        <EvidenceLink id={dataHubCapabilityEvidence.evidence_id} onSelect={setSelectedEvidence} />
      </section>

      <nav className="story-rail" aria-label="Six story beats">
        {[
          "Signal",
          "Hypotheses",
          "Field proof",
          "Containment",
          "Recovery",
          "Proof",
        ].map((label, index) => (
          <div className={beat >= index + 1 ? "beat active" : "beat"} key={label}>
            <span>{String(index + 1).padStart(2, "0")}</span><strong>{label}</strong>
          </div>
        ))}
        <div className="playback-actions">
          <span className={`playback-state state-${playbackState.toLowerCase()}`} aria-live="polite">
            {playbackState}
          </span>
        </div>
      </nav>

      <section className="operations-grid">
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
                    {event.evidence_ids.slice(0, 2).map((id) => <EvidenceLink id={id} key={id} onSelect={setSelectedEvidence} />)}
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
            <EvidenceLink id={impactEvidence} onSelect={setSelectedEvidence} />
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
                  <button className={`lineage-node compact ${nodeClass(name)}`} onClick={() => setSelectedEvidence(assetReceiptId(name))} key={name} type="button">
                    <small>{name.includes("model") ? "MODEL" : name.includes("report") ? "DECISION REPORT" : "FEATURE TABLE"}</small>
                    <strong>{formatName(name)}</strong><span>View public DataHub evidence receipt</span>
                  </button>
                ))}
              </div>
              <div className="branch healthy-branch">
                <div className="branch-title"><span>PRESERVED MW PATH</span><StatusMark status={impactEvent ? "ALLOW" : "PENDING"} /></div>
                {["molecular_weight_feature_table", "durability_model", "formulation_report"].map((name) => (
                  <button className={`lineage-node compact ${nodeClass(name)}`} onClick={() => setSelectedEvidence(assetReceiptId(name))} key={name} type="button">
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
            <button onClick={() => setSelectedEvidence(unitEvidence)} type="button"><small>UNIT VIOLATIONS</small><strong>{evidence.has(unitEvidence) ? "187" : "—"}</strong><span>B042 rows · K vs °C</span></button>
            <button onClick={() => setSelectedEvidence(unitEvidence)} type="button"><small>FIRMWARE</small><strong>{evidence.has(unitEvidence) ? "v4.2" : "—"}</strong><span>trusted release · v4.1</span></button>
            <button onClick={() => setSelectedEvidence(modelEvidence)} type="button"><small>MODEL DRIFT</small><strong>{evidence.has(modelEvidence) ? "NONE" : "—"}</strong><span>tg-gbr-v3 unchanged</span></button>
            <button onClick={() => setSelectedEvidence(experimentEvidence)} type="button"><small>TRUE Tg DELTA</small><strong>{evidence.has(experimentEvidence) ? "0.0°" : "—"}</strong><span>after correct conversion</span></button>
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
      </section>

      <section className="control-deck">
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
          {blockedEvent?.evidence_ids[0] && <EvidenceLink id={blockedEvent.evidence_ids[0]} onSelect={setSelectedEvidence} />}
        </article>

        <article className="panel recovery-panel">
          <div className="panel-heading"><div><span className="kicker">RECOVERY GATE</span><h2>Evidence before resume</h2></div><StatusMark status={resumeAllowed ? "RESOLVED" : recoveryEvent ? "LOCKED" : "PENDING"} /></div>
          <div className="recovery-list">
            {RECOVERY_CHECKS.map((check) => {
              const known = Boolean(recoveryEvent);
              const failed = failedChecks.has(check);
              const passed = known && !failed;
              return <div className={failed ? "recovery-check failed" : passed ? "recovery-check passed" : "recovery-check"} key={check}><span>{failed ? "×" : passed ? "✓" : "○"}</span><strong>{formatName(check)}</strong><small>{failed ? "FAIL" : passed ? "PASS" : "WAITING"}</small></div>;
            })}
          </div>
          <div className="recovery-footer"><div><small>CLEAN RUNS</small><strong>{cleanRunCount} / 2</strong></div><div><small>RESUME</small><strong>{resumeAllowed ? "AUTHORIZED" : "LOCKED"}</strong></div></div>
          <p>Frontend state cannot unlock recovery. This surface only renders integrity-checked event results from the deterministic controller.</p>
        </article>
      </section>

      <section className="evaluation-theatre panel">
        <div className="evaluation-intro">
          <span className="kicker">EVALUATION THEATRE</span>
          <h2>DataHub changes the decision boundary.</h2>
          <p>Same labelled incidents. Different context. Only full lineage recovers every exact downstream cone.</p>
          <EvidenceLink id={evaluationEvidence.evidence_id} onSelect={setSelectedEvidence} />
        </div>
        <div className="evaluation-modes">
          <div className="evaluation-card unavailable"><div className="mode-title"><span>01</span><strong>NO DATAHUB CONTEXT</strong></div><div className="metric-large">NOT YET MEASURED</div><p>WP9 will execute a backend that fails on every DataHub call. No metric is invented here.</p><StatusMark status="PENDING WP9" /></div>
          <div className="evaluation-card search"><div className="mode-title"><span>02</span><strong>SEARCH-ONLY DATAHUB</strong></div><div className="metric-pair"><div><strong>60%</strong><span>precision</span></div><div><strong>83.3%</strong><span>recall</span></div></div><p>Without lineage direction · exact cone 0/3</p><StatusMark status="INCOMPLETE CONTEXT" /></div>
          <div className="evaluation-card full"><div className="mode-title"><span>03</span><strong>FULL DATAHUB LINEAGE</strong></div><div className="metric-pair"><div><strong>100%</strong><span>precision</span></div><div><strong>100%</strong><span>recall</span></div></div><p>Field lineage + owners + governance · exact cone 3/3</p><StatusMark status="VERIFIED" /></div>
        </div>
      </section>

      <footer className="site-footer">
        <div><span className="brand-mini">SG</span><strong>Trust the decision because you can inspect the evidence.</strong></div>
        <div className="footer-meta"><span>{latestEvent ? `Latest · ${latestEvent.event_type}` : "Awaiting events"}</span><span>All demo data is deterministic and synthetic</span><span>DataHub-powered</span></div>
      </footer>
    </main>
  );
}
