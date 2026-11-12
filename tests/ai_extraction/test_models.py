import pytest
from pydantic import ValidationError

from cac40val.ai_extraction.models import ExtractionPayload, RiskItem


def test_severity_bounds():
    with pytest.raises(ValidationError):
        RiskItem(category="x", description="y", severity=9, page=1)


def test_payload_schema_has_only_llm_fields():
    props = ExtractionPayload.model_json_schema()["properties"]
    assert set(props) == {"guidance", "risks", "segments", "management_tone"}
