# Recorded replays

Each subdirectory is exported from a completed real SciGuard run. It contains:

- `manifest.json` — source commit and dirty-worktree disclosure, UTC generation time,
  DataHub backend, terminal state, event count, SHA-256, and validation invariants.
- `events.jsonl` — the exact immutable `core.events.Event` sequence observed during that run.

The API always labels these bundles `RECORDED_REPLAY`; it never presents them as live data.
