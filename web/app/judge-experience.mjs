// @ts-check

export const JUDGE_STAGES = [
  {
    id: "detect",
    label: "DETECT",
    purpose: "The scientific contract changes while the pipeline still reports success.",
  },
  {
    id: "investigate",
    label: "INVESTIGATE",
    purpose: "Bounded agents test model drift, upstream drift, and real improvement.",
  },
  {
    id: "trace-impact",
    label: "TRACE IMPACT",
    purpose: "Directed field lineage separates the affected Tg cone from the preserved MW cone.",
  },
  {
    id: "decide",
    label: "DECIDE",
    purpose: "Deterministic policy assigns HALT, WARN, or ALLOW from recorded evidence.",
  },
  {
    id: "enforce",
    label: "ENFORCE",
    purpose: "The controller blocks the unsafe publication and permits the safe branch.",
  },
  {
    id: "verify-recovery",
    label: "VERIFY RECOVERY",
    purpose: "Evidence gates two clean runs before the incident can resolve.",
  },
];

export const WHY_DATAHUB_RESULTS = [
  {
    id: "full-lineage",
    label: "WITH DATAHUB LINEAGE",
    precision: "100%",
    recall: "100%",
    f1: "100%",
    exactCone: "3/3",
    status: "VERIFIED",
  },
  {
    id: "search-only",
    label: "SEARCH-ONLY DATAHUB",
    precision: "60%",
    recall: "83.3%",
    f1: "69.8%",
    exactCone: "0/3",
    status: "INCOMPLETE CONTEXT",
  },
  {
    id: "no-datahub",
    label: "NO DATAHUB",
    precision: "NOT YET MEASURED",
    recall: "NOT YET MEASURED",
    f1: "NOT YET MEASURED",
    exactCone: "NOT YET MEASURED",
    status: "NOT YET MEASURED",
  },
];

const EVENT_STAGE = new Map([
  ["SIGNAL_DETECTED", 0],
  ["ESCALATION_DECIDED", 0],
  ["INCIDENT_CREATED", 0],
  ["HYPOTHESIS_PROPOSED", 1],
  ["EVIDENCE_OBSERVED", 1],
  ["HYPOTHESIS_RESOLVED", 1],
  ["IMPACT_MAPPED", 2],
  ["POLICY_DECIDED", 3],
  ["NOTIFICATION_RECORDED", 3],
  ["ENFORCEMENT_APPLIED", 4],
  ["RECOVERY_CHECKED", 5],
  ["INCIDENT_RESOLVED", 5],
]);

/**
 * Resolve a single immutable event into a presentation stage.
 * STATE_TRANSITIONED is disambiguated by the event sequence recorded in the
 * canonical 38-event incident; no new event or state is generated here.
 *
 * @param {{event_type?: string, sequence?: number, payload?: Record<string, unknown>}} event
 * @returns {number}
 */
export function stageIndexForEvent(event) {
  if (event.event_type === "STATE_TRANSITIONED") {
    return Number(event.sequence ?? 0) >= 34 ? 4 : 0;
  }
  return EVENT_STAGE.get(event.event_type ?? "") ?? 0;
}

/**
 * @param {Array<{event_type?: string, sequence?: number, payload?: Record<string, unknown>}>} events
 * @returns {number}
 */
export function stageIndexFromEvents(events) {
  if (!events.length) return 0;
  return events.reduce(
    (highestStage, event) =>
      Math.max(highestStage, stageIndexForEvent(event)),
    0,
  );
}

export const DATAHUB_DECISION_EXPLANATION =
  "Search can find similar names; directed lineage proves the exact downstream decision cone.";

export const DATAHUB_CAPABILITY_BOUNDARY =
  "MCP provides schema, unit, ownership, governance, and directed dataset lineage reads. Fine-grained lineage and write-back currently use the SDK fallback.";
