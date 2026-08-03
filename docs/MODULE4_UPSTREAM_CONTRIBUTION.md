# Module 4 — DataHub upstream contribution

Status on 2026-08-03: **SUBMITTED · DRAFT · NOT ACCEPTED**

## Public evidence

- Upstream repository: <https://github.com/datahub-project/datahub-skills>
- Proposal: [Issue #82](https://github.com/datahub-project/datahub-skills/issues/82)
- Contribution: [Draft PR #83](https://github.com/datahub-project/datahub-skills/pull/83)
- Fork branch:
  `songjie6816-code:datahub-skills/agent/field-impact-evidence`
- Contribution commit: `595fbb014b1cd2d4b01701573b4bf1dcb198f586`

## Contribution strategy

The upstream repository already had several open schema-impact, incident-response, and ML
impact proposals. Module 4 therefore did not publish SciGuard's three local Skills as three
new overlapping top-level Skills.

Instead, it generalized the most reusable SciGuard behavior into the existing
`datahub-lineage` Skill: classify field-specific downstream paths as `AFFECTED`,
`PRESERVED`, or `UNKNOWN`, and require positive field-level evidence before claiming that
an independent branch is preserved.

The contribution deliberately excludes SciGuard names, polymer entities, replay data,
policy verdicts, mutation workflows, risk scores, and project-specific code.

## Upstream diff

- Extend `skills/datahub-lineage/SKILL.md` with a field-impact traversal and fail-safe rules.
- Extend the lineage reference with the reusable two-scope strategy.
- Add `templates/field-impact-analysis.template.md` with provenance and completeness gates.
- Add the capability and example to the lineage README.

## Validation

- Markdownlint 0.21.0: zero errors on all four changed Markdown files.
- Prettier 4.0.0-alpha.8: all four files match repository formatting.
- General pre-commit hooks: whitespace, EOF, YAML, large-file, conflict, symlink,
  case-conflict, private-key, and permanent-link checks pass.
- `git diff --check`: pass.
- Upstream `validate-conventional-commit-title`: pass.
- No Python or runtime code changed upstream.

## Truth boundary

Safe claim: “SciGuard generalized and submitted a public DataHub upstream contribution.”

Blocked claim: “DataHub accepted or merged the contribution.” That claim becomes valid
only after the upstream PR records the corresponding maintainer action.

Reviewer comments, requested changes, CI updates, and merge status must be read directly
from Draft PR #83 before final submission.

## Module gate

- [x] Reusable capability generalized without project branding.
- [x] Duplication audit performed against open upstream proposals.
- [x] Public issue created.
- [x] Fork branch and exact contribution commit published.
- [x] Draft upstream PR created.
- [x] Public links exposed in README, Devpost draft, submission gate, and Judge Evidence UI.
- [x] Submitted-versus-accepted boundary stated wherever the contribution is presented.
- [ ] Maintainer acceptance or merge — external outcome, not required to complete Module 4.
