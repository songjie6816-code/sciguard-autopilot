# SciGuard submission gate

This is the final go/no-go gate for the public hackathon entry. It is based on the
attached Official Rules snapshot and the repository's measured evidence. Re-check the
live Devpost rules before the final submission because the Official Rules permit
amendments.

## Hard deadline and ownership

- Submission closes **August 10, 2026 at 5:00 pm Eastern Time**. In China Standard
  Time, that is **August 11, 2026 at 5:00 am** while US Eastern Daylight Time applies.
- Freeze the Devpost entry at least 24 hours earlier. The final hour is only for link
  verification, not content creation.
- Appoint one eligible team representative and verify every team member satisfies the
  eligibility rules.
- Record that SciGuard was newly created during the submission period. Disclose any
  pre-existing code, templates, assets, or third-party assistance.

## Mandatory submission materials

All boxes in this section are blocking.

- [ ] Devpost registration is complete for the representative and every listed member.
- [x] The project URL opens anonymously, free of charge, in a clean browser.
- [x] The public code repository opens anonymously.
- [x] The repository contains a visible Apache-2.0 `LICENSE`.
- [x] GitHub's repository About section detects and displays the Apache-2.0 license.
- [x] The repository contains source, synthetic data, sample outputs, setup instructions,
      tests, the proof-carrying repair bundle, and the public replay.
- [ ] The English Devpost description has no placeholders and matches the actual build.
- [ ] The public YouTube, Vimeo, or Youku video is under three minutes.
- [ ] The video shows the functioning product, not only slides or mockups.
- [ ] The video contains no unlicensed music, logos, footage, or third-party assets.
- [ ] English narration, captions, description, and testing instructions are complete.
- [ ] The public demo, repository, and video remain available through August 31, 2026.

## Judge's 170-second video cut

Do not start with architecture. Start with the broken decision.

| Time | Screen and action | Claim the judge must retain |
|---|---|---|
| 0:00–0:12 | Brief hero: pipeline `SUCCESS`, P-204 `#18 → #1` | A technically healthy pipeline produced an unsafe scientific decision. |
| 0:12–0:30 | Run the verified replay; show the unit contract and rejected model-drift hypothesis | SciGuard distinguishes data drift from model drift with evidence. |
| 0:30–0:55 | Operate: DataHub impact graph | Field lineage isolates 6 affected assets and preserves 3 independent assets. |
| 0:55–1:12 | Native Production ML context and lifecycle | DataHub connects features, training, models, deployments, inference, owners, and decisions. |
| 1:12–1:35 | Enforcement console | Deterministic policy blocks the unsafe ranking with exit 42 while safe work exits 0. |
| 1:35–1:58 | Counterfactual Verification Lab | The generated patch restores `#1 → #18`; three distinct receipts prove unit, decision, and safe-branch behavior. |
| 1:58–2:17 | Repair and authority panel | Patch, commit, tests, approval, exact-revision application, and recovery are bound to the same evidence closure. |
| 2:17–2:35 | DataHub Incident and Decision Log receipts | SciGuard contributes resolved incident state and durable knowledge back to DataHub. |
| 2:35–2:50 | Why DataHub ablation and Evidence Drawer | Lineage recovers 3/3 exact cones; search-only recovers 0/3. Every public claim is inspectable. |

End on this sentence:

> SciGuard does not merely tell a team what changed. It proves which scientific decision
> became unsafe, keeps independent work running, and only restores the path when the
> repair, tests, owner approval, and DataHub state all agree.

## Evidence-to-score map

