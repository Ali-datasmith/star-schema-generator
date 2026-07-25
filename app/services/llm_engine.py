"""
llm_engine.py

Structured-output wrapper around the Google GenAI SDK.
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from dataclasses import dataclass
from typing import Any, List, Optional

from google import genai
from google.genai import types as genai_types

from app.schemas import StarSchemaResponse

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3.5-flash"


class SchemaGenerationError(Exception):
    """Raised when the LLM call itself fails (network, auth, quota, timeout)."""


class SchemaValidationError(Exception):
    """Raised when the LLM response cannot be validated against StarSchemaResponse."""


SYSTEM_INSTRUCTION = """You are a senior data warehouse architect.

Given a raw JSON payload from a source system, design a Kimball-style dimensional star schema for DuckDB.

Rules:
1. Produce exactly one fact table.
2. Produce one or more dimension tables.
3. All table and column names must be lower_snake_case.
4. Dimension tables must be prefixed with 'dim_'.
5. Dimension tables must carry an integer surrogate key.
6. The fact table must be prefixed with 'fct_'.
7. The fact table must reference every dimension surrogate key as a foreign key.
8. Emit fully executable DuckDB DDL as a STRUCTURAL SKELETON ONLY: CREATE TABLE
   statements, with every dimension table declared BEFORE the fact table so that
   REFERENCES resolve. Include PRIMARY KEY constraints on surrogate keys and
   FOREIGN KEY (REFERENCES) constraints on the fact table's foreign keys.
9. Surrogate key columns in the DDL are plain `INTEGER ... PRIMARY KEY` with NO
   default value. DO NOT emit CREATE SEQUENCE. DO NOT use nextval(), serial,
   autoincrement, or any auto-assignment default anywhere in the DDL.
10. Surrogate key VALUES are owned EXCLUSIVELY by the dbt mart models. In every
    dim_*.sql, assign the surrogate key as
    `row_number() over (order by <deterministic natural/business key column(s)>)`.
11. In fct_*.sql, NEVER recompute a dimension surrogate key. Join the staged rows
    to each dim_*.sql on its natural/business key and SELECT the dimension's
    surrogate key column, so foreign-key values are inherited from the dimension,
    not regenerated. The fact table's own surrogate key is likewise assigned in
    fct_*.sql via `row_number() over (order by <deterministic grain columns>)`.
12. Because the DDL carries no auto-assignment, the DDL and the dbt models can
    never disagree on a key value: the DDL defines shape and referential
    integrity, dbt defines the numbers. Keep them consistent by construction.
