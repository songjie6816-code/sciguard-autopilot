# SciGuard code map

## Start here

```text
api/main.py → api/runtime.py → core modules → DataHub / local controller
                   ↓
             one Event stream
                   ↓
        web / Streamlit / CLI / replay
```

`api/runtime.py` is the only business-workflow composition root. To understand the
complete closure, follow `SciGuardRuntime.run_live()` through publish, verify, approve,
apply, and two recovery calls in `scripts/capture_canonical_run.py`.

## Main trunk

| Order | Module | One responsibility |
|---|---|---|
| 1 | `core/sentinel.py` | Detect metadata drift, score it, and decide whether to escalate. |
| 2 | `core/coordinator.py` | Bind the signal to fixed hypotheses and coordinate independent evidence. |
| 3 | `core/investigator.py` | Read reverse lineage and current governance/release context from DataHub only. |
| 4 | `core/reality_checker.py` | Verify ranks, units, firmware, and trusted release artifacts locally only. |
| 5 | `core/impact.py` | Refine broad dataset scope into affected and preserved field-lineage branches. |
| 6 | `core/policy_engine.py` | Produce deterministic `HALT`, `WARN`, or `ALLOW` decisions. |
| 7 | `core/narration.py` | Explain the frozen plan with redaction, strict validation, and fallback. |
| 8 | `core/repair.py` | Freeze the evidence-bound patch, tests, rollback, and owner gate. |
| 9 | `core/change_provider.py` / `core/verification.py` | Create a real local Git commit and execute its locked checks. |
| 10 | `core/github_provider.py` / `core/github_verification.py` | Create a target-bound GitHub PR and bind hosted Check Runs to its exact head SHA. |
| 11 | `core/approval.py` | Sign a reviewer decision bound to owner, bundle, verification, and commit. |
| 12 | `core/application.py` | Materialize the exact approved Git tree in isolated synthetic staging and emit a non-production receipt. |
| 13 | `core/enforcement.py` / `core/pipeline_controller.py` | Persist controls and really block unsafe local work. |
| 14 | `core/recovery.py` | Re-run exact-commit evidence after `APPLIED` and authorize `RESUME` only after the configured gate. |

## Supporting boundaries

| Area | Modules | Purpose |
|---|---|---|
| Event truth | `core/events.py`, `core/incident_state.py`, `api/run_store.py` | One event schema, legal states, atomic replay. |
| Configuration | `core/profiles.py`, `domain_profiles/*.yaml` | Detection, escalation, action, and recovery policy. |
| DataHub access | `datahub_client/*`, `data/synthetic_polymer/native_ml.py` | SDK/MCP context, native Production ML projection, and safe read-modify-write updates. |
| LLM safety | `security/*` | Zero raw rows, redaction, bounded context, read-only tool gate. |
| Interfaces | `api/main.py`, `web/`, `app/streamlit_app.py`, `examples/run_incident.py` | One API plus thin visual/CLI clients. |
| Evidence | `data/synthetic_polymer/`, `evaluation/`, `scripts/capture_canonical_run.py`, `examples/replays/inc-sciguard-b042-unit-contract/` | Reproducible scenario, machine-readable metrics, and one canonical 55-event closure. |
| Reusable agent context | `skills/` | DataHub scientific impact, repair review, and recovery certification workflows. |

## Authority rules

- Sentinel can detect and escalate; it cannot write, block, declare root cause, or recover.
- Coordinator can organize evidence; it cannot override deterministic policy.
- Policy Guardian alone chooses `HALT`, `WARN`, and `ALLOW` from validated context.
- Enforcer alone writes incident controls; the local controller alone blocks local work.
- Remediation may propose and publish a bounded change; it cannot approve it.
- Verification executes only locked pytest targets and binds results to the published commit.
- A signed review receipt is not production identity unless its assurance says so.
- Application can materialize only an approved exact revision; local synthetic staging is
  neither production authorization nor a production deployment.
- Recovery alone authorizes `RESUME`, only after `APPLIED` and fresh server-owned checks.
- Narration and every UI are explanatory surfaces only.

The former detector, risk, lineage, remediation, orchestrator, field-impact, and two
narration files were deliberately consolidated into `sentinel.py`, `impact.py`,
`incident_state.py`, `runtime.py`, and `narration.py`. This leaves one visible trunk without
removing the evaluation harness or fallback interfaces.
