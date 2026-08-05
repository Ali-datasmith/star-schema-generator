import pytest
from unittest.mock import patch, MagicMock
from app.services.llm_engine import (
    classify_error, _is_transient_error, _is_auth_error, resolve_model_chain,
    StarSchemaGenerator, SchemaGenerationError
)

def test_is_transient_error():
    assert _is_transient_error(Exception("429 Too Many Requests")) is True
    assert _is_transient_error(Exception("503 Service Unavailable")) is True
    assert _is_transient_error(Exception("Quota exceeded")) is True
    assert _is_transient_error(Exception("400 Bad Request")) is False

def test_is_auth_error():
    assert _is_auth_error(Exception("401 Unauthorized")) is True
    assert _is_auth_error(Exception("Invalid API key")) is True
    assert _is_auth_error(Exception("500 Internal Server Error")) is False

def test_classify_error():
    assert "API Quota" in classify_error(Exception("429 quota"))
    assert "Authentication Error" in classify_error(Exception("401 API key invalid"))
    assert "Unexpected System Error" in classify_error(Exception("Something weird"))

@patch('app.services.llm_engine._get_config_value')
def test_resolve_model_chain(mock_get_config):
    mock_get_config.side_effect = lambda k, d="": "gemini-3.5-flash" if k == "GEMINI_MODEL" else "gemini-2.5-flash, gemini-1.5-pro"
    chain = resolve_model_chain()
    assert chain == ["gemini-3.5-flash", "gemini-2.5-flash", "gemini-1.5-pro"]

@patch('app.services.llm_engine.genai.Client')
def test_generate_auth_error_raises_immediately(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.models.generate_content.side_effect = Exception("401 Invalid API key")
    
    gen = StarSchemaGenerator(api_key="bad_key", model_chain=["gemini-3.5-flash", "gemini-2.5-flash"])
    with pytest.raises(SchemaGenerationError, match="Authentication Error"):
        gen.generate('{"test": 1}')
    
    # Auth errors break the loop immediately; should only be called once
    assert mock_client.models.generate_content.call_count == 1

@patch('app.services.llm_engine.genai.Client')
@patch('app.services.llm_engine.time.sleep')
def test_generate_transient_error_retries(mock_sleep, mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.models.generate_content.side_effect = [
        Exception("503 Service Unavailable"), Exception("503 Service Unavailable")
    ]
    
    gen = StarSchemaGenerator(api_key="fake_key", model_chain=["gemini-3.5-flash"])
    gen._max_attempts_per_model = 2
    
    with pytest.raises(SchemaGenerationError, match="Network Timeout"):
        gen.generate('{"test": 1}')
    
    assert mock_client.models.generate_content.call_count == 2
