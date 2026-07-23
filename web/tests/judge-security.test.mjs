import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import test from "node:test";

const judgeRoot = new URL("../judge-dist/", import.meta.url);

async function walk(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = await Promise.all(
    entries.map((entry) => {
      const url = new URL(entry.name + (entry.isDirectory() ? "/" : ""), directory);
      return entry.isDirectory() ? walk(url) : [url];
    }),
  );
  return files.flat();
}

test("judge artifact contains only public static replay material", async () => {
  const files = await walk(judgeRoot);
  const names = files.map((file) => file.pathname);
  assert.equal(names.some((name) => name.endsWith(".map")), false);
  assert.equal(names.some((name) => /(?:\.env|\.pem|\.key)$/i.test(name)), false);

  const textFiles = files.filter((file) => !file.pathname.endsWith(".png"));
  const text = (
    await Promise.all(textFiles.map((file) => readFile(file, "utf8")))
  ).join("\n");

  assert.doesNotMatch(text, /-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----/i);
  assert.doesNotMatch(text, /\b(?:sk-|gh[pousr]_)[A-Za-z0-9_-]{20,}/);
  assert.doesNotMatch(text, /\bAKIA[0-9A-Z]{16}\b|\bAIza[0-9A-Za-z_-]{30,}/);
  assert.doesNotMatch(text, /\bxox[baprs]-[A-Za-z0-9-]{10,}/);
  assert.doesNotMatch(text, /\/Users\/|\/home\/|file:\/\/|vscode-file:\/\//i);
  assert.doesNotMatch(text, /https?:\/\/(?:localhost|127\.0\.0\.1)/i);
  assert.doesNotMatch(text, /oai-authenticated-user|chatgpt-auth|appgprj_|client_secret/i);
  assert.doesNotMatch(text, /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i);
  assert.match(
    text,
    /38 immutable events: 35 events reach recovery lock, followed by 3 verified recovery events\./,
  );

  const manifest = JSON.parse(
    await readFile(new URL("replays/inc-wp6-flagship/manifest.json", judgeRoot), "utf8"),
  );
  const events = (
    await readFile(new URL("replays/inc-wp6-flagship/events.jsonl", judgeRoot), "utf8")
  )
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line));
  assert.equal(manifest.event_count, 38);
  assert.equal(events.length, 38);
  assert.deepEqual([...new Set(events.map((event) => event.incident_id))], [
    "inc-wp6-flagship",
  ]);
  assert.equal(events.some((event) => JSON.stringify(event).includes("@")), false);
  assert.equal(
    events.some((event) => (event.payload.raw_data_rows ?? 0) > 0),
    false,
  );
});
