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


def test_no_change_returns_empty() -> None:
    snap = Snapshot(fields={"a": "double"}, units={"a": "g/mol"})
    assert detect_changes(snap, snap) == []
