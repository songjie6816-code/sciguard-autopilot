export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export type RunMode = "LIVE" | "RECORDED_REPLAY";

export interface SciGuardEvent {
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

export interface RunManifest {
  incident_id: string;
  mode: RunMode;
  status: "RUNNING" | "COMPLETED" | "FAILED";
  incident_state: string;
  datahub_backend: string;
  source_commit: string;
  source_worktree_dirty: boolean;
  generated_at: string;
  event_count: number;
  events_sha256: string;
}

export interface EventFrame {
  mode: RunMode;
  event: SciGuardEvent;
}

export interface EvidenceRecord {
  evidence_id: string;
  source: string;
  kind: string;
  summary: string;
  payload: Record<string, JsonValue>;
}
