"""Small fail-closed unified-diff applier for remote change providers.

Local publication delegates patch semantics to ``git apply``. A GitHub Git Data
API adapter does not have a worktree, so it needs to materialize the repaired
file before creating a blob. This module intentionally supports one text file
and standard unified hunks only; ambiguity, context drift, or extra file
sections are rejected rather than guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath


class UnifiedPatchError(ValueError):
    pass


@dataclass(frozen=True)
class AppliedPatch:
    path: str
    content: str


_HUNK = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@(?: .*)?$"
)


def _header_path(line: str, prefix: str) -> str:
    if not line.startswith(prefix):
        raise UnifiedPatchError(f"expected {prefix.strip()} patch header")
    raw = line[len(prefix) :].split("\t", 1)[0].strip()
    if raw == "/dev/null":
        raise UnifiedPatchError("file creation/deletion patches are not supported")
    if raw.startswith(("a/", "b/")):
        raw = raw[2:]
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise UnifiedPatchError(f"unsafe patched path: {raw!r}")
    return path.as_posix()


def apply_unified_patch(original: str, patch: str) -> AppliedPatch:
    """Apply a single-file unified diff only when every context line matches."""

    lines = patch.splitlines(keepends=True)
    if len(lines) < 3:
        raise UnifiedPatchError("unified patch is incomplete")
    old_path = _header_path(lines[0], "--- ")
    new_path = _header_path(lines[1], "+++ ")
    if old_path != new_path:
        raise UnifiedPatchError("patch path changes are not supported")

    source = original.splitlines(keepends=True)
    output: list[str] = []
    source_cursor = 0
    index = 2
    saw_hunk = False

    while index < len(lines):
        match = _HUNK.match(lines[index].rstrip("\n"))
        if match is None:
            raise UnifiedPatchError(
                f"unexpected patch content outside a hunk: {lines[index]!r}"
            )
        saw_hunk = True
        old_start = int(match.group("old_start"))
        old_count = int(match.group("old_count") or "1")
        new_count = int(match.group("new_count") or "1")
        target_cursor = max(old_start - 1, 0)
        if target_cursor < source_cursor or target_cursor > len(source):
            raise UnifiedPatchError("patch hunk is out of order or outside the source")
        output.extend(source[source_cursor:target_cursor])
        source_cursor = target_cursor
        index += 1
        consumed_old = 0
        emitted_new = 0

        while index < len(lines) and not lines[index].startswith("@@ "):
            line = lines[index]
            if line.startswith("\\ No newline at end of file"):
                index += 1
                continue
            if not line or line[0] not in {" ", "+", "-"}:
                raise UnifiedPatchError(f"unsupported unified patch line: {line!r}")
            marker, content = line[0], line[1:]
            if marker in {" ", "-"}:
                if source_cursor >= len(source) or source[source_cursor] != content:
                    raise UnifiedPatchError(
                        f"patch context drift at source line {source_cursor + 1}"
                    )
                source_cursor += 1
                consumed_old += 1
            if marker in {" ", "+"}:
                output.append(content)
                emitted_new += 1
            index += 1

        if consumed_old != old_count or emitted_new != new_count:
            raise UnifiedPatchError(
                "patch hunk line counts do not match its unified-diff header"
            )

    if not saw_hunk:
        raise UnifiedPatchError("unified patch contains no hunks")
    output.extend(source[source_cursor:])
    return AppliedPatch(path=new_path, content="".join(output))
