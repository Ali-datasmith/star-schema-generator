import pytest
from app.schemas import (
    _normalize_duckdb_type,
    _validate_identifier,
    _validate_table_name,
    DimensionTable,
    DimensionColumn,
    FactTable,
    FactColumn,
    StarSchemaResponse,
    DuckDBDataType,
    MeasureType,
)
from pydantic import ValidationError

def test_normalize_duckdb_type():
    assert _normalize_duckdb_type("VARCHAR") == "VARCHAR"
    assert _normalize_duckdb_type("TEXT") == DuckDBDataType.VARCHAR.value
    assert _normalize_duckdb_type("INT") == DuckDBDataType.INTEGER.value
    assert _normalize_duckdb_type("DECIMAL(18,2)") == DuckDBDataType.DECIMAL.value
    assert _normalize_duckdb_type("DATETIME") == DuckDBDataType.TIMESTAMP.value
    assert _normalize_duckdb_type("") == ""

def test_validate_identifier():
    assert _validate_identifier("valid_name", "col") == "valid_name"
    with pytest.raises(ValueError, match="must not start with a digit"):
        _validate_identifier("1invalid", "col")
    with pytest.raises(ValueError, match="must be lower_snake_case"):
        _validate_identifier("Invalid_Name", "col")
    with pytest.raises(ValueError, match="must not be empty"):
        _validate_identifier("", "col")

def test_validate_table_name():
    assert _validate_table_name("dim_customer", "dim_") == "dim_customer"
    with pytest.raises(ValueError, match="must be prefixed"):
        _validate_table_name("fct_customer", "dim_")
    with pytest.raises(ValueError, match="must contain a name"):
        _validate_table_name("dim_", "dim_")

def test_dimension_table_validation():
    sk_col = DimensionColumn(name="customer_sk", data_type="INTEGER", is_surrogate_key=True, is_business_key=False, description="SK")
    biz_col = DimensionColumn(name="customer_id", data_type="VARCHAR", is_surrogate_key=False, is_business_key=True, description="Biz")
    
    # Valid
    dim = DimensionTable(table_name="dim_customer", surrogate_key_name="customer_sk", attributes=[sk_col, biz_col])
    assert dim.table_name == "dim_customer"

    # Invalid: no surrogate key
    with pytest.raises(ValidationError):
        DimensionTable(table_name="dim_customer", surrogate_key_name="customer_sk", attributes=[biz_col])

    # Invalid: two surrogate keys
    sk_col2 = DimensionColumn(name="other_sk", data_type="INTEGER", is_surrogate_key=True, is_business_key=False, description="Other SK")
    with pytest.raises(ValidationError):
        DimensionTable(table_name="dim_customer", surrogate_key_name="customer_sk", attributes=[sk_col, sk_col2, biz_col])

def test_fact_table_validation():
    fk_col = FactColumn(name="customer_sk", data_type="INTEGER", is_foreign_key=True, references_table="dim_customer", measure_type=MeasureType.NONE)
    measure_col = FactColumn(name="amount", data_type="DECIMAL", measure_type=MeasureType.ADDITIVE)
    
    # Valid
    fct = FactTable(
        table_name="fct_orders", primary_key="order_sk", foreign_keys=["customer_sk"],
        measures=[fk_col, measure_col], ddl_sql="CREATE TABLE fct_orders (order_sk INTEGER);"
    )
    assert fct.table_name == "fct_orders"

    # Invalid: FK declared in foreign_keys list but missing in measures
    with pytest.raises(ValidationError):
        FactTable(
            table_name="fct_orders", primary_key="order_sk", 
            foreign_keys=["customer_sk", "product_sk"], # product_sk missing
            measures=[fk_col, measure_col], ddl_sql="CREATE TABLE fct_orders (order_sk INTEGER);"
        )

def test_star_schema_response_fk_targets():
    # Test that fact table references must exist in generated dimensions
    sk_col = DimensionColumn(name="customer_sk", data_type="INTEGER", is_surrogate_key=True, is_business_key=False, description="SK")
    dim = DimensionTable(table_name="dim_customer", surrogate_key_name="customer_sk", attributes=[sk_col])
    
    fk_col = FactColumn(name="customer_sk", data_type="INTEGER", is_foreign_key=True, references_table="dim_missing", measure_type=MeasureType.NONE)
    fct = FactTable(
        table_name="fct_orders", primary_key="order_sk", foreign_keys=["customer_sk"], 
        measures=[fk_col], ddl_sql="CREATE TABLE fct_orders (order_sk INTEGER);"
    )
    
    with pytest.raises(ValidationError, match="does not match any generated DimensionTable"):
        StarSchemaResponse(
            fact_table=fct, dimensions=[dim], duckdb_ddl="CREATE TABLE fct_orders();", 
            dbt_models={
                "staging_models": [{"filename": "stg.sql", "model_type": "staging", "content": "select 1"}],
                "mart_models": [{"filename": "mart.sql", "model_type": "dimension", "content": "select 1"}],
                "schema_yml": "version: 2"
            }
        )
