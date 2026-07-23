import assert from "node:assert/strict";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the SciGuard command center shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
  const html = await response.text();
  assert.match(html, /<title>SciGuard Autopilot/);
  assert.match(html, /Scientific Decision Control Plane/);
  assert.match(html, /A model succeeded/);
  assert.match(html, /#18/);
  assert.match(html, /#1/);
  assert.match(html, /Pipeline status/i);
  assert.match(html, /Sentinel signal/i);
  assert.match(html, /Escalation gate/i);
  assert.match(html, /DataHub Impact Graph/i);
  assert.match(html, /Evidence Board/i);
  assert.match(html, /Recovery Gate/i);
  assert.match(html, /RECORDED REPLAY/i);
  assert.match(html, /RUN 15s VERIFIED REPLAY/i);
  assert.match(html, /SHOW FINAL STATE/i);
  assert.match(html, /LIVE BACKEND/i);
  assert.match(html, /CONTROLLER EVENT SPAN/i);
  assert.match(html, /NARRATED REPLAY DURATION/i);
  assert.match(html, /DataHub MCP Server/i);
  assert.doesNotMatch(html, /href=["']http:\/\/localhost:9002/i);
  assert.doesNotMatch(html, /codex-preview|react-loading-skeleton|Your site is taking shape/i);
});
