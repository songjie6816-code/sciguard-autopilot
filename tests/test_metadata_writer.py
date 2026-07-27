"""Unit tests for read-modify-write safety, with a fake graph (no DataHub)."""

from datahub.metadata.schema_classes import (
    DatasetPropertiesClass,
    GlobalTagsClass,
    MLModelPropertiesClass,
    TagAssociationClass,
    VersionTagClass,
)

from datahub_client import metadata_writer as W

URN = "urn:li:dataset:(urn:li:dataPlatform:polymer_rnd,x,PROD)"


class FakeGraph:
    def __init__(self, aspects: dict) -> None:
        self.store = aspects
        self.emitted: list = []

    def get_aspect(self, urn: str, cls):
        return self.store.get(cls.__name__)

    def emit(self, mcp) -> None:
        self.emitted.append(mcp.aspect)


def test_add_custom_properties_preserves_name_and_existing_props() -> None:
    seed = DatasetPropertiesClass(
        name="Tg measurements", description="d", customProperties={"a": "1"}
    )
    g = FakeGraph({"DatasetPropertiesClass": seed})
    merged = W.add_custom_properties(g, URN, {"sciguard:risk": "critical"})
    assert merged == {"a": "1", "sciguard:risk": "critical"}
    written = g.emitted[0]
    assert written.name == "Tg measurements"        # not clobbered
    assert written.description == "d"
    assert written.customProperties == merged


def test_add_custom_properties_noop_when_unchanged() -> None:
    seed = DatasetPropertiesClass(name="n", customProperties={"a": "1"})
    g = FakeGraph({"DatasetPropertiesClass": seed})
    W.add_custom_properties(g, URN, {"a": "1"})
    assert g.emitted == []


def test_remove_custom_properties_preserves_unrelated_metadata() -> None:
    seed = DatasetPropertiesClass(
        name="n",
        description="keep",
        customProperties={"keep": "1", "sciguard:incident": "temporary"},
    )
    g = FakeGraph({"DatasetPropertiesClass": seed})
    remaining = W.remove_custom_properties(g, URN, ["sciguard:incident"])
    assert remaining == {"keep": "1"}
    assert g.emitted[0].name == "n"
    assert g.emitted[0].description == "keep"


def test_add_tags_merges_without_dropping_existing() -> None:
    seed = GlobalTagsClass(tags=[TagAssociationClass(tag="urn:li:tag:keep")])
    g = FakeGraph({"GlobalTagsClass": seed})
    result = W.add_tags(g, URN, ["urn:li:tag:new"])
    assert result == ["urn:li:tag:keep", "urn:li:tag:new"]
    assert [t.tag for t in g.emitted[0].tags] == result


def test_add_tags_idempotent_no_emit() -> None:
    seed = GlobalTagsClass(tags=[TagAssociationClass(tag="urn:li:tag:keep")])
    g = FakeGraph({"GlobalTagsClass": seed})
    W.add_tags(g, URN, ["urn:li:tag:keep"])
    assert g.emitted == []


def test_native_aspect_custom_properties_preserve_model_lifecycle_fields() -> None:
    seed = MLModelPropertiesClass(
        name="Tg Model",
        version=VersionTagClass(versionTag="tg-gbr-v3"),
        mlFeatures=["urn:feature:tg"],
        deployments=["urn:deployment:prod"],
        customProperties={"existing": "keep"},
    )
    graph = FakeGraph({"MLModelPropertiesClass": seed})

    merged = W.add_aspect_custom_properties(
        graph,
        "urn:li:mlModel:(urn:li:dataPlatform:polymer_rnd,tg_prediction_model,PROD)",
        MLModelPropertiesClass,
        {"sciguard:incident_state": "AT_RISK"},
    )

    written = graph.emitted[0]
    assert merged == {"existing": "keep", "sciguard:incident_state": "AT_RISK"}
    assert written.name == "Tg Model"
    assert written.version.versionTag == "tg-gbr-v3"
    assert written.mlFeatures == ["urn:feature:tg"]
    assert written.deployments == ["urn:deployment:prod"]


def test_native_aspect_write_fails_closed_when_projection_is_missing() -> None:
    graph = FakeGraph({})
    try:
        W.add_aspect_custom_properties(
            graph,
            "urn:missing",
            MLModelPropertiesClass,
            {"sciguard:incident_state": "AT_RISK"},
        )
    except LookupError as exc:
        assert "aspect is missing" in str(exc)
    else:
        raise AssertionError("missing native projection must not be silently ignored")
