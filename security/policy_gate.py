"""Allow only registered, read-only investigation tools for LLM proposals."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from security.redactor import contains_internal_url

READ_ONLY_ALLOWLIST = {
    "search_datasets",
    "get_all_upstream",
    "get_schema_fields",
    "get_units",
    "get_owners",
    "get_asset_context",
}
_SHELL_SYNTAX = re.compile(r"\$\(|`|(?:^|\s)(?:bash|sh|zsh|sudo|curl|wget)\s|[;\n\r]")


class PolicyViolation(RuntimeError):
    pass


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any]


class ReadOnlyToolExecutor:
    def __init__(self, tools: dict[str, Callable[..., Any]]) -> None:
        illegal = set(tools) - READ_ONLY_ALLOWLIST
        if illegal:
            raise PolicyViolation(f"registered tools are not read-only allowlisted: {sorted(illegal)}")
        self.tools = dict(tools)

    def validate(self, request: ToolRequest) -> None:
        if request.tool_name not in READ_ONLY_ALLOWLIST:
            raise PolicyViolation(f"tool is not read-only allowlisted: {request.tool_name}")
        if request.tool_name not in self.tools:
            raise PolicyViolation(f"tool is not registered: {request.tool_name}")
        encoded = json.dumps(request.arguments, ensure_ascii=False)
        if len(encoded) > 2_000:
            raise PolicyViolation("tool arguments exceed the bounded size")
        if _SHELL_SYNTAX.search(encoded):
            raise PolicyViolation("shell syntax is forbidden in tool arguments")
        if contains_internal_url(encoded):
            raise PolicyViolation("internal URLs are forbidden in tool arguments")

    def execute(self, request: ToolRequest) -> Any:
        self.validate(request)
        return self.tools[request.tool_name](**request.arguments)
