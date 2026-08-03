## What changed

<!-- Describe the smallest reviewable change and why it matters. -->

## Evidence boundary

- [ ] Runtime behavior is unchanged, or the changed authority/evidence path is described below.
- [ ] Live, fixture, snapshot, replay, and sample claims are labelled accurately.
- [ ] No secrets, unpublished data, local paths, or private repository details are included.
- [ ] Canonical evidence was regenerated through its capture path rather than hand-edited, if applicable.

## Verification

- [ ] `make judge-check PYTHON=.venv/bin/python`
- [ ] Public links or UI states affected by this change were inspected.
