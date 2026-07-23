"""Build the deterministic flagship polymer incident and both safe/unsafe branches.

The data is synthetic and non-confidential. A trusted baseline is generated in Celsius,
then instrument firmware v4.2 emits exactly 187 rows of batch B042 in Kelvin. The buggy
``tg-normalizer-v1`` copies those numeric values into a column labelled ``tg_degC``. This
creates a believable silent failure: every pipeline completes, while P-204 moves from rank
18 to rank 1.

The two downstream feature tables intentionally fork:

    cleaned_polymer_dataset -> tg_feature_table -> Tg ranking
                             -> molecular_weight_feature_table -> durability

Only the Tg branch contains the contaminated field.
"""

from __future__ import annotations

import csv
import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = 20260718
N_SAMPLES = 420
B042_START = 181
B042_ROWS = 240
AFFECTED_ROWS = 187
CANDIDATE_ID = "P-204"
BASE_DATE = date(2026, 1, 6)
TRUSTED_RELEASE_MANIFEST = {
    "schema_version": "1.0",
    "trusted_release": {
        "model_version": "tg-gbr-v3",
        "code_version": "ranker-2026.07",
        "normalization_version": "tg-normalizer-v1",
    },
    "scientific_contract": {
        "expected_tg_unit": "degC",
        "instrument_id": "DSC-07",
        "approved_firmware": "v4.1",
    },
}

# name, class, repeat-unit SMILES, Tg_inf (degC), Fox K (degC * g/mol), Mn range
BASE_POLYMERS = [
    ("polystyrene", "vinyl", "*CC(*)c1ccccc1", 100.0, 1.0e5, (1.5e4, 2.0e5)),
    ("poly(methyl methacrylate)", "acrylate", "*CC(*)(C)C(=O)OC", 105.0, 1.2e5,
     (2.0e4, 1.8e5)),
    ("polycarbonate", "carbonate", "*OC(=O)Oc1ccc(cc1)C(C)(C)c1ccc(*)cc1", 147.0,
     1.4e5, (1.5e4, 6.0e4)),
    ("poly(ethylene terephthalate)", "polyester", "*OCCOC(=O)c1ccc(cc1)C(=O)*", 78.0,
     0.9e5, (1.0e4, 5.0e4)),
    ("poly(vinyl chloride)", "vinyl", "*CC(*)Cl", 82.0, 0.8e5, (3.0e4, 1.5e5)),
    ("poly(vinyl acetate)", "vinyl", "*CC(*)OC(C)=O", 30.0, 0.7e5, (2.0e4, 1.2e5)),
    ("poly(methyl acrylate)", "acrylate", "*CC(*)C(=O)OC", 10.0, 0.7e5,
     (2.0e4, 1.2e5)),
    ("polyisobutylene", "vinyl", "*CC(*)(C)C", -70.0, 0.6e5, (5.0e4, 3.0e5)),
    ("poly(dimethylsiloxane)", "silicone", "*O[Si](C)(C)*", -125.0, 0.5e5,
     (1.0e4, 1.0e5)),
    ("polypropylene (atactic)", "polyolefin", "*CC(*)C", -18.0, 0.7e5,
     (3.0e4, 2.0e5)),
]


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _batch_for(sample_number: int) -> str:
    if sample_number < 91:
        return "B040"
    if sample_number < B042_START:
        return "B041"
    return "B042"


def _force_candidate_to_rank_18(records: list[dict]) -> None:
    candidate = next(row for row in records if row["sample_id"] == CANDIDATE_ID)
    other_scores = sorted(
        (row["trusted_tg_degC"] for row in records if row is not candidate), reverse=True
    )
    upper, lower = other_scores[16], other_scores[17]
    candidate["trusted_tg_degC"] = round((upper + lower) / 2.0, 6)


def _affected_ids(records: list[dict]) -> set[str]:
    candidate = next(row for row in records if row["sample_id"] == CANDIDATE_ID)
    eligible = sorted(
        (
            row for row in records
            if row["batch_id"] == "B042"
            and row["sample_id"] != CANDIDATE_ID
            and row["trusted_tg_degC"] < candidate["trusted_tg_degC"]
        ),
        key=lambda row: (row["trusted_tg_degC"], row["sample_id"]),
    )
    if len(eligible) < AFFECTED_ROWS - 1:
        raise RuntimeError("not enough lower-ranked B042 rows to construct the flagship incident")
    return {CANDIDATE_ID, *(row["sample_id"] for row in eligible[: AFFECTED_ROWS - 1])}


def _rankings(records: list[dict], score_key: str, state: str) -> list[dict]:
    ordered = sorted(records, key=lambda row: (-row[score_key], row["sample_id"]))
    return [
        {
            "candidate_id": row["sample_id"],
            "rank": rank,
            "predicted_tg_degC": round(row[score_key], 6),
            "batch_id": row["batch_id"],
            "pipeline_status": "SUCCESS",
            "source_state": state,
        }
        for rank, row in enumerate(ordered, 1)
    ]


