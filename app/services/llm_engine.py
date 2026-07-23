"""
llm_engine.py
Structured-output wrapper around the Google Gen AI SDK (`google-genai`).
Encapsulates prompt construction, schema-constrained generation, latency
measurement, and Pydantic v2 validation of the model's response.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Type, TypeVar

from google import genai
from google.genai import types as genai_types
import pydantic

from app.schemas import StarSchemaResponse


class SchemaGenerationError(Exception):
    """Raised when the LLM call itself fails (network, auth, quota, timeout)."""


class SchemaValidationError(Exception):
    """Raised when the LLM response cannot be validated against StarSchemaResponse."""


T = TypeVar("T", bound=pydantic.BaseModel)


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


@dataclass
class LLMCallResult:
    response: StarSchemaResponse
    raw_text: str
    latency_seconds: float
    prompt_token_count: int
    candidates_token_count: int


def _pydantic_to_gemini_schema(model_cls: Type[pydantic.BaseModel]) -> dict:
    """
    Convert a Pydantic v2 model class to a Gemini-compatible JSON Schema dict.

    Gemini's `response_schema` accepts a *flattened* JSON Schema subset. Pydantic v2's
    `model_json_schema()` emits `$defs` + `$ref` pointers for nested models, which the
    Gemini API rejects with `INVALID_ARGUMENT: Unsupported field: $ref`. We inline every
    `$ref` recursively and strip Pydantic-only keywords (`min_length`, `max_length`,
    `pattern`, `extra`, `title`, `default`) that Gemini does not understand.
    """
    raw = model_cls.model_json_schema()
    defs = raw.pop("$defs", {})

    BLOCKED_KEYS = {
        "title", "default", "min_length", "max_length",
        "max_items", "min_items", "extra", "examples",
    }

    def _resolve(node):
        if not isinstance(node, dict):
            return node
        # Inline $ref
        if "$ref" in node:
            ref_name = node["$ref"].split("/")[-1]
            return _resolve({**defs[ref_name], **{k: v for k, v in node.items() if k != "$ref"}})
        # Recurse + strip unsupported keys
        cleaned: dict = {}
        for k, v in node.items():
            if k in BLOCKED_KEYS:
                continue
            if k == "type" and isinstance(v, list):
                # Pydantic emits ["string", "null"] for Optional[str].
                # Gemini accepts only a single type string; fall back to first non-null.
                cleaned["type"] = next(t for t in v if t != "null")
                cleaned.setdefault("nullable", True)
                continue
            if k == "anyOf":
                # Optional fields arrive as anyOf[{type:...},{type:null}]
                non_null = next((s for s in v if s.get("type") != "null"), v[0])
                cleaned.update(_resolve(non_null))
                cleaned["nullable"] = True
                continue
            if k == "properties":
                cleaned["properties"] = {pk: _resolve(pv) for pk, pv in v.items()}
                continue
            if k == "items":
                cleaned["items"] = _resolve(v)
                continue
            if k == "enum":
                cleaned["enum"] = list(v)
                continue
            cleaned[k] = _resolve(v)
        return cleaned

    return _resolve(raw)


class StarSchemaGenerator:
    """Thin, testable wrapper around genai.Client() for structured star-schema generation."""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash") -> None:
        if not api_key:
            raise SchemaGenerationError(
                "Missing Google AI Studio API key. "
                "Set st.secrets['GOOGLE_API_KEY'] or enter it in the sidebar."
            )
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
                    # CRITICAL: pass the flattened schema, not model_json_schema() output.
                    # Gemini does not support $ref/$defs in response_schema.
                    response_schema=_pydantic_to_gemini_schema(StarSchemaResponse),
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
