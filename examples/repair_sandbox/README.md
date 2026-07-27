# SciGuard repair sandbox

This directory is the bounded source shape expected by the flagship
Proof-Carrying Repair Bundle. `pipeline/normalize.py` deliberately contains the
trusted-label failure used by the synthetic incident. `pipeline/decision.py`
executes a real ranking and preserved molecular-weight artifact path over
`data/b042_decision_fixture.csv`, a 20-row subset copied from the deterministic
flagship dataset. The subset retains the observed P-204 `#18 → #1` decision
regression without inventing candidates inside the test.

The change-provider tests copy this source into a temporary Git repository,
apply the generated patch, add the generated contract/scientific/safe-branch
integration tests, and create a real local commit. The scientific test executes
the legacy and repaired normalizers against the fixture. The safe-branch test
publishes an actual artifact and compares it with a locked trusted digest. A
remote provider must use the same bundle and receipt contract before SciGuard
can claim a pull request.
