"""Detect material changes between two scientific-dataset metadata snapshots.

A snapshot is the schema (field -> native type) plus declared units
(field -> unit). Comparing the DataHub "before" against an incoming "after"
turns a silent change (a unit swap, a dropped column) into an explicit,
structured event the rest of the pipeline can reason about.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class ChangeKind(str, Enum):
    UNIT_CHANGE = "unit_change"
    FIELD_REMOVED = "field_removed"
    FIELD_ADDED = "field_added"
    TYPE_CHANGED = "type_changed"


class Snapshot(BaseModel):
    """Metadata state of a dataset at one point in time."""

    fields: dict[str, str] = {}   # field -> native type
    units: dict[str, str] = {}    # field -> unit


class Change(BaseModel):
    kind: ChangeKind
    field: str
    before: str | None = None
    after: str | None = None

    def describe(self) -> str:
        if self.kind is ChangeKind.UNIT_CHANGE:
            return f"unit of '{self.field}' changed {self.before} -> {self.after}"
        if self.kind is ChangeKind.FIELD_REMOVED:
            return f"field '{self.field}' was removed"
        if self.kind is ChangeKind.FIELD_ADDED:
            return f"field '{self.field}' was added"
        return f"type of '{self.field}' changed {self.before} -> {self.after}"


def detect_changes(before: Snapshot, after: Snapshot) -> list[Change]:
    """Return the structured differences from `before` to `after`."""
    changes: list[Change] = []

    for field in before.fields:
        if field not in after.fields:
            changes.append(Change(kind=ChangeKind.FIELD_REMOVED, field=field))
        elif before.fields[field] != after.fields[field]:
            changes.append(
                Change(
                    kind=ChangeKind.TYPE_CHANGED,
                    field=field,
                    before=before.fields[field],
                    after=after.fields[field],
                )
            )
    for field in after.fields:
        if field not in before.fields:
            changes.append(Change(kind=ChangeKind.FIELD_ADDED, field=field))

    for field, before_unit in before.units.items():
        after_unit = after.units.get(field)
        if after_unit is not None and after_unit != before_unit:
            changes.append(
                Change(
                    kind=ChangeKind.UNIT_CHANGE,
                    field=field,
                    before=before_unit,
                    after=after_unit,
                )
            )

    return changes
