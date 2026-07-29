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
  "../public/replays/inc-sciguard-b042-unit-contract/events.jsonl",
  import.meta.url,
);

async function replayEvents() {
  return (await readFile(replayUrl, "utf8"))
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line));
}

test("six Judge stages are driven by the canonical immutable event sequence", async () => {
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
  const through = (eventType) =>
    events.slice(0, events.findIndex((event) => event.event_type === eventType) + 1);
  assert.equal(stageIndexFromEvents(through("SIGNAL_DETECTED")), 0);
  assert.equal(stageIndexFromEvents(through("HYPOTHESIS_PROPOSED")), 1);
  assert.equal(stageIndexFromEvents(through("IMPACT_MAPPED")), 2);
  assert.equal(stageIndexFromEvents(through("POLICY_DECIDED")), 3);
  assert.equal(stageIndexFromEvents(through("REPAIR_BUNDLE_CREATED")), 4);
  assert.equal(stageIndexFromEvents(through("REPAIR_VERIFIED")), 5);
  assert.equal(stageIndexFromEvents(events), 5);
  assert.equal(events.length, 55);
  assert.equal(
    events.filter((event) => event.event_type === "RECOVERY_EVIDENCE_REFRESHED")
      .length,
    2,
  );
  assert.equal(events.some((event) => event.event_type === "REPAIR_APPLIED"), true);
  const stages = events.map((_, index) =>
    stageIndexFromEvents(events.slice(0, index + 1)),
  );
  assert.equal(stages.every((stage, index) => index === 0 || stage >= stages[index - 1]), true);
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
    { precision: "60%", recall: "100%", f1: "75%", exactCone: "0/3" },
  );
  assert.equal(none.status, "MEASURED ABSTENTION");
  assert.equal(none.recall, "0%");
  assert.equal(none.exactCone, "0/3");
  assert.equal(search.label, "SEARCH-ONLY DATAHUB");
  assert.notEqual(search.label, "NO DATAHUB");
  assert.equal(
    DATAHUB_DECISION_EXPLANATION,
    "Search can find similar names; directed lineage proves the exact downstream decision cone.",
  );
  assert.match(DATAHUB_CAPABILITY_BOUNDARY, /MCP provides schema, unit, ownership/);
  assert.match(DATAHUB_CAPABILITY_BOUNDARY, /SDK fallback/);
});

test("Why DataHub UI metrics match the gated machine-readable report", async () => {
  const report = JSON.parse(
    await readFile(
      new URL("../public/evidence/evaluation_report.json", import.meta.url),
      "utf8",
    ),
  );
  assert.equal(report.capture_type, "CONTROLLED_DATAHUB_ABLATION");
  assert.equal(report.gate.status, "PASS");
  assert.equal(report.benchmark.scenario_count, 13);

  const displayById = new Map(WHY_DATAHUB_RESULTS.map((arm) => [arm.id, arm]));
  for (const arm of report.impact_arms) {
    const display = displayById.get(arm.id);
    const percent = (value) =>
      value === null ? "N/A" : `${Number((value * 100).toFixed(1))}%`;
    assert.equal(display.precision, percent(arm.precision));
    assert.equal(display.recall, percent(arm.recall));
    assert.equal(display.f1, percent(arm.f1));
    assert.equal(display.exactCone, `${arm.exact_cones}/${arm.total_cones}`);
    assert.equal(display.status, arm.status);
  }
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
    "EVIDENCE CENTER",
    "DATAHUB RECEIPT",
    "EVALUATION REPORT",
    "GITHUB PR",
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
  assert.match(source, /Zero catalog calls/);
  assert.match(styles, /\.drawer-facts dt[^}]*11px/);
  assert.match(styles, /\.drawer-facts dd[^}]*13px/);
  assert.match(styles, /\.drawer-integrity p[^}]*11px/);
  assert.match(styles, /\.drawer-payload summary[^}]*11px/);
});

test("GitHub Evidence Center receipt binds a real PR and hosted checks without overstating SSO", async () => {
  const receipt = JSON.parse(
    await readFile(
      new URL("../public/evidence/github_live_evidence.json", import.meta.url),
      "utf8",
    ),
  );
  assert.equal(receipt.evidence_type, "GITHUB_REMOTE_REPAIR_AND_IDENTITY_BOUNDARY");
  assert.match(
    receipt.pull_request.url,
    /^https:\/\/github\.com\/songjie6816-code\/sciguard-repair-sandbox\/pull\/[2-9][0-9]*$/,
  );
  assert.equal(receipt.pull_request.state, "open");
  assert.equal(receipt.pull_request.number, 2);
  assert.match(receipt.pull_request.head_sha, /^[0-9a-f]{40}$/);
  assert.equal(receipt.change_receipt.commit_sha, receipt.pull_request.head_sha);
  assert.equal(receipt.verification_receipt.commit_sha, receipt.pull_request.head_sha);
  assert.equal(receipt.verification_receipt.provider, "GITHUB_CHECK_RUNS");
  assert.equal(receipt.verification_receipt.status, "PASS");
  assert.equal(receipt.verification_receipt.checks.length, 3);
  assert.equal(
    receipt.verification_receipt.checks.every(
      (check) =>
        check.status === "PASS" &&
        check.details_url.startsWith(
          "https://github.com/songjie6816-code/sciguard-repair-sandbox/actions/runs/",
        ),
    ),
    true,
  );
  assert.equal(
    receipt.authenticated_review.identity_assurance,
    "GITHUB_ACCOUNT_REVIEW",
  );
  assert.equal(receipt.authenticated_review.enterprise_sso_verified, false);
  assert.equal(receipt.authenticated_review.independent_reviewer, false);
  assert.equal(receipt.authenticated_review.production_authorized, false);

  const source = await readFile(
    new URL("../app/CommandCenter.tsx", import.meta.url),
    "utf8",
  );
  assert.match(
    source,
    /OPEN PUBLIC PR #\{numberValue\(drawerGitHubPullRequest\.number\)\}/,
  );
  assert.doesNotMatch(source, /OPEN PUBLIC PR #1/);
});

test("judge experience exposes brief, operate, audit, and receipt-bound repair", async () => {
  const source = await readFile(
    new URL("../app/CommandCenter.tsx", import.meta.url),
    "utf8",
  );
  const styles = await readFile(
    new URL("../app/globals.css", import.meta.url),
    "utf8",
  );

  assert.match(source, /type ExperienceView = "BRIEF" \| "OPERATE" \| "AUDIT"/);
  assert.match(source, /The pipeline passed\./);
  assert.match(source, /The decision became unsafe\./);
  assert.match(source, /CREATE REAL COMMIT/);
  assert.match(source, /VERIFY COMMIT/);
  assert.match(source, /APPROVE AS OWNER/);
  assert.match(source, /APPLY TO SYNTHETIC STAGING/);
  assert.match(source, /RUN CLEAN RECOVERY CHECK/);
  assert.match(source, /production authorization/);
  assert.match(source, /COUNTERFACTUAL VERIFICATION LAB/);
  assert.match(source, /Executed test receipts · not an animated prediction/);
  assert.match(source, /training ·/);
  assert.match(source, /inference ·/);
  assert.match(source, /external_action_receipt/);
  assert.match(source, /verification_receipt/);
  assert.match(source, /approval_receipt/);
  assert.match(source, /application_receipt/);
  assert.match(styles, /\.repair-receipt-strip/);
  assert.match(styles, /\.repair-application/);
  assert.match(styles, /\.repair-check\.passed/);
  assert.match(styles, /\.counterfactual-ranks/);
});
