from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
SKILLS = {
    "datahub-scientific-impact": "references/impact-output.md",
    "datahub-repair-review": "references/review-output.md",
    "datahub-recovery-certification": "references/certification-output.md",
}


def _frontmatter(source: str) -> dict:
    _, raw, _ = source.split("---", 2)
    return yaml.safe_load(raw)


def test_datahub_skills_are_portable_valid_and_self_contained() -> None:
    for name, reference in SKILLS.items():
        directory = ROOT / "skills" / name
        source = directory.joinpath("SKILL.md").read_text(encoding="utf-8")
        metadata = _frontmatter(source)
        agent = yaml.safe_load(
            directory.joinpath("agents/openai.yaml").read_text(encoding="utf-8")
        )

        assert metadata == {
            "name": name,
            "description": metadata["description"],
        }
        assert len(metadata["description"]) >= 100
        assert "TODO" not in source
        assert reference in source
        assert directory.joinpath(reference).is_file()
        assert f"${name}" in agent["interface"]["default_prompt"]
        assert 25 <= len(agent["interface"]["short_description"]) <= 64


def test_skills_preserve_sciguard_authority_boundaries() -> None:
    impact = (ROOT / "skills/datahub-scientific-impact/SKILL.md").read_text()
    review = (ROOT / "skills/datahub-repair-review/SKILL.md").read_text()
    recovery = (ROOT / "skills/datahub-recovery-certification/SKILL.md").read_text()

    assert "missing field lineage as `UNKNOWN`" in impact
    assert "Do not write DataHub metadata" in impact
    assert "A local commit is not a remote pull request" in review
    assert "Failed or missing checks keep the approval gate locked" in review
    assert "Never accept `human_approved=true`" in recovery
    assert "Never resolve when DataHub state cannot be re-read" in recovery
