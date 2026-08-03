# Module 5 Release Freeze

SciGuard `v1.0.0-hackathon` is the immutable product release used to record the
final judge video. The annotated Git tag, rather than a mutable branch name, is
the authority for the frozen source revision.

## Frozen public surfaces

- Judge experience: <https://sciguard-autopilot-demo.pages.dev/>
- Source repository: <https://github.com/songjie6816-code/sciguard-autopilot>
- Canonical repair PR: <https://github.com/songjie6816-code/sciguard-repair-sandbox/pull/2>
- DataHub contribution: <https://github.com/datahub-project/datahub-skills/pull/83>

## Canonical evidence provenance

The recorded incident is intentionally preserved rather than regenerated for
release-only lint, documentation, and version metadata changes.

| evidence | frozen value |
|---|---|
| incident | `inc-sciguard-b042-unit-contract` |
| capture-source commit | `7115813bbb0ed167f84c6ccbffa684c2076da341` |
| capture worktree | clean |
| event count | `55` |
| event stream SHA-256 | `5b84a811ecb1b0d4ee6eab9e0adfce772995b56cbdc71bf944ed65f95243a8f9` |
| repair commit | `ea1a4760520fcb299d8b8f73d955e5c66cc03ee3` |
| DataHub receipt SHA-256 | `915a76c0fa690890f0848ad775d12f06f0cd29082d966e8c40b33175912cb95f` |
| evaluation report SHA-256 | `8022108b2a82740bfc57bd1e4592f7eeb7fee5b5846952a1461147e1dc90ed01` |
| GitHub receipt SHA-256 | `bbea213fcfe7dac8604f37d654e870875f22b5c8a0f5143cc73a76087ae20900` |

The capture-source commit and release-tag commit are different by design. The
release changes after the capture do not alter the event schema, controller,
scenario, evidence payloads, or replay semantics. Committing the reviewed
evidence must not recursively force a new evidence capture.

## Release gates

- [x] Ruff passes on the complete repository.
- [x] All 189 Python tests pass.
- [x] The deterministic evaluation reproduces the curated JSON byte-for-byte.
- [x] Web ESLint, application build, Judge build, and all 13 Node tests pass.
- [x] The public Live Sandbox passes three isolated runs and its rate-limit check.
- [x] A fresh temporary checkout installs Python and Node dependencies from the
      declared project metadata and lockfile, then passes the same gates.
- [x] The public deployment verifier matches all seven canonical evidence files
      byte-for-byte and loads the generated CSS and JavaScript assets.
- [x] GitHub PR #2 remains open at the exact repair SHA with three successful
      hosted checks and the disclosed account-bound review.
- [x] The public Judge UI keeps enterprise SSO and production authorization
      explicitly unclaimed.

One non-blocking `StarletteDeprecationWarning` originates in the installed
FastAPI test client dependency. It does not change test results or SciGuard
runtime behavior.

## Freeze policy

After `v1.0.0-hackathon` is created, do not change application behavior,
scenario semantics, evidence files, or the judge flow while recording the final
video. Any required product change needs a new tag and a new public deployment.
Documentation-only replacement of the final video URL may follow on `main`, but
the video must demonstrate the tagged product release.

Verify the frozen revision with:

```bash
git rev-list -n 1 v1.0.0-hackathon
git show --no-patch --decorate v1.0.0-hackathon
make verify-public PYTHON=.venv/bin/python \
  URL=https://sciguard-autopilot-demo.pages.dev
```
