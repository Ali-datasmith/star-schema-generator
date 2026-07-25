"""
schemas.py

Pydantic v2 data contracts for the Data Warehouse Star-Schema Generator.

IMPORTANT:
This schema is intentionally LLM-friendly.

The original version used strict JSON-schema constraints such as:
- extra="forbid"
- pattern=...
- min_length=...
- enum values like "DECIMAL(18,2)"

Those constraints are useful for runtime validation, but they can cause
Gemini structured-output requests to fail with 400 INVALID_ARGUMENT.

This version removes aggressive LLM-facing constraints and enforces the
same business rules using Pydantic validators after parsing.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class DuckDBDataType(str, Enum):
    """
    Whitelisted DuckDB column types the LLM is permitted to emit.

    These values are intentionally simple strings to avoid structured-output
    schema issues with values such as "DECIMAL(18,2)".
    """

    BIGINT = "BIGINT"
    INTEGER = "INTEGER"
    VARCHAR = "VARCHAR"
    DECIMAL = "DECIMAL"
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


def _normalize_duckdb_type(value: object) -> object:
    """
    Normalize common type aliases into the whitelisted enum values.

    This allows the LLM or downstream users to provide values such as:
    - DECIMAL(18,2)
    - NUMERIC(10,2)
    - TEXT
    - STRING
    - INT
    - DATETIME
    """

    if isinstance(value, DuckDBDataType):
        return value

    if isinstance(value, str):
        v = value.strip().upper()

        if not v:
            return value

        if v.startswith("DECIMAL") or v.startswith("NUMERIC"):
            return DuckDBDataType.DECIMAL.value

        aliases = {
            "TEXT": DuckDBDataType.VARCHAR.value,
            "STRING": DuckDBDataType.VARCHAR.value,
            "CHAR": DuckDBDataType.VARCHAR.value,
            "CHARACTER": DuckDBDataType.VARCHAR.value,
            "INT": DuckDBDataType.INTEGER.value,
            "INT4": DuckDBDataType.INTEGER.value,
            "SIGNED": DuckDBDataType.INTEGER.value,
            "LONG": DuckDBDataType.BIGINT.value,
            "INT8": DuckDBDataType.BIGINT.value,
            "FLOAT": DuckDBDataType.DOUBLE.value,
            "REAL": DuckDBDataType.DOUBLE.value,
            "DOUBLE PRECISION": DuckDBDataType.DOUBLE.value,
            "BOOL": DuckDBDataType.BOOLEAN.value,
            "DATETIME": DuckDBDataType.TIMESTAMP.value,
        }

        return aliases.get(v, v)

    return value


def _validate_identifier(value: object, field_name: str) -> str:
    """
    Validate lower_snake_case identifiers.

    This replaces regex constraints in Field(...) to avoid structured-output
    schema rejection while preserving the same runtime rule.
    """

    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")

    v = value.strip()

    if not v:
        raise ValueError(f"{field_name} must not be empty.")

    if v[0].isdigit():
        raise ValueError(f"{field_name} '{v}' must not start with a digit.")

    if not v.replace("_", "").isalnum() or v != v.lower():
        raise ValueError(f"{field_name} '{v}' must be lower_snake_case.")

    return v


def _validate_table_name(value: object, prefix: str) -> str:
    """
    Validate table names such as:
    - dim_customer
    - fct_orders
    """

    v = _validate_identifier(value, "table_name")

    if not v.startswith(prefix):
        raise ValueError(f"table_name '{v}' must be prefixed with '{prefix}'.")

    if len(v) <= len(prefix):
        raise ValueError(f"table_name '{v}' must contain a name after '{prefix}'.")

    return v


class DimensionColumn(BaseModel):
    """A single attribute column on a dimension table."""

    name: str = Field(
        ...,
        description="Column name in lower_snake_case.",
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
    def validate_name(cls, v: object) -> str:
        return _validate_identifier(v, "name")

    @field_validator("data_type", mode="before")
    @classmethod
    def validate_data_type(cls, v: object) -> object:
        return _normalize_duckdb_type(v)

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: object) -> str:
        if not isinstance(v, str):
            raise ValueError("description must be a string.")

        v_clean = v.strip()

        if not v_clean:
            raise ValueError("description must not be empty.")

        return v_clean


class DimensionTable(BaseModel):
    """A single dimension table, e.g. dim_customer."""

    table_name: str = Field(
        ...,
        description="Dimension table name, must be prefixed with 'dim_'.",
    )

    surrogate_key_name: str = Field(
        ...,
        description="Name of the surrogate key column, e.g. 'customer_sk'.",
    )

    attributes: List[DimensionColumn] = Field(
        ...,
        description=(
            "Ordered list of dimension attribute columns, including the surrogate key column."
        ),
    )

    @field_validator("table_name")
    @classmethod
    def validate_table_name(cls, v: object) -> str:
        return _validate_table_name(v, "dim_")

    @field_validator("surrogate_key_name")
    @classmethod
    def validate_surrogate_key_name(cls, v: object) -> str:
        return _validate_identifier(v, "surrogate_key_name")

    @model_validator(mode="after")
    def validate_surrogate_key_present(self) -> "DimensionTable":
        if not self.attributes:
            raise ValueError(
                f"DimensionTable '{self.table_name}' must declare at least one attribute column."
            )

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

    name: str = Field(
        ...,
        description="Column name in lower_snake_case.",
    )

    data_type: DuckDBDataType = Field(
        ...,
        description="DuckDB-native SQL data type.",
    )

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
    def validate_name(cls, v: object) -> str:
        return _validate_identifier(v, "name")

    @field_validator("data_type", mode="before")
    @classmethod
    def validate_data_type(cls, v: object) -> object:
        return _normalize_duckdb_type(v)

    @field_validator("references_table", mode="before")
    @classmethod
    def normalize_references_table(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            return None
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

    table_name: str = Field(
        ...,
        description="Fact table name, must be prefixed with 'fct_'.",
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
        description="All columns on the fact table, including keys and measures.",
    )

    ddl_sql: str = Field(
        ...,
        description="Fully-formed CREATE TABLE DDL statement for this fact table.",
    )

    @field_validator("table_name")
    @classmethod
    def validate_table_name(cls, v: object) -> str:
        return _validate_table_name(v, "fct_")

    @field_validator("primary_key")
    @classmethod
    def validate_primary_key(cls, v: object) -> str:
        return _validate_identifier(v, "primary_key")

    @field_validator("ddl_sql")
    @classmethod
    def validate_ddl_sql(cls, v: object) -> str:
        if not isinstance(v, str):
            raise ValueError("ddl_sql must be a string.")

        v_clean = v.strip()

        if not v_clean:
            raise ValueError("ddl_sql must not be empty.")

        return v_clean

    @model_validator(mode="after")
    def validate_foreign_keys_present(self) -> "FactTable":
        if not self.measures:
            raise ValueError(
                f"FactTable '{self.table_name}' must declare at least one column in measures."
            )

        declared_fk_names = {c.name for c in self.measures if c.is_foreign_key}

        for fk in self.foreign_keys:
            if fk not in declared_fk_names:
                raise ValueError(
                    f"foreign_keys entry '{fk}' has no matching FactColumn with is_foreign_key=True."
                )

        return self


class DbtSqlFile(BaseModel):
    """A single generated dbt SQL file."""

    filename: str = Field(
        ...,
        description="File name including extension, e.g. 'stg_stripe_orders.sql'.",
    )

    model_type: Literal["staging", "dimension", "fact"] = Field(
        ...,
        description="Category of dbt model: 'staging', 'dimension', or 'fact'.",
    )

    content: str = Field(
        ...,
        description="Full Jinja + SQL file content, copy-pasteable into a dbt project.",
    )

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, v: object) -> str:
        if not isinstance(v, str):
            raise ValueError("filename must be a string.")

        v_clean = v.strip()

        if not v_clean:
            raise ValueError("filename must not be empty.")

        return v_clean

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: object) -> str:
        if not isinstance(v, str):
            raise ValueError("content must be a string.")

        v_clean = v.strip()

        if not v_clean:
            raise ValueError("content must not be empty.")

        return v_clean


class DbtModelBundle(BaseModel):
    """All dbt Core artifacts required to materialize the star schema."""

    staging_models: List[DbtSqlFile] = Field(
        ...,
        description="stg_*.sql staging views, one per raw source entity.",
    )

    mart_models: List[DbtSqlFile] = Field(
        ...,
        description="dim_*.sql and fct_*.sql mart models.",
    )

    schema_yml: str = Field(
        ...,
        description="Full contents of schema.yml declaring sources, models, columns, and tests.",
    )

    @field_validator("schema_yml")
    @classmethod
    def validate_schema_yml(cls, v: object) -> str:
        if not isinstance(v, str):
            raise ValueError("schema_yml must be a string.")

        v_clean = v.strip()

        if not v_clean:
            raise ValueError("schema_yml must not be empty.")

        return v_clean

    @model_validator(mode="after")
    def validate_bundles(self) -> "DbtModelBundle":
        if not self.staging_models:
            raise ValueError("dbt_models.staging_models must contain at least one staging model.")

        if not self.mart_models:
            raise ValueError("dbt_models.mart_models must contain at least one mart model.")

        return self


class StarSchemaResponse(BaseModel):
    """Root response model returned by the LLM and validated end-to-end."""

    fact_table: FactTable = Field(
        ...,
        description="The single generated fact table.",
    )

    dimensions: List[DimensionTable] = Field(
        ...,
        description="All generated dimension tables.",
    )

    duckdb_ddl: str = Field(
        ...,
        description=(
            "Concatenated, executable DuckDB DDL that defines the star schema's "
            "STRUCTURE ONLY: CREATE TABLE statements with PRIMARY KEY and "
            "REFERENCES (foreign key) constraints, dimensions declared before the "
            "fact table. Surrogate key columns are plain INTEGER PRIMARY KEY with "
            "NO default. Do NOT include CREATE SEQUENCE statements and do NOT use "
            "nextval() or any auto-increment default — surrogate key VALUES are "
            "assigned by the dbt mart models (row_number over a deterministic "
            "natural-key order), never by the DDL."
        ),
    )

    dbt_models: DbtModelBundle = Field(
        ...,
        description="Generated dbt Core staging and mart models plus schema.yml.",
    )

    @field_validator("duckdb_ddl")
    @classmethod
    def validate_duckdb_ddl(cls, v: object) -> str:
        if not isinstance(v, str):
            raise ValueError("duckdb_ddl must be a string.")

        v_clean = v.strip()

        if not v_clean:
            raise ValueError("duckdb_ddl must not be empty.")

        return v_clean

    @model_validator(mode="after")
    def validate_fk_targets_exist(self) -> "StarSchemaResponse":
        if not self.dimensions:
            raise ValueError("StarSchemaResponse must contain at least one dimension table.")

        dim_names = {d.table_name for d in self.dimensions}

        for col in self.fact_table.measures:
            if col.is_foreign_key and col.references_table not in dim_names:
                raise ValueError(
                    f"FactColumn '{col.name}' references_table='{col.references_table}' "
                    f"does not match any generated DimensionTable.table_name. "
                    f"Available dimensions: {sorted(dim_names)}"
                )

        return self