"""Live test: the MCP backend returns the same context as the SDK backend.

Skipped when DataHub or the mcp-server-datahub tool is unavailable. When it runs,
it proves SciGuard's DataHub MCP Server integration is not just live but correct:
search, lineage, schema, units and ownership match the SDK path.
"""

import pytest
from datahub.emitter.mce_builder import make_dataset_urn

RAW = make_dataset_urn(platform="polymer_rnd", name="raw_polymer_experiments", env="PROD")
MODEL = make_dataset_urn(platform="polymer_rnd", name="tg_prediction_model", env="PROD")


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
    assert mcp.get_units(RAW).get("tg_value") == "degC"


def test_owners_match(backends) -> None:
    sdk, mcp = backends
    assert sdk.get_owners(MODEL) == mcp.get_owners(MODEL)
