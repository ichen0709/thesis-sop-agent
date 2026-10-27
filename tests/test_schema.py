import json

import pytest

from sop_agent.schema import SchemaError, extract_payload, json_schema_text, parse_model_response

FIELDS = ("structured_output", "result")

GOOD = {
    "status": "answered",
    "answer": "請備妥文件。",
    "next_steps": [{"text": "備文件", "cite": [0]}],
    "forms": [],
    "deadlines": [{"text": "口試前 14 日", "term": None, "cite": [0]}],
    "contacts": [],
    "citations": [{"doc_id": "a", "version_date": "2025-09-01", "quote": "原文"}],
}


def test_valid_response_parses():
    r = parse_model_response(GOOD)
    assert r.status == "answered"
    assert r.deadlines[0].term is None


def test_valid_json_string_parses():
    assert parse_model_response(json.dumps(GOOD)).status == "answered"


def test_code_fenced_json_parses():
    assert parse_model_response("```json\n" + json.dumps(GOOD) + "\n```").status == "answered"


def test_minimal_not_in_documents_parses():
    assert parse_model_response({"status": "not_in_documents"}).answer == ""


@pytest.mark.parametrize("bad", ["not json", "[]", "123", "", "{"])
def test_not_json_object_is_rejected(bad):
    with pytest.raises(SchemaError):
        parse_model_response(bad)


def test_missing_status_is_rejected():
    with pytest.raises(SchemaError):
        parse_model_response({"answer": "x"})


def test_unknown_status_is_rejected():
    with pytest.raises(SchemaError):
        parse_model_response({"status": "maybe"})


def test_wrong_type_is_rejected():
    bad = dict(GOOD, next_steps=[{"text": "x", "cite": ["0"]}])
    with pytest.raises(SchemaError):
        parse_model_response(bad)


def test_extra_field_is_rejected():
    with pytest.raises(SchemaError):
        parse_model_response(dict(GOOD, comment="多餘欄位"))


def test_citation_missing_quote_is_rejected():
    bad = dict(GOOD, citations=[{"doc_id": "a", "version_date": "2025-09-01"}])
    with pytest.raises(SchemaError):
        parse_model_response(bad)


# --- 外層結果 ---

def test_extract_structured_output_first():
    env = json.dumps({"is_error": False, "structured_output": GOOD, "result": "ignored"})
    assert extract_payload(env, FIELDS) == GOOD


def test_extract_falls_back_to_result_string():
    env = json.dumps({"is_error": False, "result": json.dumps(GOOD)})
    assert parse_model_response(extract_payload(env, FIELDS)).status == "answered"


def test_envelope_error_is_rejected():
    with pytest.raises(SchemaError):
        extract_payload(json.dumps({"is_error": True, "result": "boom"}), FIELDS)


def test_envelope_without_content_is_rejected():
    with pytest.raises(SchemaError):
        extract_payload(json.dumps({"is_error": False}), FIELDS)


def test_envelope_not_json_is_rejected():
    with pytest.raises(SchemaError):
        extract_payload("hello", FIELDS)


def test_json_schema_text_is_valid_json_and_forbids_extra_fields():
    schema = json.loads(json_schema_text())
    assert schema["type"] == "object"
    assert schema.get("additionalProperties") is False
