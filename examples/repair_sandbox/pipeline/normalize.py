def normalize_tg(value: float, unit: str) -> float:
    # v1 trusted the destination column label and silently copied mixed units.
    return float(value)
