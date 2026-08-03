# Module 3 — Champion Judge Experience QA

Date: 2026-08-03 (Asia/Shanghai)

Scope: public Judge build only. This record separates browser-verified engineering checks from the still-required independent human cold-judge session.

## Outcome

The engineering acceptance path passes. The only remaining Module 3 gate is a recorded session with a person who has never seen SciGuard.

| Judge deadline | Required answer or evidence | Browser-verified path | Result |
| --- | --- | --- | --- |
| 10 seconds | Pipeline passed; scientific decision failed; P-204 moved #18 → #1; unsafe path blocked; safe work continues | Overview, first viewport | PASS |
| 30 seconds | DataHub is required for directed field lineage, ownership, criticality, governance, and writeback | Context hero, impact map, inspector, and three-arm comparison | PASS |
| 60 seconds | Patch, public PR, and hosted CI | Studio canonical delivery rail: `Patch + 4 proof files`, PR #2, `3 / 3 PASS` | PASS |
| 90 seconds | MW was preserved because it is outside the affected field-lineage cone | Context `PRESERVED · ALLOW` branch | PASS |
| 120 seconds | DataHub writeback and the three-arm ablation | Evidence DataHub receipt plus evaluation cards | PASS |

The Overview now includes a persistent, optional **2-minute Judge Tour** with
10/30/60/90/120-second checkpoints. Each checkpoint names the question a judge should be
able to answer and links directly to the relevant page; it does not auto-play or conceal
the normal Live / Replay paths.

## Live / replay semantics

- The first Overview CTA starts the public session-isolated Live scenario. The second CTA starts the integrity-checked replay.
- A live smoke run reached 12 visible actions and the `ENFORCED` state through the public controller and SSE stream.
- Live correctly stops with Recovery pending. The five-stage map shows Signal, Impact, and Control complete; Repair current; Recovery incomplete.
- The UI now says `LIVE CONTROL PASS ... recovery remains gated`, rather than implying that the full recovery loop completed.
- When that live boundary is reached, an accessible `LIVE RUN COMPLETE · DECISION
  REQUIRED` dialog now states that no request is still running, summarizes the completed
  work, explains the read-only boundary, and offers `Continue with verified recovery`,
  `Inspect the patch`, or `Stay and inspect results`.
- The same next-action dialog model is wired to full-product receipt transitions:
  publish → verify → owner approval → synthetic-staging application → two fresh recovery
  checks. It advances only after the preceding backend receipt is recorded.
- The Studio proof rail explicitly labels the PR/CI/recovery receipts as the completed canonical reference incident, separate from the isolated live run.
- Studio opens in `Judge summary`, with patch, public PR, hosted CI, owner approval, and
  recovery evidence ahead of telemetry. `Technical details` restores the full event,
  graph, policy, and console surfaces.
- The Repair Bundle card scrolls directly to the rendered patch. The canonical recovery
  step reads `AUTHORIZED` from the DataHub closure receipt even when the narrated replay
  has not been started.
- Live evidence IDs without embedded payloads still populate the Evidence Board; the verified smoke run displayed 187 unit violations and firmware v4.2.

## Evidence and honesty checks

- Overview core values are clickable: #18, #1, 187 rows, 19 DataHub entities, 55 immutable events, and 3/3 exact cones.
- Context graph entities and all three comparison arms open their evidence source.
- Evidence exposes the DataHub receipt, evaluation report, GitHub receipt, full 40-character repair SHA, public PR, and individual hosted CI links.
- Audit contains visible boundaries for the live controller, DataHub read-back snapshot, GitHub account identity, enterprise SSO, independent review, production authorization, and replay hash integrity.
- Evidence Drawer opens as a dialog, focuses its close control, closes with Escape, and returns focus to its trigger.

## Responsive and accessibility QA

| Check | Observed result |
| --- | --- |
| 1440 × 900 Overview | No horizontal overflow; all five 10-second facts are in the first viewport |
| 1024 × 768 Context | No horizontal overflow; affected and preserved branches and all three ablation arms are present |
| 390 × 844 Evidence | No horizontal overflow; 7 passport receipts, 3 source cards, and 3 honesty-boundary cards are present |
| 390 × 844 Overview + Judge Tour | No horizontal overflow; all five timed checkpoints and the next-step control remain available |
| Keyboard semantics | 33 visible controls, 0 unnamed controls, 0 positive `tabindex` values |
| Page navigation focus | Navigation moves focus to the destination `h1`; a skip-to-content control is first in DOM order |
| Evidence dialog | Initial focus, Escape close, and trigger focus restoration verified |
| Next-action dialog | Initial primary-action focus, Escape close, keyboard focus trap, explicit pause reason, and mobile stacking verified |
| Reduced motion | Production CSS contains `prefers-reduced-motion: reduce` and disables animation, transition, and smooth scrolling |

Latest automated gate: lint passed; both production builds passed; all 13 Node tests
passed. Browser retest confirmed `scrollWidth === clientWidth` at mobile width and verified
that Repair Bundle lands on the visible patch with hosted-check and owner-gate evidence
beside it.

## Visual QA artifacts

- [Overview — 1440 × 900](screenshots/module3-overview-1440x900.jpg)
- [Recovery Studio — 1440 × 900](screenshots/module3-studio-1440x900.jpg)
- [DataHub Context — 1024 × 768](screenshots/module3-context-1024x768.jpg)
- [Evidence — mobile 390 × 844](screenshots/module3-evidence-mobile-390x844.jpg)

## Independent cold-judge gate — not yet executed

Recruit one person who has not seen the repository, README, video, or prior SciGuard screens. Give them only the public URL and do not explain the product. Record exact answers and time stamps:

| Time | Ask exactly | Pass condition | Result / verbatim answer |
| --- | --- | --- | --- |
| 10 s | “What happened?” | Mentions green pipeline, unsafe scientific decision, selective block, and safe continuation | PENDING |
| 30 s | “Why is DataHub necessary?” | Mentions directed lineage or exact impact scope, not generic metadata search | PENDING |
| 60 s | “Show me the patch, PR, and CI.” | Reaches all three without coaching | PENDING |
| 90 s | “Why did molecular-weight work continue?” | Identifies independent field-lineage branch | PENDING |
| 120 s | “Show me the DataHub writeback and comparison evidence.” | Opens the receipt and three-arm evaluation | PENDING |

Stop and revise the UI if any answer requires coaching, if the person mistakes the isolated Live run for the completed canonical repair, or if they interpret the GitHub review as enterprise SSO or independent production approval.
