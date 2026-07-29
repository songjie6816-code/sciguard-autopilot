const CANONICAL = {
  sourceCommit: "943719220dc231099436130207ec2260d17621d7",
  incidentId: "inc-sciguard-b042-unit-contract",
  bundleId: "repair-bundle:301bd0a4d7b8f086",
  repairCommit: "ea1a4760520fcb299d8b8f73d955e5c66cc03ee3",
  pullRequest: "https://github.com/songjie6816-code/sciguard-repair-sandbox/pull/2",
  dataHubServer: "v1.5.0.6",
  dataHubEntityCount: 19,
  dataHubReceiptSha:
    "915a76c0fa690890f0848ad775d12f06f0cd29082d966e8c40b33175912cb95f",
} as const;

const FIXED_SCENARIO = "KELVIN_CELSIUS_B042";
const RATE_WINDOW_MS = 10 * 60 * 1000;
const RATE_LIMIT = 3;
const CLIENT_RATE_LIMIT = 12;
const MAX_RUNS = 20;
const EVENT_DELAY_MS = 320;
const STALE_RUN_MS = 20_000;

type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

interface SciGuardEvent {
  event_id: string;
  incident_id: string;
  sequence: number;
  timestamp: string;
  actor: string;
  event_type: string;
  summary: string;
  evidence_ids: string[];
  duration_ms: number;
  payload: Record<string, JsonValue>;
}

interface RunManifest {
  incident_id: string;
  mode: "LIVE";
  status: "RUNNING" | "COMPLETED" | "FAILED";
  incident_state: string;
  datahub_backend: "VERIFIED_DATAHUB_READBACK_SNAPSHOT";
  source_commit: string;
  source_worktree_dirty: false;
  generated_at: string;
  event_count: number;
  events_sha256: string;
}

interface StoredRun {
  manifest: RunManifest;
  sessionHash: string;
  idempotencyKey: string;
  createdAt: number;
  started: boolean;
  events: SciGuardEvent[];
}

interface SandboxState {
  runs: Record<string, StoredRun>;
  sessionAttempts: Record<string, number[]>;
  idempotency: Record<string, string>;
}

interface DurableStorage {
  get<T>(key: string): Promise<T | undefined>;
  put<T>(key: string, value: T): Promise<void>;
}

interface DurableObjectState {
  storage: DurableStorage;
}

type DurableObjectId = object;

interface DurableObjectStub {
  fetch(request: Request): Promise<Response>;
}

interface DurableObjectNamespace {
  idFromName(name: string): DurableObjectId;
  get(id: DurableObjectId): DurableObjectStub;
}

interface Env {
  LIVE_SANDBOX: DurableObjectNamespace;
  SCIGUARD_ALLOWED_ORIGINS?: string;
}

interface ExecutionContext {
  waitUntil(promise: Promise<unknown>): void;
}

