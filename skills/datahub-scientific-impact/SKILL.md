---
name: datahub-scientific-impact
description: Trace a metadata, schema, unit, contract, feature, model, or deployment change through DataHub to the exact scientific, ML, or AI decision paths it can affect, while proving independent paths that can remain available. Use for blast-radius analysis, silent pipeline-success incidents, upstream drift, field-level impact, Production ML context, or requests asking what must halt versus what is safe to preserve.
---

# DataHub Scientific Impact

Build an evidence-bound decision cone, not a list of similarly named assets.

## Workflow

1. Identify the changed entity, changed fields, before/after contract, and observation time.
2. Resolve one exact DataHub URN. If a name has multiple matches, stop and ask the user to choose.
3. Traverse directed downstream lineage to form a conservative review scope.
4. For every changed field, follow fine-grained lineage. Classify each downstream asset:
   - `AFFECTED`: a changed field reaches it.
   - `PRESERVED`: it is in the dataset-level scope but no changed field reaches it.
   - `UNKNOWN`: field lineage is absent, truncated, or ambiguous.
5. Enrich the cone with ownership, criticality, governance terms, assertions, native
   MLFeature/MLFeatureTable/MLModel/MLModelDeployment context, training/inference runs,
   and human-facing decision outputs.
6. Identify the first decision boundary: model execution, report publication,
   recommendation, experiment selection, or other consequential output.
7. Produce the contract in `references/impact-output.md`. Attach query provenance and
   stable evidence IDs to every classification.

## Tool selection

- Prefer DataHub MCP for entity, schema, ownership, governance, and directed lineage reads.
- Use the DataHub CLI or SDK only for capabilities the active MCP tools do not expose,
  especially fine-grained lineage. Label the fallback.
- Batch-enrich URNs. Avoid one metadata call per node.
- Detect capped or truncated results and retry with pagination before declaring a complete cone.
- Reject shell metacharacters before passing user values to a CLI.

## Decision rules

- Never classify an asset as preserved from name similarity or missing lineage.
- Treat missing field lineage as `UNKNOWN`, not unaffected.
- Keep affected and preserved URN sets disjoint.
- Do not choose `HALT`, `ALLOW`, or `RESUME`; return evidence for a deterministic policy.
- Do not write DataHub metadata in this skill.
- If DataHub is unavailable, abstain. Do not invent a dependency graph.

## Completion gate

Finish only when the result names the changed field, affected path, preserved path,
decision boundary, owners, uncertainty, query provenance, and evidence IDs. Read
`references/impact-output.md` for the exact output shape.
