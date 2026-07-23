from security.redactor import REDACTED, Redactor


def test_redactor_removes_secrets_pii_internal_urls_and_raw_rows() -> None:
    value = {
        "api_key": "sk-testSecret123456789",
        "note": (
            "Contact scientist@example.com with Bearer abcdefghijklmnop or visit "
            "http://localhost:8080/internal and https://10.0.0.8/run"
        ),
        "rows": [{"sample_id": "P-204", "tg_value": 412.1}],
        "safe": {"row_count": 420, "model_version": "tg-gbr-v3"},
    }
    result = Redactor().redact(value)
    rendered = str(result.value)

    assert "testSecret" not in rendered
    assert "scientist@example.com" not in rendered
    assert "localhost" not in rendered
    assert "10.0.0.8" not in rendered
    assert "P-204" not in rendered
    assert "412.1" not in rendered
    assert result.value["api_key"] == REDACTED["secret"]
    assert result.value["rows"] == REDACTED["raw_rows"]
    assert result.value["safe"]["row_count"] == 420
    assert result.raw_rows_removed == 1


def test_redactor_keeps_public_urls_and_nonsecret_metadata() -> None:
    result = Redactor().redact(
        {"documentation": "https://datahub.com/docs", "owner": "lab_experimentalist"}
    )
    assert result.value == {
        "documentation": "https://datahub.com/docs",
        "owner": "lab_experimentalist",
    }
    assert result.total_redactions == 0
