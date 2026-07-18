from pathlib import Path


def test_required_project_assets_exist() -> None:
    root = Path(__file__).parents[1]
    required = [
        "LICENSE",
        "README.md",
        ".env.example",
        "domain_profiles/generic.yaml",
        "domain_profiles/materials.yaml",
        "domain_profiles/polymer.yaml",
    ]
    assert all((root / path).is_file() for path in required)

