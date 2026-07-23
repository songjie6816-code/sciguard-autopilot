# SciGuard code map

## Start here

```text
api/main.py → api/runtime.py → core modules → DataHub / local controller
                   ↓
             one Event stream
                   ↓
        web / Streamlit / CLI / replay
```

`api/runtime.py` is the only business-workflow composition root. If a reviewer wants to
understand a complete run, read `SciGuardRuntime.run_live()` from top to bottom.

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
| 8 | `core/enforcement.py` / `core/pipeline_controller.py` | Persist controls and really block unsafe local work. |
| 9 | `core/recovery.py` | Re-read evidence and authorize `RESUME` only after the configured gate. |

## Supporting boundaries

| Area | Modules | Purpose |
|---|---|---|
| Event truth | `core/events.py`, `core/incident_state.py`, `api/run_store.py` | One event schema, legal states, atomic replay. |
| Configuration | `core/profiles.py`, `domain_profiles/*.yaml` | Detection, escalation, action, and recovery policy. |
| DataHub access | `datahub_client/*` | Interchangeable SDK/MCP reads and safe read-modify-write updates. |
| LLM safety | `security/*` | Zero raw rows, redaction, bounded context, read-only tool gate. |
| Interfaces | `api/main.py`, `web/`, `app/streamlit_app.py`, `examples/run_incident.py` | One API plus thin visual/CLI clients. |
| Evidence | `data/synthetic_polymer/`, `evaluation/`, `examples/replays/` | Reproducible scenario, regression metrics, and real-run replay. |

## Authority rules

- Sentinel can detect and escalate; it cannot write, block, declare root cause, or recover.
- Coordinator can organize evidence; it cannot override deterministic policy.
- Policy Guardian alone chooses `HALT`, `WARN`, and `ALLOW` from validated context.
- Enforcer alone writes incident controls; the local controller alone blocks local work.
- Recovery alone authorizes `RESUME`, after re-reading persisted evidence.
- Narration and every UI are explanatory surfaces only.

The former detector, risk, lineage, remediation, orchestrator, field-impact, and two
narration files were deliberately consolidated into `sentinel.py`, `impact.py`,
`incident_state.py`, `runtime.py`, and `narration.py`. This leaves one visible trunk without
removing the evaluation harness or fallback interfaces.
