"""
schemas.py
Pydantic v2 data contracts for the Data Warehouse Star-Schema Generator.

IMPORTANT — Gemini structured-output compatibility:
Gemini's `response_schema` only accepts a restricted subset of JSON Schema
(roughly: type, format, description, enum, properties, required, items,
nullable, minItems/maxItems, additionalProperties). Keywords Pydantic v2
happily emits from `pattern=` and `min_length=` on `str` fields — i.e.
`"pattern"` and `"minLength"` — are NOT reliably accepted by every Gemini
model/endpoint. Sending them produces a 400 INVALID_ARGUMENT ("bad schema")
before the model ever runs. This was the root cause of Project B's 400s.

Fix: string-level `pattern` / `min_length` constraints have been removed
from every `Field(...)` that participates in `response_schema`. The exact
same rules (dim_ prefix, lower_snake_case, non-empty) are now enforced by
`@field_validator` / `@model_validator`, which run locally *after*
Pydantic has already parsed the model's JSON — they never get serialized
into the schema sent to the API, so they cost nothing on the wire and
still reject a malformed response before it reaches the UI.

List-level `min_length` (which maps to the widely-supported `minItems`)
is left in place.

All models are strict (`extra="forbid"`), fully typed, and JSON-schema
exportable via model_json_schema(). No legacy Pydantic v1 methods
(.dict(), .json(), schema()) are used anywhere in this codebase.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class DuckDBDataType(str, Enum):
    """Whitelisted DuckDB column types the LLM is permitted to emit."""
    BIGINT = "BIGINT"
    INTEGER = "INTEGER"
    VARCHAR = "VARCHAR"
    DECIMAL = "DECIMAL(18,2)"
    DOUBLE = "DOUBLE"
    BOOLEAN = "BOOLEAN"
    DATE = "DATE"
    TIMESTAMP = "TIMESTAMP"
    TIME = "TIME"


class MeasureType(str, Enum):
    ADDITIVE = "additive"
    SEMI_ADDITIVE = "semi_additive"
    NON_ADDITIVE = "non_additive"
    NONE = "none"


class DimensionColumn(BaseModel):
    """A single attribute column on a dimension table."""
    model_config = {"extra": "forbid"}

    name: str = Field(
        ...,
        description="Column name in lower_snake_case, e.g. 'customer_email'.",
    )
    data_type: DuckDBDataType = Field(
        ...,
        description="DuckDB-native SQL data type.",
    )
    is_surrogate_key: bool = Field(
        default=False,
        description="True if this column is the auto-generated integer surrogate key.",
    )
    is_business_key: bool = Field(
        default=False,
        description="True if this column is the natural/business key from the source system.",
    )
    description: str = Field(
        ...,
        description="Human-readable description of the column's business meaning.",
    )

    @field_validator("name")
    @classmethod
    def validate_snake_case(cls, v: str) -> str:
        if not v or not _SNAKE_CASE_RE.match(v):
            raise ValueError(f"Column name '{v}' must be non-empty lower_snake_case.")
        return v

    @field_validator("description")
    @classmethod
    def validate_description_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Column description must not be empty.")
        return v


class DimensionTable(BaseModel):
    """A single dimension table, e.g. dim_customer."""
    model_config = {"extra": "forbid"}

    table_name: str = Field(
        ...,
        description="Dimension table name, must be prefixed with 'dim_', e.g. 'dim_customer'.",
    )
    surrogate_key_name: str = Field(
        ...,
        description="Name of the surrogate key column, e.g. 'customer_sk'.",
    )
    attributes: List[DimensionColumn] = Field(
        ...,
        min_length=1,
        description="Ordered list of dimension attribute columns, including the surrogate key column.",
    )

    @field_validator("table_name")
    @classmethod
    def validate_dim_prefix(cls, v: str) -> str:
        if not v.startswith("dim_") or not _SNAKE_CASE_RE.match(v):
            raise ValueError(f"DimensionTable.table_name '{v}' must match 'dim_[a-z0-9_]+'.")
        return v

    @field_validator("surrogate_key_name")
    @classmethod
    def validate_sk_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("surrogate_key_name must not be empty.")
        return v

    @model_validator(mode="after")
    def validate_surrogate_key_present(self) -> "DimensionTable":
        sk_columns = [c for c in self.attributes if c.is_surrogate_key]
        if len(sk_columns) != 1:
            raise ValueError(
                f"DimensionTable '{self.table_name}' must declare exactly one "
                f"is_surrogate_key=True column, found {len(sk_columns)}."
            )
        if sk_columns[0].name != self.surrogate_key_name:
            raise ValueError(
                f"surrogate_key_name '{self.surrogate_key_name}' must match the "
                f"flagged surrogate column name '{sk_columns[0].name}'."
            )
        return self


class FactColumn(BaseModel):
    """A single column on a fact table — key or measure."""
    model_config = {"extra": "forbid"}

    name: str = Field(..., description="Column name in lower_snake_case.")
    data_type: DuckDBDataType = Field(..., description="DuckDB-native SQL data type.")
    is_primary_key: bool = Field(
        default=False,
        description="True if this column is the fact table's primary key.",
    )
    is_foreign_key: bool = Field(
        default=False,
        description="True if this column references a dimension surrogate key.",
    )
    references_table: Optional[str] = Field(
        default=None,
        description="Name of the dimension table referenced. Required if is_foreign_key=True.",
    )
    measure_type: MeasureType = Field(
        default=MeasureType.NONE,
        description="Additive classification of the measure; 'none' for key columns.",
    )

    @field_validator("name")
    @classmethod
    def validate_snake_case(cls, v: str) -> str:
        if not v or not _SNAKE_CASE_RE.match(v):
            raise ValueError(f"FactColumn name '{v}' must be non-empty lower_snake_case.")
        return v

    @model_validator(mode="after")
    def validate_fk_reference(self) -> "FactColumn":
        if self.is_foreign_key and not self.references_table:
            raise ValueError(
                f"FactColumn '{self.name}' has is_foreign_key=True but references_table is not set."
            )
        if not self.is_foreign_key and self.references_table:
            raise ValueError(
                f"FactColumn '{self.name}' sets references_table but is_foreign_key=False."
            )
        return self


class FactTable(BaseModel):
    """The single generated fact table, e.g. fct_orders."""
    model_config = {"extra": "forbid"}

    table_name: str = Field(
        ...,
        description="Fact table name, must be prefixed with 'fct_', e.g. 'fct_orders'.",
    )
    primary_key: str = Field(
        ...,
        description="Name of the fact table's primary key column.",
    )
    foreign_keys: List[str] = Field(
        default_factory=list,
        description="List of foreign key column names on this fact table.",
    )
    measures: List[FactColumn] = Field(
        ...,
        min_length=1,
        description="All columns on the fact table, including keys and measures.",
    )
    ddl_sql: str = Field(
        ...,
        description="Fully-formed CREATE TABLE DDL statement for this fact table.",
    )

    @field_validator("table_name")
    @classmethod
    def validate_fct_prefix(cls, v: str) -> str:
        if not v.startswith("fct_") or not _SNAKE_CASE_RE.match(v):
            raise ValueError(f"FactTable.table_name '{v}' must match 'fct_[a-z0-9_]+'.")
        return v

    @field_validator("primary_key", "ddl_sql")
    @classmethod
    def validate_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Field must not be empty.")
        return v

    @model_validator(mode="after")
    def validate_foreign_keys_present(self) -> "FactTable":
        declared_fk_names = {c.name for c in self.measures if c.is_foreign_key}
        for fk in self.foreign_keys:
            if fk not in declared_fk_names:
                raise ValueError(
                    f"foreign_keys entry '{fk}' has no matching FactColumn with is_foreign_key=True."
                )
        return self


class DbtSqlFile(BaseModel):
    """A single generated dbt SQL file."""
    model_config = {"extra": "forbid"}

    filename: str = Field(
        ...,
        description="File name including extension, e.g. 'stg_stripe_orders.sql'.",
    )
    model_type: str = Field(
        ...,
        description="Category of dbt model: 'staging', 'dimension', or 'fact'.",
    )
    content: str = Field(
        ...,
        description="Full Jinja + SQL file content, copy-pasteable into a dbt project.",
    )

    @field_validator("filename", "content")
    @classmethod
    def validate_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Field must not be empty.")
        return v

    @field_validator("model_type")
    @classmethod
    def validate_model_type(cls, v: str) -> str:
        if v not in {"staging", "dimension", "fact"}:
            raise ValueError(f"model_type '{v}' must be one of staging/dimension/fact.")
        return v


class DbtModelBundle(BaseModel):
    """All dbt Core artifacts required to materialize the star schema."""
    model_config = {"extra": "forbid"}

    staging_models: List[DbtSqlFile] = Field(
        ...,
        min_length=1,
        description="stg_*.sql staging views, one per raw source entity.",
    )
    mart_models: List[DbtSqlFile] = Field(
        ...,
        min_length=1,
        description="dim_*.sql and fct_*.sql mart models.",
    )
    schema_yml: str = Field(
        ...,
        description="Full contents of schema.yml declaring sources, models, columns, and tests.",
    )

    @field_validator("schema_yml")
    @classmethod
    def validate_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("schema_yml must not be empty.")
        return v


class StarSchemaResponse(BaseModel):
    """Root response model returned by the LLM and validated end-to-end."""
    model_config = {"extra": "forbid"}

    fact_table: FactTable = Field(..., description="The single generated fact table.")
    dimensions: List[DimensionTable] = Field(
        ...,
        min_length=1,
        description="All generated dimension tables.",
    )
    duckdb_ddl: str = Field(
        ...,
        description=(
            "Concatenated, executable DuckDB DDL script for the full star schema "
            "(CREATE SEQUENCE statements, CREATE TABLE statements, foreign keys)."
        ),
    )
    dbt_models: DbtModelBundle = Field(
        ...,
        description="Generated dbt Core staging and mart models plus schema.yml.",
    )

    @field_validator("duckdb_ddl")
    @classmethod
    def validate_ddl_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("duckdb_ddl must not be empty.")
        return v

    @model_validator(mode="after")
    def validate_fk_targets_exist(self) -> "StarSchemaResponse":
        dim_names = {d.table_name for d in self.dimensions}
        for col in self.fact_table.measures:
            if col.is_foreign_key and col.references_table not in dim_names:
                raise ValueError(
                    f"FactColumn '{col.name}' references_table='{col.references_table}' "
                    f"does not match any generated DimensionTable.table_name. "
                    f"Available dimensions: {sorted(dim_names)}"
                )
        return self