function jsonResponse(
  body: unknown,
  status = 200,
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

function errorResponse(status: number, code: string, detail: string): Response {
  return jsonResponse({ error: code, detail }, status);
}

function allowedOrigins(env: Env): Set<string> {
  return new Set(
    (
      env.SCIGUARD_ALLOWED_ORIGINS ??
      "https://sciguard-autopilot-demo.pages.dev,http://localhost:4173,http://127.0.0.1:4173"
    )
      .split(",")
      .map((origin) => origin.trim())
      .filter(Boolean),
  );
}

function withCors(response: Response, origin: string | null, env: Env): Response {
  const headers = new Headers(response.headers);
  if (origin && allowedOrigins(env).has(origin)) {
    headers.set("Access-Control-Allow-Origin", origin);
    headers.set("Vary", "Origin");
  }
  headers.set("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  headers.set(
    "Access-Control-Allow-Headers",
    "Content-Type, Idempotency-Key, X-SciGuard-Session",
  );
  headers.set("Access-Control-Max-Age", "86400");
  headers.set("Referrer-Policy", "no-referrer");
  headers.set("X-Frame-Options", "DENY");
  headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

async function sha256(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

function randomToken(bytes = 8): string {
  const value = new Uint8Array(bytes);
  crypto.getRandomValues(value);
  return Array.from(value, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function sessionFrom(request: Request): string | null {
  const session = request.headers.get("X-SciGuard-Session")?.trim() ?? "";
  return /^[A-Za-z0-9_-]{16,80}$/.test(session) ? session : null;
}

function canonicalJson(value: JsonValue): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .map(
        (key) =>
          `${JSON.stringify(key)}:${canonicalJson(
            (value as Record<string, JsonValue>)[key],
          )}`,
      )
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function liveScientificCalculation(): Record<string, JsonValue> {
  const rows = Array.from({ length: 187 }, (_, index) => {
    const kelvin = 420 + (index % 17) * 0.75;
    return {
      sample: `B042-${String(index + 1).padStart(3, "0")}`,
      raw: kelvin,
      normalized: Number((kelvin - 273.15).toFixed(2)),
    };
  });
  const violations = rows.filter(
    (row) => Math.abs(row.raw - row.normalized) > 273,
  );
  const trustedScores = Array.from({ length: 18 }, (_, index) => ({
    candidate: index === 17 ? "P-204" : `P-${String(index + 1).padStart(3, "0")}`,
    score: index + 1,
  }));
  const unsafeScores = trustedScores.map((candidate) => ({
    ...candidate,
    score: candidate.candidate === "P-204" ? 0.01 : candidate.score,
  }));
  const rank = (
    candidates: Array<{ candidate: string; score: number }>,
    candidate: string,
  ) =>
    [...candidates].sort((left, right) => left.score - right.score).findIndex(
      (item) => item.candidate === candidate,
    ) + 1;
  return {
    calculated_at: new Date().toISOString(),
    row_count: rows.length,
    violating_rows: violations.length,
    raw_unit: "K",
    expected_unit: "degC",
    conversion: "degC = K - 273.15",
    unsafe_rank: rank(unsafeScores, "P-204"),
    trusted_rank: rank(trustedScores, "P-204"),
    sample_sha256_input: canonicalJson(rows.slice(0, 5)),
  };
}

function traverseDecisionGraph(): Record<string, JsonValue> {
  const graph: Record<string, string[]> = {
    tg_value: ["experimental_data"],
    experimental_data: ["tg_feature_table", "molecular_weight_feature_table"],
    tg_feature_table: ["tg_prediction_production"],
    tg_prediction_production: [
      "candidate_ranking",
      "research_meeting",
      "tg_decision_dashboard",
    ],
    molecular_weight_feature_table: ["durability_production"],
    durability_production: ["formulation_report"],
    candidate_ranking: [],
    research_meeting: [],
    tg_decision_dashboard: [],
    formulation_report: [],
  };
  const fieldLineage: Record<string, string[]> = {
    tg_value: ["experimental_data", "tg_feature_table"],
    tg_feature_table: [
      "tg_prediction_production",
      "candidate_ranking",
      "research_meeting",
      "tg_decision_dashboard",
    ],
  };
  const affected = new Set<string>(["experimental_data"]);
  const queue = [...fieldLineage.tg_value];
  while (queue.length) {
    const current = queue.shift();
    if (!current || affected.has(current)) continue;
    affected.add(current);
    for (const next of fieldLineage[current] ?? []) queue.push(next);
  }
  const all = new Set(Object.keys(graph).filter((node) => node !== "tg_value"));
  const preserved = [...all].filter((node) => !affected.has(node));
  return {
    source: "MODULE_1_VERIFIED_DATAHUB_READBACK",
    source_incident_id: CANONICAL.incidentId,
    receipt_sha256: CANONICAL.dataHubReceiptSha,
    server_version: CANONICAL.dataHubServer,
    verified_entity_count: CANONICAL.dataHubEntityCount,
    affected_names: [...affected],
    unaffected_names: preserved,
    affected_urns: [...affected].map(
      (name) => `urn:li:dataset:(urn:li:dataPlatform:polymer_rnd,${name},PROD)`,
    ),
    unaffected_urns: preserved.map(
      (name) => `urn:li:dataset:(urn:li:dataPlatform:polymer_rnd,${name},PROD)`,
    ),
  };
}

function eventTemplates(
  incidentId: string,
  scientific: Record<string, JsonValue>,
  context: Record<string, JsonValue>,
  bundleId: string,
): Array<Omit<SciGuardEvent, "event_id" | "incident_id" | "sequence" | "timestamp">> {
  const affectedNames = context.affected_names as string[];
  const unaffectedNames = context.unaffected_names as string[];
  const affectedUrns = context.affected_urns as string[];
  const unaffectedUrns = context.unaffected_urns as string[];
  const commonEvidence = [
    "unit-firmware-contract:711d085fe8869ed0",
    "rank-baseline-comparison:55a5b1ad73eb48b1",
  ];
  return [
    {
      actor: "SENTINEL",
      event_type: "SIGNAL_DETECTED",
      summary: "Live calculation found 187 Kelvin values violating the Celsius contract",
      evidence_ids: commonEvidence,
      duration_ms: 24,
      payload: {
        ...scientific,
        pipeline_status: "SUCCESS",
        initial_scope: ["B042", "experimental_data"],
      },
    },
    {
      actor: "COORDINATOR",
      event_type: "INCIDENT_CREATED",
      summary: "Created an isolated public sandbox incident",
      evidence_ids: [],
      duration_ms: 2,
      payload: {
        from_state: "NEW",
        to_state: "INVESTIGATING",
        fixed_scenario: FIXED_SCENARIO,
        arbitrary_repository_writes: false,
      },
    },
    {
      actor: "SCIENTIFIC_INVESTIGATOR",
      event_type: "EVIDENCE_OBSERVED",
      summary: "Retrieved the verified DataHub context snapshot and checked its binding",
      evidence_ids: ["datahub-live-receipt:inc-sciguard-b042-unit-contract"],
      duration_ms: 18,
      payload: {
        context_source: context.source,
        receipt_sha256: context.receipt_sha256,
        verified_entity_count: context.verified_entity_count,
        data_freshness_boundary:
          "Module 1 verified read-back; this edge run does not claim a fresh GMS query",
      },
    },
    {
      actor: "SCIENTIFIC_INVESTIGATOR",
      event_type: "HYPOTHESIS_PROPOSED",
      summary: "Proposed an upstream Kelvin/Celsius unit-contract regression",
      evidence_ids: commonEvidence,
      duration_ms: 3,
      payload: {
        hypothesis_id: "H-UNIT-CONTRACT",
        candidate_cause: "instrument_firmware_unit_change",
      },
    },
    {
      actor: "REALITY_CHECKER",
      event_type: "HYPOTHESIS_RESOLVED",
      summary: "Confirmed unit drift explains the unsafe P-204 rank inversion",
      evidence_ids: commonEvidence,
      duration_ms: 15,
      payload: {
        hypothesis_id: "H-UNIT-CONTRACT",
        status: "CONFIRMED",
        unsafe_rank: scientific.unsafe_rank,
        trusted_rank: scientific.trusted_rank,
      },
    },
    {
      actor: "COORDINATOR",
      event_type: "IMPACT_MAPPED",
      summary: "Field lineage separated six affected assets from three preserved assets",
      evidence_ids: ["field-impact:6d7265f6ecc4d6e1"],
      duration_ms: 21,
      payload: {
        affected_names: affectedNames,
        unaffected_names: unaffectedNames,
        affected_urns: affectedUrns,
        unaffected_urns: unaffectedUrns,
        traversal: "DIRECTED_FIELD_LINEAGE",
        context_receipt_sha256: context.receipt_sha256,
      },
    },
    {
      actor: "POLICY_GUARDIAN",
      event_type: "POLICY_DECIDED",
      summary: "HALT the high-criticality candidate-ranking publication",
      evidence_ids: ["field-impact:6d7265f6ecc4d6e1"],
      duration_ms: 4,
      payload: {
        asset_name: "candidate_ranking",
        decision: "HALT",
        rule: "AFFECTED && BUSINESS_CRITICALITY=HIGH",
        owner: "polymer-ml-platform",
      },
    },
    {
      actor: "POLICY_GUARDIAN",
      event_type: "POLICY_DECIDED",
      summary: "ALLOW the preserved molecular-weight formulation report",
      evidence_ids: ["field-impact:6d7265f6ecc4d6e1"],
      duration_ms: 4,
      payload: {
        asset_name: "formulation_report",
        decision: "ALLOW",
        rule: "OUTSIDE_AFFECTED_FIELD_CONE",
        owner: "formulation-science",
      },
    },
    {
      actor: "REMEDIATION_AGENT",
      event_type: "REPAIR_BUNDLE_CREATED",
      summary: "Generated a metadata-aware repair bundle for this isolated run",
      evidence_ids: [
        "unit-firmware-contract:711d085fe8869ed0",
        "field-impact:6d7265f6ecc4d6e1",
      ],
      duration_ms: 28,
      payload: {
        incident_id: incidentId,
        bundle_id: bundleId,
        status: "PROPOSED",
        artifacts: [
          {
            kind: "CODE_PATCH",
            path: "pipeline/normalize.py",
            summary: "Normalize Kelvin to Celsius before feature computation",
          },
          {
            kind: "TEST",
            path: "tests/test_unit_contract.py",
            summary: "Reject unnormalized B042 values",
          },
        ],
        metadata_inputs: {
          ownership: ["polymer-ml-platform", "formulation-science"],
          governance: "SCIENTIFIC_DECISION_SAFETY",
          criticality: "HIGH",
          field_lineage_receipt: context.receipt_sha256,
        },
        external_action: {
          mode: "CANONICAL_EXTERNAL_ACTION_RESOLVED",
          canonical_bundle_id: CANONICAL.bundleId,
          pull_request_url: CANONICAL.pullRequest,
          verified_commit_sha: CANONICAL.repairCommit,
          new_pull_request_created: false,
        },
        production_authorized: false,
      },
    },
    {
      actor: "ENFORCER",
      event_type: "ENFORCEMENT_APPLIED",
      summary: "Blocked the unsafe candidate-ranking publication",
      evidence_ids: ["field-impact:6d7265f6ecc4d6e1"],
      duration_ms: 5,
      payload: {
        asset_name: "candidate_ranking",
        decision: "HALT",
        exit_code: 42,
        target_created: false,
      },
    },
    {
      actor: "ENFORCER",
      event_type: "ENFORCEMENT_APPLIED",
      summary: "Allowed the independent formulation report to continue",
      evidence_ids: ["field-impact:6d7265f6ecc4d6e1"],
      duration_ms: 5,
      payload: {
        asset_name: "formulation_report",
        decision: "ALLOW",
        exit_code: 0,
        target_created: true,
      },
    },
    {
      actor: "COORDINATOR",
      event_type: "DECISION_LOG_WRITTEN",
      summary: "Recorded the live calculation and canonical external-action boundary",
      evidence_ids: [
        "datahub-live-receipt:inc-sciguard-b042-unit-contract",
        "github-live-evidence:inc-sciguard-b042-unit-contract",
      ],
      duration_ms: 6,
      payload: {
        from_state: "ENFORCING",
        to_state: "ENFORCED",
        external_write: false,
        read_only_public_sandbox: true,
        canonical_pull_request: CANONICAL.pullRequest,
      },
    },
  ];
}

async function buildEvents(incidentId: string): Promise<SciGuardEvent[]> {
  const scientific = liveScientificCalculation();
  const context = traverseDecisionGraph();
  const bundleDigest = await sha256(
    canonicalJson({
      incident_id: incidentId,
      scenario: FIXED_SCENARIO,
      violations: scientific.violating_rows,
      context_receipt: context.receipt_sha256,
      canonical_repair_commit: CANONICAL.repairCommit,
    }),
  );
  const bundleId = `repair-bundle:${bundleDigest.slice(0, 16)}`;
  return eventTemplates(incidentId, scientific, context, bundleId).map(
    (event, sequence) => ({
      ...event,
      event_id: `${incidentId}:${String(sequence).padStart(4, "0")}:${event.event_type}`,
      incident_id: incidentId,
      sequence,
      timestamp: new Date().toISOString(),
    }),
  );
}

function emptyState(): SandboxState {
  return { runs: {}, sessionAttempts: {}, idempotency: {} };
}

function sseFrame(event: SciGuardEvent): Uint8Array {
  return new TextEncoder().encode(
    `id: ${event.sequence}\nevent: sciguard-event\ndata: ${JSON.stringify({
      mode: "LIVE",
      event,
    })}\n\n`,
  );
}

function completeFrame(manifest: RunManifest): Uint8Array {
  return new TextEncoder().encode(
    `event: sciguard-complete\ndata: ${JSON.stringify({ manifest })}\n\n`,
  );
}

function sleep(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

export class LiveSandbox {
  constructor(private readonly state: DurableObjectState) {}

  private async readState(): Promise<SandboxState> {
    return (await this.state.storage.get<SandboxState>("sandbox")) ?? emptyState();
  }

  private async writeState(value: SandboxState): Promise<void> {
    await this.state.storage.put("sandbox", value);
  }

  private async handleCreate(request: Request): Promise<Response> {
    const session = sessionFrom(request);
    if (!session) {
      return errorResponse(400, "INVALID_SESSION", "A bounded browser session is required.");
    }
    const contentLength = Number(request.headers.get("Content-Length") ?? "0");
    if (contentLength > 1024) {
      return errorResponse(413, "PAYLOAD_TOO_LARGE", "The fixed scenario accepts no custom data.");
    }
    let body: { scenario?: unknown };
    try {
      body = (await request.json()) as { scenario?: unknown };
    } catch {
      return errorResponse(400, "INVALID_JSON", "Request body must be JSON.");
    }
    if (body.scenario !== undefined && body.scenario !== FIXED_SCENARIO) {
      return errorResponse(
        400,
        "FIXED_SCENARIO_ONLY",
        `Only ${FIXED_SCENARIO} is available in the public sandbox.`,
      );
    }

    const sessionHash = (await sha256(session)).slice(0, 24);
    const clientAddress = request.headers.get("CF-Connecting-IP") ?? "local-client";
    const clientHash = (await sha256(clientAddress)).slice(0, 24);
    const idempotencyKey =
      request.headers.get("Idempotency-Key")?.trim() || `auto-${randomToken()}`;
    if (!/^[A-Za-z0-9._:-]{8,100}$/.test(idempotencyKey)) {
      return errorResponse(400, "INVALID_IDEMPOTENCY_KEY", "Invalid idempotency key.");
    }
    const storage = await this.readState();
    const idempotencyStorageKey = `${sessionHash}:${idempotencyKey}`;
    const existingId = storage.idempotency[idempotencyStorageKey];
    if (existingId && storage.runs[existingId]) {
      return jsonResponse(
        { manifest: storage.runs[existingId].manifest, idempotent_replay: true },
        200,
      );
    }
    const now = Date.now();
    const attempts = (storage.sessionAttempts[sessionHash] ?? []).filter(
      (attempt) => now - attempt < RATE_WINDOW_MS,
    );
    const clientRateKey = `client:${clientHash}`;
    const clientAttempts = (storage.sessionAttempts[clientRateKey] ?? []).filter(
      (attempt) => now - attempt < RATE_WINDOW_MS,
    );
    if (attempts.length >= RATE_LIMIT) {
      return errorResponse(
        429,
        "RATE_LIMITED",
        "This browser session has used its three live runs for the ten-minute window.",
      );
    }
    if (clientAttempts.length >= CLIENT_RATE_LIMIT) {
      return errorResponse(
        429,
        "CLIENT_RATE_LIMITED",
        "This anonymous client has reached the bounded live-compute limit.",
      );
    }
    for (const run of Object.values(storage.runs)) {
      if (
        run.manifest.status === "RUNNING" &&
        now - run.createdAt > STALE_RUN_MS
      ) {
        run.manifest.status = "FAILED";
        run.manifest.incident_state = "TIMED_OUT";
        run.manifest.generated_at = new Date(now).toISOString();
      }
    }
    if (
      Object.values(storage.runs).some(
        (run) => run.manifest.status === "RUNNING",
      )
    ) {
      return errorResponse(
        409,
        "SANDBOX_BUSY",
        "A bounded live run is already executing. Retry shortly or watch the verified replay.",
      );
    }

    const incidentId = `inc-live-b042-${now.toString(36)}-${randomToken(4)}`;
    const manifest: RunManifest = {
      incident_id: incidentId,
      mode: "LIVE",
      status: "RUNNING",
      incident_state: "DETECTED",
      datahub_backend: "VERIFIED_DATAHUB_READBACK_SNAPSHOT",
      source_commit: CANONICAL.sourceCommit,
      source_worktree_dirty: false,
      generated_at: new Date(now).toISOString(),
      event_count: 0,
      events_sha256: "",
    };
    storage.runs[incidentId] = {
      manifest,
      sessionHash,
      idempotencyKey,
      createdAt: now,
      started: false,
      events: [],
    };
    storage.sessionAttempts[sessionHash] = [...attempts, now];
    storage.sessionAttempts[clientRateKey] = [...clientAttempts, now];
    storage.idempotency[idempotencyStorageKey] = incidentId;

    const runIds = Object.keys(storage.runs).sort(
      (left, right) => storage.runs[right].createdAt - storage.runs[left].createdAt,
    );
    for (const staleId of runIds.slice(MAX_RUNS)) {
      if (storage.runs[staleId].manifest.status !== "RUNNING") {
        delete storage.runs[staleId];
      }
    }
    await this.writeState(storage);
    return jsonResponse({ manifest, idempotent_replay: false }, 201);
  }

  private async handleRun(incidentId: string): Promise<Response> {
    const storage = await this.readState();
    const run = storage.runs[incidentId];
    return run
      ? jsonResponse({ manifest: run.manifest, events: run.events })
      : errorResponse(404, "RUN_NOT_FOUND", "The isolated run does not exist.");
  }

  private async streamRun(request: Request, incidentId: string): Promise<Response> {
    const url = new URL(request.url);
    const afterSequence = Number(url.searchParams.get("after_sequence") ?? "-1");
    const initialState = await this.readState();
    const initialRun = initialState.runs[incidentId];
    if (!initialRun) {
      return errorResponse(404, "RUN_NOT_FOUND", "The isolated run does not exist.");
    }
    const shouldExecute = !initialRun.started;
    if (shouldExecute) {
      initialRun.started = true;
      await this.writeState(initialState);
    }
    const state = this.state;
    const stream = new ReadableStream<Uint8Array>({
      async start(controller) {
        let lastSent = afterSequence;
        let streamOpen = true;
        const enqueue = (chunk: Uint8Array): void => {
          if (!streamOpen) return;
          try {
            controller.enqueue(chunk);
          } catch {
            streamOpen = false;
          }
        };
        const sendAvailable = async (): Promise<StoredRun | null> => {
          const latestState =
            (await state.storage.get<SandboxState>("sandbox")) ?? emptyState();
          const latestRun = latestState.runs[incidentId] ?? null;
          if (!latestRun) return null;
          for (const event of latestRun.events) {
            if (event.sequence > lastSent) {
              enqueue(sseFrame(event));
              lastSent = event.sequence;
            }
          }
          return latestRun;
        };

        try {
          await sendAvailable();
          if (shouldExecute) {
            const generated = await buildEvents(incidentId);
            for (const event of generated) {
              await sleep(EVENT_DELAY_MS);
              const latestState =
                (await state.storage.get<SandboxState>("sandbox")) ?? emptyState();
              const latestRun = latestState.runs[incidentId];
              if (!latestRun) break;
              latestRun.events.push({ ...event, timestamp: new Date().toISOString() });
              latestRun.manifest.event_count = latestRun.events.length;
              latestRun.manifest.incident_state =
                event.event_type === "DECISION_LOG_WRITTEN"
                  ? "ENFORCED"
                  : event.event_type === "IMPACT_MAPPED"
                    ? "IMPACT_MAPPED"
                    : latestRun.manifest.incident_state;
              await state.storage.put("sandbox", latestState);
              await sendAvailable();
            }
            const finalState =
              (await state.storage.get<SandboxState>("sandbox")) ?? emptyState();
            const finalRun = finalState.runs[incidentId];
            if (finalRun) {
              const jsonl = `${finalRun.events
                .map((event) => JSON.stringify(event))
                .join("\n")}\n`;
              finalRun.manifest.status = "COMPLETED";
              finalRun.manifest.incident_state = "ENFORCED";
              finalRun.manifest.events_sha256 = await sha256(jsonl);
              finalRun.manifest.generated_at = new Date().toISOString();
              await state.storage.put("sandbox", finalState);
              enqueue(completeFrame(finalRun.manifest));
            }
          } else {
            for (let attempt = 0; attempt < 30; attempt += 1) {
              const latestRun = await sendAvailable();
              if (!latestRun || latestRun.manifest.status !== "RUNNING") {
                if (latestRun) enqueue(completeFrame(latestRun.manifest));
                break;
              }
              await sleep(250);
            }
          }
        } catch (error) {
          const failedState =
            (await state.storage.get<SandboxState>("sandbox")) ?? emptyState();
          const failedRun = failedState.runs[incidentId];
          if (failedRun) {
            failedRun.manifest.status = "FAILED";
            failedRun.manifest.incident_state = "FAILED";
            failedRun.manifest.generated_at = new Date().toISOString();
            await state.storage.put("sandbox", failedState);
          }
          enqueue(
            new TextEncoder().encode(
              `event: sciguard-error\ndata: ${JSON.stringify({
                detail: error instanceof Error ? error.message : "Live execution failed",
              })}\n\n`,
            ),
          );
        } finally {
          if (streamOpen) {
            try {
              controller.close();
            } catch {
              streamOpen = false;
            }
          }
        }
      },
    });
    return new Response(stream, {
      headers: {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
        "X-Accel-Buffering": "no",
      },
    });
  }

  private async handleReset(request: Request): Promise<Response> {
    const session = sessionFrom(request);
    if (!session) {
      return errorResponse(400, "INVALID_SESSION", "A bounded browser session is required.");
    }
    let body: { incident_id?: unknown };
    try {
      body = (await request.json()) as { incident_id?: unknown };
    } catch {
      body = {};
    }
    const incidentId = typeof body.incident_id === "string" ? body.incident_id : "";
    if (!incidentId) {
      return errorResponse(400, "INCIDENT_REQUIRED", "Specify the isolated incident to reset.");
    }
    const sessionHash = (await sha256(session)).slice(0, 24);
    const storage = await this.readState();
    const run = storage.runs[incidentId];
    if (!run || run.sessionHash !== sessionHash) {
      return errorResponse(404, "RUN_NOT_FOUND", "No owned isolated run was found.");
    }
    if (run.manifest.status === "RUNNING") {
      return errorResponse(409, "RUN_ACTIVE", "An active run cannot be reset.");
    }
    delete storage.runs[incidentId];
    delete storage.idempotency[`${sessionHash}:${run.idempotencyKey}`];
    await this.writeState(storage);
    return jsonResponse({
      status: "reset",
      incident_id: incidentId,
      rate_limit_window_preserved: true,
    });
  }

  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "POST" && url.pathname === "/api/runs") {
      return this.handleCreate(request);
    }
    const runMatch = url.pathname.match(/^\/api\/runs\/([^/]+)$/);
    if (request.method === "GET" && runMatch) {
      return this.handleRun(decodeURIComponent(runMatch[1]));
    }
    const eventsMatch = url.pathname.match(/^\/api\/runs\/([^/]+)\/events$/);
    if (request.method === "GET" && eventsMatch) {
      return this.streamRun(request, decodeURIComponent(eventsMatch[1]));
    }
    if (request.method === "POST" && url.pathname === "/api/reset") {
      return this.handleReset(request);
    }
    if (
      request.method === "POST" &&
      /^\/api\/runs\/[^/]+\/(repair|recovery)/.test(url.pathname)
    ) {
      return errorResponse(
        403,
        "PUBLIC_SANDBOX_READ_ONLY",
        "The public sandbox computes a repair plan but cannot mutate GitHub, DataHub, or production.",
      );
    }
    return errorResponse(404, "NOT_FOUND", "Unknown bounded sandbox endpoint.");
  }
}

const worker = {
  async fetch(request: Request, env: Env, context: ExecutionContext): Promise<Response> {
    const origin = request.headers.get("Origin");
    if (request.method === "OPTIONS") {
      const response = origin && allowedOrigins(env).has(origin)
        ? new Response(null, { status: 204 })
        : errorResponse(403, "ORIGIN_DENIED", "This origin is not allowed.");
      return withCors(response, origin, env);
    }
    if (request.method === "GET" && new URL(request.url).pathname === "/healthz") {
      return withCors(
        jsonResponse({
          status: "ok",
          service: "sciguard-live-sandbox",
          runtime: "CLOUDFLARE_WORKER_DURABLE_OBJECT",
          scenario: FIXED_SCENARIO,
          capabilities: {
            live_calculation: true,
            server_sent_events: true,
            isolated_state: true,
            reset: true,
            mutating_actions: false,
            arbitrary_repository_writes: false,
          },
          dependencies: {
            run_store: "DURABLE_OBJECT",
            datahub_context: "VERIFIED_MODULE_1_READBACK_SNAPSHOT",
            github_action: "CANONICAL_PR_2_READ_ONLY",
          },
          honesty_boundary:
            "Live scientific computation; DataHub context is a verified read-back snapshot, not a fresh GMS query.",
        }),
        origin,
        env,
      );
    }
    if (request.method !== "GET") {
      if (!origin || !allowedOrigins(env).has(origin)) {
        return withCors(
          errorResponse(403, "ORIGIN_DENIED", "This write-like request origin is not allowed."),
          origin,
          env,
        );
      }
    }
    const id = env.LIVE_SANDBOX.idFromName("global");
    const response = await env.LIVE_SANDBOX.get(id).fetch(request);
    context.waitUntil(Promise.resolve());
    return withCors(response, origin, env);
  },
};

export default worker;
