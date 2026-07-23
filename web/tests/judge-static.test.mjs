import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
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
