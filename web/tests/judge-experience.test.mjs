import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  DATAHUB_CAPABILITY_BOUNDARY,
  DATAHUB_DECISION_EXPLANATION,
  JUDGE_STAGES,
  WHY_DATAHUB_RESULTS,
  stageIndexFromEvents,
} from "../app/judge-experience.mjs";

const replayUrl = new URL(
  "../public/replays/inc-wp6-flagship/events.jsonl",
  import.meta.url,
);

async function replayEvents() {
  return (await readFile(replayUrl, "utf8"))
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line));
}

test("six Judge stages are driven by the existing immutable event sequence", async () => {
  const events = await replayEvents();
  assert.deepEqual(
    JUDGE_STAGES.map((stage) => stage.label),
    [
      "DETECT",
      "INVESTIGATE",
      "TRACE IMPACT",
      "DECIDE",
      "ENFORCE",
      "VERIFY RECOVERY",
    ],
  );
  assert.equal(stageIndexFromEvents(events.slice(0, 1)), 0);
  assert.equal(stageIndexFromEvents(events.slice(0, 6)), 1);
  assert.equal(stageIndexFromEvents(events.slice(0, 14)), 2);
  assert.equal(stageIndexFromEvents(events.slice(0, 15)), 3);
  assert.equal(stageIndexFromEvents(events.slice(0, 26)), 4);
  assert.equal(stageIndexFromEvents(events.slice(0, 36)), 5);
  assert.equal(stageIndexFromEvents(events), 5);
  assert.equal(events.length, 38);
  assert.equal(events.at(-1).event_type, "INCIDENT_RESOLVED");
  assert.deepEqual(
    events.map((_, index) => stageIndexFromEvents(events.slice(0, index + 1))),
    [
      ...Array(5).fill(0),
      ...Array(8).fill(1),
      2,
      ...Array(11).fill(3),
      ...Array(10).fill(4),
      ...Array(3).fill(5),
    ],
  );
});

test("unknown later events cannot make an achieved stage regress", async () => {
  const events = await replayEvents();
  const throughImpact = events.slice(0, 14);
  const afterUnknown = [
    ...throughImpact,
    {
      event_type: "FUTURE_PRESENTATION_EVENT",
      sequence: 999,
      payload: {},
    },
  ];
  const afterRecoveryUnknown = [
    ...events,
    {
      event_type: "FUTURE_PRESENTATION_EVENT",
      sequence: 1000,
      payload: {},
    },
  ];

  assert.equal(stageIndexFromEvents(throughImpact), 2);
  assert.equal(stageIndexFromEvents(afterUnknown), 2);
  assert.equal(stageIndexFromEvents(afterRecoveryUnknown), 5);
});

test("Why DataHub labels only the measured evaluation arms", () => {
  const full = WHY_DATAHUB_RESULTS.find((result) => result.id === "full-lineage");
  const search = WHY_DATAHUB_RESULTS.find((result) => result.id === "search-only");
  const none = WHY_DATAHUB_RESULTS.find((result) => result.id === "no-datahub");

  assert.deepEqual(
    {
      precision: full.precision,
      recall: full.recall,
      f1: full.f1,
      exactCone: full.exactCone,
    },
    { precision: "100%", recall: "100%", f1: "100%", exactCone: "3/3" },
  );
  assert.deepEqual(
    {
      precision: search.precision,
      recall: search.recall,
      f1: search.f1,
      exactCone: search.exactCone,
    },
    { precision: "60%", recall: "83.3%", f1: "69.8%", exactCone: "0/3" },
  );
  assert.equal(none.status, "NOT YET MEASURED");
  assert.equal(search.label, "SEARCH-ONLY DATAHUB");
  assert.notEqual(search.label, "NO DATAHUB");
  assert.equal(
    DATAHUB_DECISION_EXPLANATION,
    "Search can find similar names; directed lineage proves the exact downstream decision cone.",
  );
  assert.match(DATAHUB_CAPABILITY_BOUNDARY, /MCP provides schema, unit, ownership/);
  assert.match(DATAHUB_CAPABILITY_BOUNDARY, /SDK fallback/);
});

test("Evidence Drawer states the public integrity and hosted-link boundaries", async () => {
  const source = await readFile(
    new URL("../app/CommandCenter.tsx", import.meta.url),
    "utf8",
  );
  const styles = await readFile(
    new URL("../app/globals.css", import.meta.url),
    "utf8",
  );
  for (const label of [
    "Evidence type",
    "Incident ID",
    "Immutable event ID / sequence",
    "DataHub URN",
    "Affected field",
    "Downstream impact",
    "Policy rule",
    "Enforcement action",
    "Provenance / backend",
  ]) {
    assert.match(source, new RegExp(label));
  }
  assert.match(source, /internal consistency of the packaged replay/);
  assert.match(source, /not a\s+digital signature and not proof of origin/);
  assert.match(source, /event\.key === "Escape"/);
  assert.match(source, /button:not\(\[disabled\]\), summary/);
  assert.match(source, /EXACT CONE · 3\/3 WITH LINEAGE → 0\/3 SEARCH-ONLY/);
  assert.match(source, /NO DATAHUB · NOT YET MEASURED/);
  assert.match(styles, /\.drawer-facts dt[^}]*11px/);
  assert.match(styles, /\.drawer-facts dd[^}]*13px/);
  assert.match(styles, /\.drawer-integrity p[^}]*11px/);
  assert.match(styles, /\.drawer-payload summary[^}]*11px/);
});
