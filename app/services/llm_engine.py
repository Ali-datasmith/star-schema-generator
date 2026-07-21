"""
llm_engine.py
Structured-output wrapper around the Google Gen AI SDK (`google-genai`).
Encapsulates prompt construction, schema-constrained generation, latency
measurement, and Pydantic v2 validation of the model's response.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from google import genai
from google.genai import types as genai_types

from app.schemas import StarSchemaResponse


class SchemaGenerationError(Exception):
    """Raised when the LLM call itself fails (network, auth, quota, timeout)."""


class SchemaValidationError(Exception):
    """Raised when the LLM response cannot be validated against StarSchemaResponse."""


@dataclass
class LLMCallResult:
    response: StarSchemaResponse
    raw_text: str
    latency_seconds: float
    prompt_token_count: int
    candidates_token_count: int


SYSTEM_INSTRUCTION = """You are a senior data warehouse architect. Given a raw JSON payload \
from a source system (e.g. a Stripe webhook or a Shopify order), design a Kimball-style \
dimensional star schema for DuckDB. Produce exactly one fact table and one or more \
dimension tables. All table and column names must be lower_snake_case. Dimension tables \
must be prefixed 'dim_' and carry an integer surrogate key. The fact table must be \
prefixed 'fct_' and reference every dimension surrogate key as a foreign key. Emit fully \
executable DuckDB DDL using CREATE SEQUENCE plus DEFAULT nextval() for every surrogate \
key, and emit complete dbt Core staging models, mart models, and a schema.yml with \
unique, not_null, and relationships tests. Return only the JSON object described by the \
response schema — no prose, no markdown fences, no commentary."""


class StarSchemaGenerator:
    """Thin, testable wrapper around genai.Client() for structured star-schema generation."""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash") -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model

    def generate(self, raw_json_payload: str) -> LLMCallResult:
        start = time.perf_counter()
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=[
                    genai_types.Content(
                        role="user",
                        parts=[genai_types.Part.from_text(text=raw_json_payload)],
                    )
                ],
                config=genai_types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    response_mime_type="application/json",
                    response_schema=StarSchemaResponse.model_json_schema(),
                    temperature=0.1,
                    max_output_tokens=8192,
                ),
            )
        except Exception as exc:
            raise SchemaGenerationError(f"Gemini API call failed: {exc}") from exc

        latency = time.perf_counter() - start

        if response.text is None or response.text.strip() == "":
            raise SchemaGenerationError("Gemini returned an empty response body.")

        try:
            validated = StarSchemaResponse.model_validate_json(response.text)
        except Exception as exc:
            raise SchemaValidationError(
                f"LLM output failed StarSchemaResponse validation: {exc}\n"
                f"Raw output (first 2000 chars): {response.text[:2000]}"
            ) from exc

        usage = response.usage_metadata
        return LLMCallResult(
            response=validated,
            raw_text=response.text,
            latency_seconds=latency,
            prompt_token_count=usage.prompt_token_count if usage else 0,
            candidates_token_count=usage.candidates_token_count if usage else 0,
        )
