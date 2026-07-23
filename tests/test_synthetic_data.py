import csv
import hashlib
from pathlib import Path

from data.synthetic_polymer import generate


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def _digest(directory: Path) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.iterdir())
        if path.is_file()
    }


def test_flagship_batch_and_rank_shift_are_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    generate.build(first)
    generate.build(second)

    assert _digest(first) == _digest(second)
    raw = _rows(first / "raw_polymer_experiments.csv")
    before = _rows(first / "candidate_ranking_before.csv")
    after = _rows(first / "candidate_ranking_after.csv")

    assert len(raw) == generate.N_SAMPLES
    assert sum(row["batch_id"] == "B042" for row in raw) == generate.B042_ROWS
    assert sum(row["batch_id"] == "B042" and row["tg_unit"] == "K" for row in raw) == 187
    p204 = next(row for row in raw if row["sample_id"] == "P-204")
    assert p204["batch_id"] == "B042"
    assert p204["tg_unit"] == "K"
    assert next(row for row in before if row["candidate_id"] == "P-204")["rank"] == "18"
    assert next(row for row in after if row["candidate_id"] == "P-204")["rank"] == "1"
    trusted_p204 = next(
        row
        for row in _rows(first / "trusted_polymer_baseline.csv")
        if row["sample_id"] == "P-204"
    )
    assert trusted_p204["instrument_firmware"] == "v4.1"
    assert (first / "trusted_release_manifest.json").is_file()


def test_tg_contamination_does_not_enter_molecular_weight_branch(tmp_path: Path) -> None:
    generate.build(tmp_path)
    raw = _rows(tmp_path / "raw_polymer_experiments.csv")
    cleaned = _rows(tmp_path / "cleaned_polymer_dataset.csv")
    tg_features = _rows(tmp_path / "tg_feature_table.csv")
    mw_features = _rows(tmp_path / "molecular_weight_feature_table.csv")

    assert len(raw) == len(cleaned) == len(tg_features) == len(mw_features)
    assert "tg_degC" in tg_features[0]
    assert not any("tg" in column.lower() for column in mw_features[0])
    assert {row["sample_id"] for row in mw_features} == {row["sample_id"] for row in raw}

    raw_p204 = next(row for row in raw if row["sample_id"] == "P-204")
    tg_p204 = next(row for row in tg_features if row["sample_id"] == "P-204")
    mw_p204 = next(row for row in mw_features if row["sample_id"] == "P-204")
    assert tg_p204["tg_degC"] == raw_p204["tg_value"]  # buggy v1 treated K as degC
    assert mw_p204["mn_g_mol"] == raw_p204["mn_g_mol"]
    assert mw_p204["mw_g_mol"] == raw_p204["mw_g_mol"]


def test_provenance_columns_explain_the_silent_change(tmp_path: Path) -> None:
    generate.build(tmp_path)
    raw = _rows(tmp_path / "raw_polymer_experiments.csv")
    b041 = next(row for row in raw if row["batch_id"] == "B041")
    b042_k = next(
        row for row in raw if row["batch_id"] == "B042" and row["tg_unit"] == "K"
    )

    assert b041["instrument_id"] == "DSC-07"
    assert b041["instrument_firmware"] == "v4.1"
    assert b042_k["instrument_firmware"] == "v4.2"
    assert b041["normalization_version"] == b042_k["normalization_version"] == (
        "tg-normalizer-v1"
    )
