# SciGuard command center

This directory contains two delivery surfaces that share `app/CommandCenter.tsx` and the
same immutable replay artifacts.

## Full product

The vinext/Next.js build keeps the complete product surface. It can connect to the bounded
FastAPI Event API when `NEXT_PUBLIC_SCIGUARD_API_URL` is configured, or automatically uses
`http://127.0.0.1:8000` only when the page itself runs on localhost. The app route does not
require authentication, but a hosting platform may still enforce its own access policy.

```bash
corepack enable
pnpm install --frozen-lockfile
pnpm dev
pnpm build
```

`.openai/hosting.json` is an optional, ignored local binding. When it is absent, the full
product builds with no D1/R2 bindings. `.openai/hosting.example.json` is the public,
sanitized shape; the real hosted project binding is never required for a clean build.

## Public Judge Mode

`pnpm build:judge` produces `judge-dist/`, a standalone static site suitable for an
anonymous static host. It requires no browser secret, local DataHub, or paid model API.
The configured public API is a read-only Cloudflare Worker/Durable Object sandbox; if its
health check fails, the verified replay remains the explicit fallback.
Do not deploy the parent directory; publish only the contents of `judge-dist/`.

```bash
pnpm build:judge
```

Judge Mode:

- exposes **RUN LIVE SCIENTIFIC INCIDENT** and **WATCH VERIFIED CHAMPION RUN** as separate
  paths;
- creates isolated, resettable live state and streams newly computed events over SSE;
- limits the public sandbox to the fixed `KELVIN_CELSIUS_B042` scenario and three runs per
  browser session per ten minutes;
- resolves the canonical PR #2 read-only and refuses public GitHub, DataHub, or production
  mutations;
- labels DataHub context as a verified Module 1 read-back snapshot instead of claiming a
  fresh public GMS query;
- states the replay boundary explicitly: **55 immutable canonical events** through two
  fresh recovery verifications;
- verifies replay SHA-256, count, contiguous sequence, unique event IDs, and incident ID in
  the browser before rendering;
- runs the recorded story in 15 seconds and distinguishes that narrated duration from the
  recorded controller event span;
- marks the live backend ONLINE only after the Worker health and capability contract
  succeeds; failure leaves the replay available and never displays a fake live success;
- opens public DataHub evidence receipts rather than linking hosted judges to localhost;
- discloses that the bundled replay was captured through `DATAHUB_SDK`, while the real MCP
  context path and its SDK field-lineage/write boundary are separately documented.

The bundled SHA-256 is an integrity/consistency check only. Because the expected digest and
JSONL are delivered together, it is not a digital signature or independent source
authentication.

No deploy, push, or access-policy change is performed by the build.

The public contract can be exercised end-to-end with:

```bash
pnpm verify:live
```

That script performs three consecutive isolated runs, verifies 12 contiguous events per
run, idempotency, the fourth-run rate limit, the reset boundary, and refusal of mutation.

## Tests

```bash
pnpm test
pnpm lint
```

`pnpm test` builds both surfaces and verifies the server-rendered product shell plus the
anonymous static artifact and bundled replay.
