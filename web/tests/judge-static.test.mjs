import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import test from "node:test";

test("judge build is a no-login static replay with no localhost evidence links", async () => {
  const html = await readFile(new URL("../judge-dist/index.html", import.meta.url), "utf8");
  const manifest = JSON.parse(
    await readFile(
      new URL(
        "../judge-dist/replays/inc-sciguard-b042-unit-contract/manifest.json",
        import.meta.url,
      ),
      "utf8",
    ),
  );
  const events = await readFile(
    new URL(
      "../judge-dist/replays/inc-sciguard-b042-unit-contract/events.jsonl",
      import.meta.url,
    ),
    "utf8",
  );
  const dataHubReceipt = JSON.parse(
    await readFile(
      new URL("../judge-dist/evidence/datahub_live_receipt.json", import.meta.url),
      "utf8",
    ),
  );

  assert.match(html, /Public Judge Mode/);
  assert.doesNotMatch(html, /signin-with-chatgpt|localhost:9002|localhost:8000/);
  assert.equal(manifest.mode, "RECORDED_REPLAY");
  assert.equal(manifest.status, "COMPLETED");
  assert.equal(events.trim().split("\n").length, manifest.event_count);
  assert.equal(dataHubReceipt.capture_type, "LIVE_DATAHUB_END_TO_END_CLOSURE");
  assert.equal(dataHubReceipt.incident_id, "inc-sciguard-b042-unit-contract");
  assert.equal(dataHubReceipt.repair_lifecycle.status, "APPLIED");
  assert.equal(dataHubReceipt.repair_lifecycle.recovery_results.at(-1).resume_allowed, true);
  assert.equal(dataHubReceipt.entity_count, 19);
  assert.equal(dataHubReceipt.all_verified, true);
});

test("judge bundle contains the P1 cockpit, measured comparison, and Evidence Drawer", async () => {
  const assetsRoot = new URL("../judge-dist/assets/", import.meta.url);
  const assetNames = await readdir(assetsRoot);
  const bundleText = (
    await Promise.all(
      assetNames
        .filter((name) => name.endsWith(".js") || name.endsWith(".css"))
        .map((name) => readFile(new URL(name, assetsRoot), "utf8")),
    )
  ).join("\n");

  for (const expected of [
    "A model succeeded.",
    "TRACE IMPACT",
    "VERIFY RECOVERY",
    "Search can find similar names; directed lineage proves the exact downstream decision cone.",
    "SEARCH-ONLY DATAHUB",
    "75%",
    "EXACT CONE · 3/3 WITH LINEAGE → 0/3 SEARCH-ONLY",
    "NO DATAHUB",
    "MEASURED ABSTENTION",
    "LIVE_DATAHUB_END_TO_END_CLOSURE",
    "CANONICAL REFERENCE",
    "2-MINUTE JUDGE TOUR",
    "Judge summary",
    "APPLY TO SYNTHETIC STAGING",
    "NATIVE ENTITIES READ BACK",
    "EVIDENCE CENTER · PUBLIC RECEIPT",
    "not a digital signature and not proof of origin",
    "RUN LIVE SCIENTIFIC INCIDENT",
    "WATCH VERIFIED CHAMPION RUN",
    "sciguard-live-sandbox.songjie6816.workers.dev",
  ]) {
    assert.match(bundleText, new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  assert.doesNotMatch(bundleText, /href=["']https?:\/\/(?:localhost|127\.0\.0\.1)/i);
});
