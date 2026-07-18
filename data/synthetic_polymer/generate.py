"""Generate a synthetic, non-confidential polymer Tg dataset and its derived
tables. Deterministic (fixed seed) so the whole pipeline is reproducible.

Scientific grounding (all public textbook knowledge, no proprietary data):
- Realistic repeat-unit SMILES and glass-transition temperatures for common
  polymers.
- Molecular weight dependence of Tg via the Fox-Flory relation
  Tg(Mn) = Tg_inf - K / Mn.

Three datasets are produced, forming the demo lineage:
  raw_polymer_experiments -> cleaned_polymer_dataset -> polymer_feature_table
"""

from __future__ import annotations

import csv
import math
import random
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = 20260718
N_SAMPLES = 180
BASE_DATE = date(2026, 1, 6)

# name, class, repeat-unit SMILES, Tg_inf (degC), Fox K (degC * g/mol), Mn range
BASE_POLYMERS = [
    ("polystyrene", "vinyl", "*CC(*)c1ccccc1", 100.0, 1.0e5, (1.5e4, 2.0e5)),
    ("poly(methyl methacrylate)", "acrylate", "*CC(*)(C)C(=O)OC", 105.0, 1.2e5, (2.0e4, 1.8e5)),
    ("polycarbonate", "carbonate", "*OC(=O)Oc1ccc(cc1)C(C)(C)c1ccc(*)cc1", 147.0, 1.4e5, (1.5e4, 6.0e4)),
    ("poly(ethylene terephthalate)", "polyester", "*OCCOC(=O)c1ccc(cc1)C(=O)*", 78.0, 0.9e5, (1.0e4, 5.0e4)),
    ("poly(vinyl chloride)", "vinyl", "*CC(*)Cl", 82.0, 0.8e5, (3.0e4, 1.5e5)),
    ("poly(vinyl acetate)", "vinyl", "*CC(*)OC(C)=O", 30.0, 0.7e5, (2.0e4, 1.2e5)),
    ("poly(methyl acrylate)", "acrylate", "*CC(*)C(=O)OC", 10.0, 0.7e5, (2.0e4, 1.2e5)),
    ("polyisobutylene", "vinyl", "*CC(*)(C)C", -70.0, 0.6e5, (5.0e4, 3.0e5)),
    ("poly(dimethylsiloxane)", "silicone", "*O[Si](C)(C)*", -125.0, 0.5e5, (1.0e4, 1.0e5)),
    ("polypropylene (atactic)", "polyolefin", "*CC(*)C", -18.0, 0.7e5, (3.0e4, 2.0e5)),
]


def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def build() -> None:
    rng = random.Random(SEED)

    raw_header = [
        "sample_id", "polymer_name", "polymer_class", "smiles",
        "mn_g_mol", "mw_g_mol", "pdi",
        "tg_value", "tg_unit", "measurement_method", "gpc_calibration",
        "test_protocol", "measured_on",
    ]
    raw_rows: list[list] = []

    for i in range(N_SAMPLES):
        name, klass, smiles, tg_inf, fox_k, (mn_lo, mn_hi) = rng.choice(BASE_POLYMERS)
        mn = rng.uniform(mn_lo, mn_hi)
        pdi = rng.uniform(1.5, 2.4)
        mw = mn * pdi
        # Fox-Flory Mn dependence plus small measurement noise.
        tg = tg_inf - fox_k / mn + rng.gauss(0.0, 1.5)
        measured_on = (BASE_DATE + timedelta(days=i)).isoformat()

        raw_rows.append([
            f"PLY-{i + 1:04d}", name, klass, smiles,
            round(mn, 1), round(mw, 1), round(pdi, 3),
            round(tg, 2), "degC", "DSC", "polystyrene",
            "ISO 11357-2", measured_on,
        ])

    _write_csv(HERE / "raw_polymer_experiments.csv", raw_header, raw_rows)

    # cleaned: normalize column names, keep Tg explicitly in Celsius, drop the
    # raw provenance columns the model does not consume.
    cleaned_header = [
        "sample_id", "polymer_name", "polymer_class", "smiles",
        "mn_g_mol", "mw_g_mol", "pdi", "tg_degC",
    ]
    cleaned_rows = [
        [r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]] for r in raw_rows
    ]
    _write_csv(HERE / "cleaned_polymer_dataset.csv", cleaned_header, cleaned_rows)

    # features: numeric inputs the Tg model actually trains on, plus target.
    class_codes = {k: idx for idx, k in enumerate(sorted({p[1] for p in BASE_POLYMERS}))}
    feat_header = ["sample_id", "log10_mn", "pdi", "class_code", "tg_degC"]
    feat_rows = [
        [r[0], round(math.log10(r[4]), 4), r[6], class_codes[r[2]], r[7]]
        for r in raw_rows
    ]
    _write_csv(HERE / "polymer_feature_table.csv", feat_header, feat_rows)

    print(f"wrote {N_SAMPLES} samples across {len(BASE_POLYMERS)} polymers")
    print(f"  raw     -> {HERE / 'raw_polymer_experiments.csv'}")
    print(f"  cleaned -> {HERE / 'cleaned_polymer_dataset.csv'}")
    print(f"  features-> {HERE / 'polymer_feature_table.csv'}")
    print(f"  class_codes = {class_codes}")


if __name__ == "__main__":
    build()
