import pytest

from security.policy_gate import PolicyViolation, ReadOnlyToolExecutor, ToolRequest


def test_only_registered_read_tool_can_execute() -> None:
    calls = []
    executor = ReadOnlyToolExecutor(
        {"get_asset_context": lambda urn: calls.append(urn) or {"urn": urn}}
    )
    result = executor.execute(
        ToolRequest(tool_name="get_asset_context", arguments={"urn": "urn:li:dataset:test"})
    )
    assert result == {"urn": "urn:li:dataset:test"}
    assert calls == ["urn:li:dataset:test"]


@pytest.mark.parametrize(
    "tool_name",
    ["add_tags", "write_datahub", "shell", "exec", "unknown_tool"],
)
def test_write_shell_and_unregistered_tools_are_rejected(tool_name) -> None:
    executor = ReadOnlyToolExecutor({"get_asset_context": lambda urn: {"urn": urn}})
    with pytest.raises(PolicyViolation):
        executor.execute(ToolRequest(tool_name=tool_name, arguments={}))


def test_registered_tool_arguments_cannot_smuggle_shell_or_internal_url() -> None:
    executor = ReadOnlyToolExecutor({"search_datasets": lambda query: []})
    with pytest.raises(PolicyViolation):
        executor.execute(
            ToolRequest(tool_name="search_datasets", arguments={"query": "$(whoami)"})
        )
    with pytest.raises(PolicyViolation):
        executor.execute(
            ToolRequest(
                tool_name="search_datasets",
                arguments={"query": "http://localhost:8080/private"},
            )
        )
