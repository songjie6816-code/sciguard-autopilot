import assert from "node:assert/strict";

const api =
  process.env.SCIGUARD_LIVE_API_URL ??
  "https://sciguard-live-sandbox.songjie6816.workers.dev";
const allowedOrigin = "https://sciguard-autopilot-demo.pages.dev";
const session = `verify-${crypto.randomUUID()}`;

const healthResponse = await fetch(`${api}/healthz`, {
  headers: { Origin: allowedOrigin },
});
assert.equal(healthResponse.status, 200);
assert.equal(healthResponse.headers.get("access-control-allow-origin"), allowedOrigin);
const health = await healthResponse.json();
assert.equal(health.status, "ok");
assert.equal(health.capabilities.live_calculation, true);
assert.equal(health.capabilities.server_sent_events, true);
assert.equal(health.capabilities.mutating_actions, false);
assert.equal(health.dependencies.datahub_context, "VERIFIED_MODULE_1_READBACK_SNAPSHOT");

const deniedResponse = await fetch(`${api}/api/runs`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-SciGuard-Session": session,
  },
  body: "{}",
});
assert.equal(deniedResponse.status, 403);

const invalidScenarioResponse = await fetch(`${api}/api/runs`, {
  method: "POST",
  headers: {
    Origin: allowedOrigin,
    "Content-Type": "application/json",
    "Idempotency-Key": "verify-invalid-scenario",
    "X-SciGuard-Session": session,
  },
  body: JSON.stringify({ scenario: "ARBITRARY_REPOSITORY" }),
});
assert.equal(invalidScenarioResponse.status, 400);

const completedRuns = [];
for (let index = 1; index <= 3; index += 1) {
  const idempotencyKey = `verify-run-${index}-${crypto.randomUUID()}`;
  const createResponse = await fetch(`${api}/api/runs`, {
    method: "POST",
    headers: {
      Origin: allowedOrigin,
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
      "X-SciGuard-Session": session,
    },
    body: JSON.stringify({ scenario: "KELVIN_CELSIUS_B042" }),
  });
  assert.equal(createResponse.status, 201);
  const created = await createResponse.json();
  assert.equal(created.manifest.mode, "LIVE");
  assert.equal(created.manifest.status, "RUNNING");
  assert.equal(
    created.manifest.datahub_backend,
    "VERIFIED_DATAHUB_READBACK_SNAPSHOT",
  );

  const duplicateResponse = await fetch(`${api}/api/runs`, {
    method: "POST",
    headers: {
      Origin: allowedOrigin,
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
      "X-SciGuard-Session": session,
    },
    body: JSON.stringify({ scenario: "KELVIN_CELSIUS_B042" }),
  });
  assert.equal(duplicateResponse.status, 200);
  const duplicate = await duplicateResponse.json();
  assert.equal(duplicate.idempotent_replay, true);
  assert.equal(duplicate.manifest.incident_id, created.manifest.incident_id);

  const streamResponse = await fetch(
    `${api}/api/runs/${created.manifest.incident_id}/events`,
    { headers: { Origin: allowedOrigin } },
  );
  assert.equal(streamResponse.status, 200);
  assert.match(streamResponse.headers.get("content-type") ?? "", /text\/event-stream/);
  const stream = await streamResponse.text();
  const frames = stream
    .split("\n")
    .filter((line) => line.startsWith("data: "))
    .map((line) => JSON.parse(line.slice(6)));
  const events = frames.filter((frame) => frame.event).map((frame) => frame.event);
  const completion = frames.find((frame) => frame.manifest)?.manifest;
  assert.equal(events.length, 12);
  assert.deepEqual(
    events.map((event) => event.sequence),
    Array.from({ length: 12 }, (_, sequence) => sequence),
  );
  assert.equal(
    events.every((event) => event.incident_id === created.manifest.incident_id),
    true,
  );
  assert.equal(events[0].payload.violating_rows, 187);
  assert.equal(events[0].payload.unsafe_rank, 1);
  assert.equal(events[0].payload.trusted_rank, 18);
  const impact = events.find((event) => event.event_type === "IMPACT_MAPPED");
  assert.equal(impact.payload.affected_names.length, 6);
  assert.equal(impact.payload.unaffected_names.length, 3);
  const repair = events.find((event) => event.event_type === "REPAIR_BUNDLE_CREATED");
  assert.equal(repair.payload.external_action.new_pull_request_created, false);
  assert.equal(
    repair.payload.external_action.pull_request_url,
    "https://github.com/songjie6816-code/sciguard-repair-sandbox/pull/2",
  );
  assert.equal(
    events.some(
      (event) =>
        event.event_type === "ENFORCEMENT_APPLIED" &&
        event.payload.asset_name === "candidate_ranking" &&
        event.payload.exit_code === 42,
    ),
    true,
  );
  assert.equal(completion.status, "COMPLETED");
  assert.equal(completion.event_count, 12);
  assert.match(completion.events_sha256, /^[0-9a-f]{64}$/);
  completedRuns.push(created.manifest.incident_id);
}

assert.equal(new Set(completedRuns).size, 3);

const limitedResponse = await fetch(`${api}/api/runs`, {
  method: "POST",
  headers: {
    Origin: allowedOrigin,
    "Content-Type": "application/json",
    "Idempotency-Key": `verify-limit-${crypto.randomUUID()}`,
    "X-SciGuard-Session": session,
  },
  body: JSON.stringify({ scenario: "KELVIN_CELSIUS_B042" }),
});
assert.equal(limitedResponse.status, 429);

const mutationResponse = await fetch(
  `${api}/api/runs/${completedRuns[0]}/repair/publish`,
  {
    method: "POST",
    headers: {
      Origin: allowedOrigin,
      "X-SciGuard-Session": session,
    },
  },
);
assert.equal(mutationResponse.status, 403);

const resetResponse = await fetch(`${api}/api/reset`, {
  method: "POST",
  headers: {
    Origin: allowedOrigin,
    "Content-Type": "application/json",
    "X-SciGuard-Session": session,
  },
  body: JSON.stringify({ incident_id: completedRuns.at(-1) }),
});
assert.equal(resetResponse.status, 200);
const reset = await resetResponse.json();
assert.equal(reset.status, "reset");
assert.equal(reset.rate_limit_window_preserved, true);

console.log(
  JSON.stringify(
    {
      status: "PASS",
      api,
      live_runs: completedRuns.length,
      unique_incidents: new Set(completedRuns).size,
      events_per_run: 12,
      rate_limit: "3 / 10 minutes / browser session",
      mutation_boundary: "READ_ONLY",
      datahub_context: health.dependencies.datahub_context,
    },
    null,
    2,
  ),
);