| Criterion | Show first | Repository proof | No-overclaim boundary |
|---|---|---|---|
| Use of DataHub | Impact graph, native ML lifecycle, Incident and Decision Log | `data/synthetic_polymer/native_ml.py`, `datahub_client/incident_writer.py`, `examples/outputs/datahub_live_receipt.json` | MCP handles supported reads; fine-grained lineage and writes use the labelled SDK fallback. |
| Technical Execution | Exit 42/0 controls, counterfactual lab, APPLIED boundary, recovery gate | `core/enforcement.py`, `core/repair.py`, `core/verification.py`, `core/application.py`, `core/recovery.py`, passing test suite | Local synthetic staging is not a production deployment; a recorded local commit is not a remote PR. |
| Originality | Scientific decision control plane and selective containment | Domain profiles, proof-carrying repair, native ML decision context | Do not describe built-in DataHub features as SciGuard inventions. |
| Real-World Usefulness | Unsafe ranking blocked while MW work continues | Affected/preserved cone, owner gate, rollback, recovery certification | Practitioner metrics remain future work until measured with users. |
| Submission Quality | Brief → Operate → Audit and Evidence Drawer | Static Judge build, integrity manifests, README, and machine-readable evaluation JSON | SHA-256 proves package consistency, not authorship or origin. |
| Open-source bonus | Reusable Skills plus an upstream field-impact contribution | Local Skills; [Issue #82](https://github.com/datahub-project/datahub-skills/issues/82); [Draft PR #83](https://github.com/datahub-project/datahub-skills/pull/83) | The contribution is submitted and publicly reviewable; acceptance or merge is not claimed. |

## Truthful claim gate

The following current claims are safe:

- The canonical `inc-sciguard-b042-unit-contract` replay contains 55 contiguous, unique events for
  one incident ID.
- The same execution contains a real local Git commit and three executed pytest checks.
- The three verification results have distinct result digests.
- The demo-signed approval is bound to the bundle, verification receipt, and commit.
- The exact approved Git tree reached `APPLIED` in isolated
  `SCIGUARD_SYNTHETIC_STAGING`; its receipt records a tree digest and
  `production_authorized: false`.
- Two fresh recovery-verification executions enforced clean-run counts 1 then 2 before
  the same Incident reached `RESOLVED · FIXED`.
- The same closure read back 19 native DataHub Production ML entities and a `PUBLISHED`
  Decision Log with 11 related assets and the required receipt IDs.
- The machine-readable three-arm evaluation measured lineage at 100% precision/recall/F1
  and 3/3 exact cones; search-only at 60% / 100% / 75% and 0/3; zero-context abstention at
  0% recall and 0/3.
- The canonical capture records `source_worktree_dirty: false` in its replay manifest,
  repair manifest, and DataHub closure receipt.

The following claims are blocked until the named receipt exists:

- [x] “A GitHub pull request was created” — public PR #2 is bound to exact head SHA
      `ea1a4760520fcb299d8b8f73d955e5c66cc03ee3`.
- [x] “GitHub checks passed” — three GitHub Actions Check Run IDs are bound to that exact
      head SHA in `examples/outputs/github_live_evidence.json`.
- [ ] “Production approval was granted” — requires SSO/OIDC-backed identity assurance.
- [ ] “The repair was deployed to production” — requires a production deployment adapter
      and a receipt whose authorization and environment are independently verifiable.
- [x] “The submitted canonical capture came from clean source” — the capture-source commit
      was clean and all three provenance-bearing artifacts record
      `source_worktree_dirty: false`.
- [x] “The public deployment is the current build” — the canonical Judge release and
      Evidence Center were deployed and opened anonymously on Cloudflare Pages.
- [x] “An upstream DataHub open-source contribution was submitted” — public Issue #82 and
      Draft PR #83 add a domain-neutral field-impact evidence contract to the existing
      `datahub-lineage` Skill; the PR title check passed.
- [ ] “DataHub accepted our open-source contribution” — requires a public upstream PR or
      merged contribution.

## Cold-judge rehearsal

Run this from a machine and browser profile that have never opened the project:

1. Open only the Devpost entry.
2. Play the video from the embedded player with captions enabled.
3. Open the anonymous demo and complete Brief → Show Final State → Operate → Audit.
4. Open one Incident evidence receipt and the controlled benchmark drawer.
5. Open the public repository and follow the shortest setup path exactly.
6. Run the documented tests and Judge build.
7. Verify there are no localhost links, secrets, missing assets, login prompts, 404s, stale
   hashes, placeholder text, or claims not visible in the submitted build.
8. Repeat on a 1024-pixel-wide viewport and with reduced motion enabled.

Current deployment note: the Cloudflare Pages URL serves the canonical
`inc-sciguard-b042-unit-contract` replay, DataHub closure, and Evidence Center. The connected Sites
project ID remains unavailable, so deployment used the already-existing Cloudflare Pages
project rather than creating an untracked second project.

## Final 24-hour gate

- [x] Freeze and commit the implementation; require a clean worktree and record this
      capture-source SHA.
- [x] Run `make canonical-capture-clean` from that clean implementation commit. Confirm the repair
      reaches `PROPOSED → PUBLISHED → VERIFIED → APPROVED → APPLIED`, two fresh recovery
      executions occur, and the same incident reaches `RESOLVED`.
- [ ] Rebuild the Judge artifact and re-run the full Python, lint, web, integrity, and
      clean-install gates against the generated evidence.
- [ ] Commit the reviewed generated evidence, tag the exact submitted release revision,
      and record both the capture-source SHA and release-tag SHA. Do not recursively
      recapture merely because committing evidence creates the release commit.
- [ ] Verify demo, repository, video, README anchors, PRs, and evidence links from an
      incognito browser in two networks.
- [ ] Run `make verify-public URL=https://sciguard-autopilot-demo.pages.dev` and require
      `Deployment gate: PASS` against the frozen checkout.
- [ ] Confirm the video duration is below 3:00 in the public player.
- [ ] Replace every bracketed placeholder in `docs/devpost_submission.md`.
- [ ] Export a PDF or screenshot copy of the final Devpost entry for the team record.
- [ ] Submit before the internal freeze and save the Devpost confirmation.

**Go** only when every mandatory and final-24-hour box is checked. A strong demo is not a
substitute for eligibility, public access, license visibility, or a valid video URL.
