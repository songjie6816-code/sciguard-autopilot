---
name: datahub-repair-review
description: Review a proposed data, ML, or scientific repair against DataHub incident evidence, field lineage, native Production ML context, ownership, governance, tests, rollback, and approval policy. Use when asked whether an agent-generated patch or pull request is safe, evidence-complete, revision-bound, useful, or ready for accountable-owner approval.
---

# DataHub Repair Review

Review the proof carried by a change. Do not reward a plausible patch that is detached
from the incident, target revision, or preserved decision paths.

## Required inputs

Require an incident ID, root-cause evidence IDs, affected and preserved URNs, target
repository and base revision, patch artifacts, verification plan, rollback, risk, and
DataHub-resolved approver. Request missing inputs; never manufacture them.

## Workflow

1. Re-read the DataHub Incident and current Decision Log.
2. Confirm that affected and preserved sets still match directed field lineage.
3. Resolve native model version, features, training/inference runs, deployments,
   owners, criticality, and expected contracts for every model in scope.
4. Validate evidence closure: every artifact, test, approval gate, and claimed outcome
   cites evidence contained by the bundle.
5. Inspect the patch for the verified root cause only. Reject unrelated refactors,
   dependency upgrades, credential changes, and broad workflow edits.
6. Require:
   - a contract test that fails closed;
   - a decision-level counterfactual regression;
   - a non-regression test for each preserved path;
   - an executable rollback that re-establishes containment.
7. Bind the review to the exact bundle ID, branch, commit SHA, and verification receipt.
8. Resolve the accountable approver from DataHub. A typed name or UI boolean is not
   authenticated approval.
9. Return `APPROVE`, `REVISE`, or `REJECT` using `references/review-output.md`.

## Safety boundaries

- Review is read-only unless the user separately authorizes publication or metadata writes.
- A local commit is not a remote pull request.
- Local process results are not hosted CI check runs.
- A demo signature is tamper evidence, not SSO/OIDC identity.
- Failed or missing checks keep the approval gate locked.
- Do not allow the same entity in affected and preserved sets.
- Do not let an LLM-generated explanation override deterministic policy.

## Completion gate

Finish only when the verdict is revision-bound, every blocking issue has evidence, safe
paths have explicit tests, and all external-action claims match observed receipts.
