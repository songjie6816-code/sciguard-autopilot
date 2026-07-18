from core.change_detector import ChangeKind, Snapshot, detect_changes


def test_detects_unit_change() -> None:
    before = Snapshot(fields={"tg_value": "double"}, units={"tg_value": "degC"})
    after = Snapshot(fields={"tg_value": "double"}, units={"tg_value": "K"})
    changes = detect_changes(before, after)
    assert len(changes) == 1
    assert changes[0].kind is ChangeKind.UNIT_CHANGE
    assert changes[0].before == "degC" and changes[0].after == "K"


def test_detects_field_removed_added_and_type_change() -> None:
    before = Snapshot(fields={"Mn": "double", "old": "string"})
    after = Snapshot(fields={"Mn": "string", "new": "double"})
    kinds = {(c.kind, c.field) for c in detect_changes(before, after)}
    assert (ChangeKind.TYPE_CHANGED, "Mn") in kinds
    assert (ChangeKind.FIELD_REMOVED, "old") in kinds
    assert (ChangeKind.FIELD_ADDED, "new") in kinds


def test_detects_unit_removed_on_surviving_field() -> None:
    before = Snapshot(fields={"tg_value": "double"}, units={"tg_value": "degC"})
    after = Snapshot(fields={"tg_value": "double"}, units={})
    changes = detect_changes(before, after)
    assert len(changes) == 1
    assert changes[0].kind is ChangeKind.UNIT_CHANGE
    assert changes[0].before == "degC" and changes[0].after == "(none)"


def test_detects_unit_added() -> None:
    before = Snapshot(fields={"tg_value": "double"}, units={})
    after = Snapshot(fields={"tg_value": "double"}, units={"tg_value": "K"})
    changes = detect_changes(before, after)
    assert [c.kind for c in changes] == [ChangeKind.UNIT_CHANGE]
    assert changes[0].before == "(none)" and changes[0].after == "K"


def test_removed_field_with_unit_does_not_double_report() -> None:
    before = Snapshot(fields={"tg_value": "double"}, units={"tg_value": "degC"})
    after = Snapshot(fields={}, units={})
    kinds = [c.kind for c in detect_changes(before, after)]
    assert kinds == [ChangeKind.FIELD_REMOVED]  # no spurious UNIT_CHANGE


def test_added_field_with_unit_does_not_double_report() -> None:
    before = Snapshot(fields={}, units={})
    after = Snapshot(fields={"tg_value": "double"}, units={"tg_value": "K"})
    kinds = [c.kind for c in detect_changes(before, after)]
    assert kinds == [ChangeKind.FIELD_ADDED]  # no spurious UNIT_CHANGE


def test_blank_unit_vs_missing_is_not_a_change() -> None:
    before = Snapshot(fields={"tg_value": "double"}, units={"tg_value": ""})
    after = Snapshot(fields={"tg_value": "double"}, units={})
    assert detect_changes(before, after) == []


def test_no_change_returns_empty() -> None:
    snap = Snapshot(fields={"a": "double"}, units={"a": "g/mol"})
    assert detect_changes(snap, snap) == []
