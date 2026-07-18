from evaluation.metrics import aggregate, counts


def test_counts_precision_recall_f1() -> None:
    prf = counts(predicted={"a", "b", "x"}, expected={"a", "b", "c"})
    assert (prf.tp, prf.fp, prf.fn) == (2, 1, 1)
    assert prf.precision == 2 / 3
    assert prf.recall == 2 / 3
    assert abs(prf.f1 - 2 / 3) < 1e-9


def test_empty_prediction_has_zero_recall() -> None:
    prf = counts(predicted=set(), expected={"a", "b"})
    assert prf.recall == 0.0
    assert prf.tp == 0 and prf.fn == 2


def test_empty_expected_is_perfect_by_convention() -> None:
    prf = counts(predicted=set(), expected=set())
    assert prf.precision == 1.0 and prf.recall == 1.0


def test_aggregate_micro_averages_counts() -> None:
    a = counts({"a"}, {"a", "b"})       # tp1 fp0 fn1
    b = counts({"c", "d"}, {"c"})       # tp1 fp1 fn0
    agg = aggregate([a, b])
    assert (agg.tp, agg.fp, agg.fn) == (2, 1, 1)
    assert agg.recall == 2 / 3
    assert agg.precision == 2 / 3