13. Emit complete dbt Core staging models, mart models, and schema.yml.
14. Include unique, not_null, and relationships tests in schema.yml.
15. Use only simple DuckDB data types from the response schema.
16. Keep dbt models concise but production-ready.
17. Return only a valid JSON object matching the response schema.
18. Do not include markdown fences, prose, or commentary.
"""


def _get_config_value(key: str, default: str = "") -> str:
    try:
        import streamlit as st
        value = st.secrets.get(key, os.environ.get(key, default))
        return str(value or default)
    except Exception:
        return str(os.environ.get(key, default) or default)


def resolve_model_chain() -> List[str]:
    primary = _get_config_value("GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    fallback_raw = _get_config_value("GEMINI_FALLBACK_MODELS", "").strip()
    chain: List[str] = [primary]
    if fallback_raw:
        for model in fallback_raw.split(","):
            model = model.strip()
            if model and model not in chain:
                chain.append(model)
    return chain


def _error_text(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}".lower()


def _is_transient_error(exc: Exception) -> bool:
    text = _error_text(exc)
    transient_codes = ("429", "500", "502", "503", "504")
    transient_keywords = (
        "quota", "resource_exhausted", "unavailable", "overloaded",
        "timeout", "deadline", "connection", "aborted", "internal",
        "server error", "temporarily",
    )
    return any(code in text for code in transient_codes) or any(
        keyword in text for keyword in transient_keywords
    )


def _is_not_found_error(exc: Exception) -> bool:
    text = _error_text(exc)
    return (
        "404" in text or "not_found" in text
        or "not found" in text or "model not found" in text
    )


def _is_auth_error(exc: Exception) -> bool:
    text = _error_text(exc)
    return (
        "401" in text or "403" in text or "api_key" in text
        or "api key" in text or "auth" in text or "permission" in text
        or "unauthenticated" in text
    )


def classify_error(exc: Exception) -> str:
    text = _error_text(exc)
    if (
        isinstance(exc, SchemaValidationError)
        or "validation" in text or "schema" in text or "pydantic" in text
    ):
        return f"Schema Validation Failure: {exc}"
    if "quota" in text or "429" in text or "resource_exhausted" in text:
        return f"API Quota Exhaustion: {exc}"
    if (
        "timeout" in text or "504" in text or "deadline" in text
        or "503" in text or "unavailable" in text or "overloaded" in text
    ):
        return f"Network Timeout / Server Unavailable: {exc}"
    if (
        "api_key" in text or "api key" in text or "auth" in text
        or "401" in text or "403" in text
    ):
        return f"Authentication Error: {exc}"
    if "404" in text or "not_found" in text or "not found" in text:
        return f"Model / Resource Not Found: {exc}"
    return f"Unexpected System Error ({type(exc).__name__}): {exc}"


@dataclass
class LLMCallResult:
    response: StarSchemaResponse
    raw_text: str
    latency_seconds: float
    prompt_token_count: int
    candidates_token_count: int
    model_used: str


class StarSchemaGenerator:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_chain: Optional[List[str]] = None,
    ) -> None:
        cleaned_key = (api_key or "").strip()
        if cleaned_key:
            self._client = genai.Client(api_key=cleaned_key)
        else:
            self._client = genai.Client()
        self._model_chain = model_chain or resolve_model_chain()
        self._max_attempts_per_model = 2
        self._base_backoff_seconds = 1.0

    def _parse_response(self, response: Any) -> tuple[StarSchemaResponse, str]:
        text = getattr(response, "text", None) or ""
        parsed = getattr(response, "parsed", None)
        try:
            if parsed is not None:
                if isinstance(parsed, StarSchemaResponse):
                    validated = parsed
                elif hasattr(parsed, "model_dump"):
                    validated = StarSchemaResponse.model_validate(parsed.model_dump())
                else:
                    validated = StarSchemaResponse.model_validate(parsed)
            elif text:
                validated = StarSchemaResponse.model_validate_json(text)
            else:
                raise SchemaGenerationError("Gemini returned an empty response body.")
        except SchemaGenerationError:
            raise
        except Exception as exc:
            preview = text[:2000] if text else "<no response text>"
            raise SchemaValidationError(
                f"LLM output failed StarSchemaResponse validation: {exc}\n"
                f"Raw output preview: {preview}"
            ) from exc
        if not text:
            try:
                text = json.dumps(validated.model_dump(mode="json"), default=str)
            except Exception:
                text = ""
        return validated, text

    def _generate_once(
        self, model: str, raw_json_payload: str
    ) -> tuple[StarSchemaResponse, str, Any]:
        config_kwargs: dict[str, Any] = {
            "system_instruction": SYSTEM_INSTRUCTION,
            "response_mime_type": "application/json",
            "response_schema": StarSchemaResponse,
            "temperature": 0.2,
        }
        max_output_tokens = _get_config_value("GEMINI_MAX_OUTPUT_TOKENS", "").strip()
        if max_output_tokens.isdigit():
            config_kwargs["max_output_tokens"] = int(max_output_tokens)
        response = self._client.models.generate_content(
            model=model,
            contents=raw_json_payload,
            config=genai_types.GenerateContentConfig(**config_kwargs),
        )
        validated, raw_text = self._parse_response(response)
        usage = getattr(response, "usage_metadata", None)
        return validated, raw_text, usage

    def generate(self, raw_json_payload: str) -> LLMCallResult:
        start = time.perf_counter()
        last_exception: Optional[Exception] = None
        for model in self._model_chain:
            for attempt in range(1, self._max_attempts_per_model + 1):
                try:
                    logger.info(
                        "Attempting structured generation with model=%s attempt=%s",
                        model, attempt,
                    )
                    validated, raw_text, usage = self._generate_once(
                        model=model, raw_json_payload=raw_json_payload,
                    )
                    latency = time.perf_counter() - start
                    return LLMCallResult(
                        response=validated,
                        raw_text=raw_text,
                        latency_seconds=latency,
                        prompt_token_count=getattr(usage, "prompt_token_count", 0) or 0,
                        candidates_token_count=getattr(usage, "candidates_token_count", 0) or 0,
                        model_used=model,
                    )
                except Exception as exc:
                    last_exception = exc
                    logger.warning("Model %s attempt %s failed: %s", model, attempt, exc)
                    if _is_auth_error(exc):
                        raise SchemaGenerationError(classify_error(exc)) from exc
                    if _is_transient_error(exc) and attempt < self._max_attempts_per_model:
                        sleep_for = (
                            self._base_backoff_seconds * (2 ** (attempt - 1))
                            + random.uniform(0.0, 0.25)
                        )
                        logger.info("Transient error. Sleeping %.2fs before retry.", sleep_for)
                        time.sleep(sleep_for)
                        continue
                    break
        raise SchemaGenerationError(
            classify_error(last_exception)
            if last_exception
            else "All models in the fallback chain failed."
        ) from last_exception