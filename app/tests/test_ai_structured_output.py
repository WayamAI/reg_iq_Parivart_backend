"""
Structured-output validation for both BaseModel and generic (e.g. list[Model]) targets.

Regression coverage for a real bug: AIService.analyze_document requests
`response_model=list[ExtractedChange]`, but both bundled providers validated a parsed
response with `response_model(**data)`, which only works when response_model is a
BaseModel subclass and data is a mapping. For a list target this raised
`TypeError: list() argument after ** must be a mapping, not list` on every single call --
silently swallowed by the providers' own `except Exception` retry loop, so every
AI-assisted change/obligation extraction always fell back to an empty list, with no
visible error anywhere.
"""

import pytest
from pydantic import BaseModel

from app.ai.base import parse_structured_output, structured_output_schema
from app.ai.schemas import ExtractedChange


class Narrative(BaseModel):
    narrative: str


def test_parses_a_plain_basemodel_target():
    result = parse_structured_output(Narrative, {"narrative": "hello"})
    assert isinstance(result, Narrative)
    assert result.narrative == "hello"


def test_parses_a_list_of_basemodel_target():
    data = [
        {"section": "5.2", "change_type": "OTHER", "summary": "x", "confidence": 0.5},
        {"section": "7.1", "change_type": "OTHER", "summary": "y", "confidence": 0.9},
    ]

    result = parse_structured_output(list[ExtractedChange], data)

    assert isinstance(result, list)
    assert len(result) == 2
    assert all(isinstance(item, ExtractedChange) for item in result)
    assert result[0].section == "5.2"


def test_rejects_invalid_data_for_a_list_target():
    with pytest.raises(Exception):
        parse_structured_output(list[ExtractedChange], [{"section": "5.2"}])


def test_schema_is_produced_for_a_plain_basemodel_target():
    schema = structured_output_schema(Narrative)
    assert schema["type"] == "object"
    assert "narrative" in schema["properties"]


def test_schema_is_produced_for_a_list_target():
    schema = structured_output_schema(list[ExtractedChange])
    assert schema["type"] == "array"
