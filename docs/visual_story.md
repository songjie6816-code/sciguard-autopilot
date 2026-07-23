# SciGuard Cinematic Command Center contract

This document is the human-readable presentation contract for WP0.5. The
machine-readable source is `evaluation/scenarios.json.presentation`. UI code may refine
layout and animation, but it must not rename modes, invent data, advance incident state, or
maintain a separate replay story.

## Product surface

The primary judge-facing surface is a single-page Next.js command center backed by a
minimal FastAPI event API and SSE. The existing Streamlit app remains an emergency fallback,
not the intended final presentation.

Product label:

> SciGuard Autopilot — Scientific Decision Control Plane

The page must feel like an operational control plane because it exposes consistent state,
evidence, actions, and recovery—not because it contains generic administration features.

## First-screen information architecture

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ SG-2026-0042 · QUARANTINED · LIVE · 01:24 · DataHub MCP                │
├──────────────────┬────────────────────────────┬──────────────────────────┤
│ AGENT TIMELINE   │ DATAHUB IMPACT GRAPH       │ EVIDENCE BOARD           │
│                  │                            │                          │
│ Coordinator      │ B042 → raw → cleaned       │ firmware v4.2            │
│ Investigator     │              ├→ Tg → HALT  │ 187 mixed-unit rows      │
│ Reality Checker  │              └→ MW → ALLOW │ model version unchanged  │
│ Policy Guardian  │                            │ evidence IDs + sources   │
├──────────────────┴────────────────────────────┴──────────────────────────┤
│ POLICY: HALT Tg · ALLOW MW │ REPORT PUBLISH: BLOCKED · EXIT 42          │
├──────────────────────────────────────────────────────────────────────────┤
│ RECOVERY  ✓ conversion  ✓ unit contract  ✓ validation  ○ rank stability│
└──────────────────────────────────────────────────────────────────────────┘
```

The global header never scrolls out of view. `LIVE` or `RECORDED_REPLAY` is always visible.
The page must remain understandable at projector distance without opening a detail drawer.

## Six story beats

The complete story is capped at 170 seconds. Timing is a content budget, not an instruction
to fake operation duration.

| time | beat | judge takeaway |
|---|---|---|
| 0:00–0:18 | Rank shock | P-204 jumped from #18 to #1 although every pipeline says SUCCESS. |
| 0:18–0:40 | Hypotheses | The Coordinator proposes model drift, upstream data drift, and legitimate improvement. |
| 0:40–1:10 | Parallel investigation | DataHub lineage isolates the Tg branch; local checks confirm firmware/unit drift and reject model drift. |
| 1:10–1:58 | Selective containment | Policy halts Tg and blocks ranking publication while the molecular-weight branch stays healthy. |
| 1:58–2:30 | Evidence-gated recovery | A new controller reads incident state, reruns checks, and unlocks RESUME only when every gate passes. |
| 2:30–2:50 | Quantified proof | Three real evaluation modes show how DataHub changes cone, owner, and action scope. |

## Required visual moments

### Rank shock

Show the before/after ranks at hero scale alongside `Pipeline status: SUCCESS`. Do not show
the root cause yet. The visual contradiction is the hook.

### Agent timeline

Render event actor, event type, summary, time, and evidence IDs. Show hypothesis status as
`PROPOSED`, `CONFIRMED`, `REJECTED`, or `INCONCLUSIVE`. Never render private chain-of-thought
or an imitation of it.

### DataHub impact graph

Animate only changes supported by `IMPACT_MAPPED` and policy events. Contaminated paths are
critical, at-risk paths warning, unaffected paths healthy, and DataHub-sourced context blue.
Nodes expose owner, criticality, role, evidence source, and DataHub deep link.

### Evidence board

Cards are explicitly labelled as observed fact, inference, rejected hypothesis, or missing
evidence. Every metric and scientific claim links to an evidence ID and integrity hash.

### Policy and enforcement

Policy shows `HALT`, `WARN`, or `ALLOW` separately from catalog status and enforcement
action. The console displays the real command, exit code, incident ID, and DataHub
write-back receipt. An animation may visualize an action but cannot substitute for it.

### Recovery gate

The UI reads deterministic check results. `RESUME` stays visibly locked while any required
check is missing or failing. Animation cannot change check or incident state.

### Evaluation theatre

Compare `NO_DATAHUB_CONTEXT`, `SEARCH_ONLY_DATAHUB`, and `FULL_DATAHUB`. The first mode must
make no DataHub calls. Search-only must be labelled as without lineage, not without DataHub.
All displayed metrics come from the evaluation artifact.

## Visual semantics

- Critical/red: contaminated, halted, blocked, or failed.
- Warning/amber: at risk, under investigation, or awaiting evidence.
- Healthy/green: unaffected, allowed, verified, or resolved.
- DataHub/blue: evidence read from or state written to DataHub.
- Neutral/slate: context without a policy decision.

Color is never the only status signal; include text and an icon or shape. Motion should
direct attention to new evidence and state transitions. Avoid decorative background motion,
fake terminal typing, fabricated token/cost counters, and unexplained charts.

## Bounded platform architecture

Required:

- Minimal FastAPI run, health, event-stream, recovery, reset, and replay endpoints.
- SSE as the only live transport.
- JSONL run store with source commit, generated time, mode, and integrity information.
- One Next.js incident command-center route.
- Live and replay parity through the same event schema and components.
- Existing Streamlit emergency fallback.

Deferred until every competition gate is green:

- Authentication, RBAC, multi-tenancy, database, distributed queue, and WebSockets.
- Slack, Jira, Airflow, dbt, and production scheduler adapters.
- Multiple LLM providers, multiple scientific domains, and mobile-specific UI.

## Acceptance checklist

- The first screen communicates symptom, investigation, affected branch, action, and mode.
- The full narrated path fits within 170 seconds without hiding work after the limit.
- Every number has evidence; every state change comes from an event.
- Live and replay use the same renderer and remain globally distinguishable.
- Projector-sized primary text remains legible.
- The blocked publish is a real non-zero process result, not a UI toggle.
- The unaffected molecular-weight branch remains visibly healthy.
- Recovery cannot be unlocked by frontend state or LLM text.
- The page remains useful with animation disabled.
