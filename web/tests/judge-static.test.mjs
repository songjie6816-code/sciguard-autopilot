import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import test from "node:test";

test("judge build is a no-login static replay with no localhost evidence links", async () => {
  const html = await readFile(new URL("../judge-dist/index.html", import.meta.url), "utf8");
  const manifest = JSON.parse(
    await readFile(
      new URL("../judge-dist/replays/inc-wp6-flagship/manifest.json", import.meta.url),
      "utf8",
    ),
  );
  const events = await readFile(
    new URL("../judge-dist/replays/inc-wp6-flagship/events.jsonl", import.meta.url),
    "utf8",
  );

  assert.match(html, /Public Judge Mode/);
  assert.doesNotMatch(html, /signin-with-chatgpt|localhost:9002|localhost:8000/);
  assert.equal(manifest.mode, "RECORDED_REPLAY");
  assert.equal(manifest.status, "COMPLETED");
  assert.equal(events.trim().split("\n").length, manifest.event_count);
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
    "69.8%",
    "NO DATAHUB",
    "NOT YET MEASURED",
    "PUBLIC EVIDENCE RECEIPT",
    "not a digital signature and not proof of origin",
  ]) {
    assert.match(bundleText, new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  assert.doesNotMatch(bundleText, /href=["']https?:\/\/(?:localhost|127\.0\.0\.1)/i);
});
