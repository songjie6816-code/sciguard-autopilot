import json

import pytest
from datahub.metadata.schema_classes import DatasetPropertiesClass, GlobalTagsClass
from datahub.metadata.schema_classes import TagAssociationClass

from core.reset import reset_incident_metadata
from tests.test_enforcement import StatefulGraph, URN


def test_reset_removes_only_matching_sciguard_metadata_and_tags() -> None:
    graph = StatefulGraph()
    properties = graph.get_aspect(URN, DatasetPropertiesClass)
    properties.customProperties.update(
        {
            "sciguard:incident_id": "inc-reset",
            "sciguard:controlled_urns": json.dumps([URN]),
            "sciguard:status": "at_risk",
            "existing": "keep",
        }
    )
    graph.store[URN]["GlobalTagsClass"] = GlobalTagsClass(
        tags=[
            TagAssociationClass(tag="urn:li:tag:sciguard:at-risk"),
            TagAssociationClass(tag="urn:li:tag:domain:polymer"),
        ]
    )

    receipt = reset_incident_metadata(graph, URN, "inc-reset")

    assert receipt.reset_urns == [URN]
    remaining = graph.get_aspect(URN, DatasetPropertiesClass).customProperties
    assert remaining == {"existing": "keep"}
    tags = [item.tag for item in graph.get_aspect(URN, GlobalTagsClass).tags]
    assert tags == ["urn:li:tag:domain:polymer"]


def test_reset_refuses_to_touch_a_different_incident() -> None:
    graph = StatefulGraph()
    graph.get_aspect(URN, DatasetPropertiesClass).customProperties[
        "sciguard:incident_id"
    ] = "inc-other"
    with pytest.raises(LookupError, match="does not belong"):
        reset_incident_metadata(graph, URN, "inc-requested")