def build(output_dir: Path = HERE) -> dict[str, int | str]:
    """Write all deterministic CSV artifacts and return the flagship summary."""
    output_dir = Path(output_dir)
    rng = random.Random(SEED)
    records: list[dict] = []

    for index in range(N_SAMPLES):
        sample_number = index + 1
        name, klass, smiles, tg_inf, fox_k, (mn_lo, mn_hi) = rng.choice(BASE_POLYMERS)
        mn = rng.uniform(mn_lo, mn_hi)
        pdi = rng.uniform(1.5, 2.4)
        mw = mn * pdi
        trusted_tg = tg_inf - fox_k / mn + rng.gauss(0.0, 1.5)
        batch_id = _batch_for(sample_number)
        records.append(
            {
                "sample_id": f"P-{sample_number:03d}",
                "batch_id": batch_id,
                "instrument_id": "DSC-07",
                "instrument_firmware": "v4.2" if batch_id == "B042" else "v4.1",
                "normalization_version": "tg-normalizer-v1",
                "polymer_name": name,
                "polymer_class": klass,
                "smiles": smiles,
                "mn_g_mol": round(mn, 1),
                "mw_g_mol": round(mw, 1),
                "pdi": round(pdi, 3),
                "trusted_tg_degC": round(trusted_tg, 6),
                "measurement_method": "DSC",
                "gpc_calibration": "polystyrene",
                "test_protocol": "ISO 11357-2",
                "measured_on": (BASE_DATE + timedelta(days=index)).isoformat(),
            }
        )

    _force_candidate_to_rank_18(records)
    affected = _affected_ids(records)
    for row in records:
        contaminated = row["sample_id"] in affected
        row["tg_unit"] = "K" if contaminated else "degC"
        row["tg_value"] = round(
            row["trusted_tg_degC"] + (273.15 if contaminated else 0.0), 6
        )
        # v1 is the bug: it trusts the column label and performs no row-level unit conversion.
        row["buggy_tg_degC"] = row["tg_value"]

    raw_fields = [
        "sample_id", "batch_id", "instrument_id", "instrument_firmware",
        "normalization_version", "polymer_name", "polymer_class", "smiles",
        "mn_g_mol", "mw_g_mol", "pdi", "tg_value", "tg_unit",
        "measurement_method", "gpc_calibration", "test_protocol", "measured_on",
    ]
    raw_rows = [{field: row[field] for field in raw_fields} for row in records]
    _write_csv(output_dir / "raw_polymer_experiments.csv", raw_fields, raw_rows)

    baseline_rows = [
        {
            **{field: row[field] for field in raw_fields if field not in {"tg_value", "tg_unit"}},
            "instrument_firmware": "v4.1",
            "tg_value": row["trusted_tg_degC"],
            "tg_unit": "degC",
        }
        for row in records
    ]
    _write_csv(output_dir / "trusted_polymer_baseline.csv", raw_fields, baseline_rows)

    cleaned_fields = [
        "sample_id", "batch_id", "instrument_id", "instrument_firmware",
        "normalization_version", "polymer_name", "polymer_class", "smiles",
        "mn_g_mol", "mw_g_mol", "pdi", "tg_degC",
    ]
    cleaned_rows = [
        {
            **{field: row[field] for field in cleaned_fields if field != "tg_degC"},
            "tg_degC": row["buggy_tg_degC"],
        }
        for row in records
    ]
    _write_csv(output_dir / "cleaned_polymer_dataset.csv", cleaned_fields, cleaned_rows)

    class_codes = {kind: index for index, kind in enumerate(sorted({p[1] for p in BASE_POLYMERS}))}
    tg_fields = ["sample_id", "batch_id", "log10_mn", "pdi", "class_code", "tg_degC"]
    tg_rows = [
        {
            "sample_id": row["sample_id"],
            "batch_id": row["batch_id"],
            "log10_mn": round(math.log10(row["mn_g_mol"]), 6),
            "pdi": row["pdi"],
            "class_code": class_codes[row["polymer_class"]],
            "tg_degC": row["buggy_tg_degC"],
        }
        for row in records
    ]
    _write_csv(output_dir / "tg_feature_table.csv", tg_fields, tg_rows)
    # Compatibility artifact for the original 13 regression scenarios. It is not a node in
    # the new flagship graph.
    _write_csv(output_dir / "polymer_feature_table.csv", tg_fields, tg_rows)

    mw_fields = ["sample_id", "batch_id", "mn_g_mol", "mw_g_mol", "pdi"]
    mw_rows = [{field: row[field] for field in mw_fields} for row in records]
    _write_csv(output_dir / "molecular_weight_feature_table.csv", mw_fields, mw_rows)

    before = _rankings(records, "trusted_tg_degC", "TRUSTED_BASELINE")
    after = _rankings(records, "buggy_tg_degC", "CURRENT_B042")
    ranking_fields = [
        "candidate_id", "rank", "predicted_tg_degC", "batch_id", "pipeline_status",
        "source_state",
    ]
    _write_csv(output_dir / "candidate_ranking_before.csv", ranking_fields, before)
    _write_csv(output_dir / "candidate_ranking_after.csv", ranking_fields, after)
    (output_dir / "trusted_release_manifest.json").write_text(
        json.dumps(TRUSTED_RELEASE_MANIFEST, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    before_rank = next(row["rank"] for row in before if row["candidate_id"] == CANDIDATE_ID)
    after_rank = next(row["rank"] for row in after if row["candidate_id"] == CANDIDATE_ID)
    if (before_rank, after_rank, len(affected)) != (18, 1, AFFECTED_ROWS):
        raise RuntimeError("flagship ground truth drifted; refusing to write a misleading demo")

    summary: dict[str, int | str] = {
        "samples": N_SAMPLES,
        "b042_rows": B042_ROWS,
        "affected_rows": len(affected),
        "candidate_id": CANDIDATE_ID,
        "rank_before": before_rank,
        "rank_after": after_rank,
    }
    print(
        f"wrote {N_SAMPLES} samples; B042 mixed units={len(affected)}; "
        f"{CANDIDATE_ID} rank {before_rank} -> {after_rank}"
    )
    return summary


if __name__ == "__main__":
    build()
