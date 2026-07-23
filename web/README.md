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
anonymous static host. It requires no secret, live API, local DataHub, or paid model API.
Do not deploy the parent directory; publish only the contents of `judge-dist/`.

```bash
pnpm build:judge
```

Judge Mode:

- states the replay boundary explicitly: **38 immutable events: 35 events reach recovery
  lock, followed by 3 verified recovery events.**
- verifies replay SHA-256, count, contiguous sequence, unique event IDs, and incident ID in
  the browser before rendering;
- runs the recorded story in 15 seconds and distinguishes that narrated duration from the
  recorded controller event span;
- marks the live backend OFFLINE with an explanation because static mode intentionally has
  no backend;
- opens public DataHub evidence receipts rather than linking hosted judges to localhost;
- discloses that the bundled replay was captured through `DATAHUB_SDK`, while the real MCP
  context path and its SDK field-lineage/write boundary are separately documented.

The bundled SHA-256 is an integrity/consistency check only. Because the expected digest and
JSONL are delivered together, it is not a digital signature or independent source
authentication.

No deploy, push, or access-policy change is performed by the build.

## Tests

```bash
pnpm test
pnpm lint
```

`pnpm test` builds both surfaces and verifies the server-rendered product shell plus the
anonymous static artifact and bundled replay.
