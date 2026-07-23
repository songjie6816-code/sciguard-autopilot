"""Live test: the MCP backend returns the same context as the SDK backend.

Skipped when DataHub or the mcp-server-datahub tool is unavailable. When it runs,
it proves SciGuard's DataHub MCP Server integration is not just live but correct:
search, lineage, schema, units and ownership match the SDK path.
"""

import pytest
from datahub.emitter.mce_builder import make_dataset_urn

RAW = make_dataset_urn(platform="polymer_rnd", name="raw_polymer_experiments", env="PROD")
MODEL = make_dataset_urn(platform="polymer_rnd", name="tg_prediction_model", env="PROD")
REPORT = make_dataset_urn(
    platform="polymer_rnd", name="candidate_ranking_report", env="PROD"
)


@pytest.fixture(scope="module")
def backends():
    try:
        from datahub_client.backends import SdkReader
        from datahub_client.mcp_client import DataHubMCP
        from datahub_client.metadata_reader import connect

        sdk = SdkReader(connect())
        mcp = DataHubMCP()
    except Exception as exc:  # noqa: BLE001 - any setup failure skips the live test
        pytest.skip(f"DataHub or MCP server unavailable: {exc}")
    yield sdk, mcp
    mcp.close()


def test_downstream_matches(backends) -> None:
    sdk, mcp = backends
    sdk_names = {h.name for h in sdk.get_all_downstream(RAW)}
    mcp_names = {h.name for h in mcp.get_all_downstream(RAW)}
    assert sdk_names == mcp_names
    assert "tg_prediction_model" in mcp_names


def test_schema_matches(backends) -> None:
    sdk, mcp = backends
    assert {f["path"] for f in sdk.get_schema_fields(RAW)} == {
        f["path"] for f in mcp.get_schema_fields(RAW)
    }


def test_units_match(backends) -> None:
    sdk, mcp = backends
    assert sdk.get_units(RAW) == mcp.get_units(RAW)
    # WP1's flagship batch is intentionally mixed-unit; parity must preserve
    # that governance signal instead of silently presenting an all-Celsius source.
    assert mcp.get_units(RAW).get("tg_value") == "mixed:degC|K"


def test_owners_match(backends) -> None:
    sdk, mcp = backends
    assert sdk.get_owners(MODEL) == mcp.get_owners(MODEL)


def test_reverse_lineage_matches(backends) -> None:
    sdk, mcp = backends
    sdk_names = {hit.name for hit in sdk.get_all_upstream(REPORT)}
    mcp_names = {hit.name for hit in mcp.get_all_upstream(REPORT)}
    assert sdk_names == mcp_names
    assert "instrument_batch_B042" in mcp_names


def test_wp3_governance_and_release_context_matches(backends) -> None:
    sdk, mcp = backends
    sdk_context = sdk.get_asset_context(MODEL)
    mcp_context = mcp.get_asset_context(MODEL)
    for key in ("name", "owners", "tags", "terms", "properties"):
        assert sdk_context[key] == mcp_context[key]
    assert sdk_context["properties"]["model_version"] == "tg-gbr-v3"
    assert sdk_context["properties"]["code_version"] == "ranker-2026.07"
    assert sdk_context["assertion_history"] == []
    assert sdk_context["assertions_supported"] is True
    assert mcp_context["assertion_history"] == []
    assert mcp_context["assertions_supported"] is False


def test_field_lineage_sdk_fallback_is_explicit_and_matches(backends) -> None:
    sdk, mcp = backends
    assert mcp.get_fine_grained_lineage(RAW) == sdk.get_fine_grained_lineage(RAW)
    receipt = mcp.capability_receipt()
    assert receipt["required_component"] == "DATAHUB_MCP_SERVER"
    assert "dataset_lineage" in receipt["decision_inputs_via_mcp"]
    assert "fine_grained_lineage" in receipt["sdk_fallbacks"]
    assert "metadata_write_back" in receipt["sdk_fallbacks"]
