# Recorded replays

Each subdirectory is exported from a completed real SciGuard run. It contains:

- `manifest.json` — source commit and dirty-worktree disclosure, UTC generation time,
  DataHub backend, terminal state, event count, SHA-256, and validation invariants.
- `events.jsonl` — the exact immutable `core.events.Event` sequence observed during that run.
- `repair-bundle.json` — the provider-neutral patch, verification, review, and application
  receipts for captures that include repair execution.
- `repair-manifest.json` — cross-bindings among the event stream, Repair Bundle, and
  DataHub closure receipt.

The API always labels these bundles `RECORDED_REPLAY`; it never presents them as live data.

`inc-sciguard-champion/` is the primary Judge replay. Its 55 events come from one
DataHub-backed incident and one exact repair revision, including `APPLIED`, two fresh
recovery-verification executions, and final `RESOLVED`. The checked artifact was captured
from a clean implementation commit and records `source_worktree_dirty: false` in the
replay manifest, repair manifest, and DataHub closure receipt. Reproduce it with:

```bash
make champion-capture-clean
```

`inc-wp6-flagship/` is retained only as a 38-event legacy development replay. Do not merge
its separate action capture into claims about the canonical champion incident.
