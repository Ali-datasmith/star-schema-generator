import pytest
from app.services.duckdb_runner import DuckDBSandboxRunner

def test_split_statements():
    runner = DuckDBSandboxRunner()
    ddl = "CREATE TABLE dim_1 (id INT);\nCREATE TABLE dim_2 (id INT);"
    stmts = runner.split_statements(ddl)
    assert len(stmts) == 2
    assert "dim_1" in stmts[0]

def test_execute_ddl_success():
    runner = DuckDBSandboxRunner()
    ddl = "CREATE TABLE dim_customer (customer_sk INTEGER PRIMARY KEY); CREATE TABLE fct_orders (order_sk INTEGER PRIMARY KEY, customer_sk INTEGER REFERENCES dim_customer(customer_sk));"
    report = runner.execute_ddl(ddl)
    assert report.success is True
    assert len(report.tables_created) == 2
    assert "dim_customer" in report.tables_created
    runner.close()

def test_execute_ddl_failure():
    runner = DuckDBSandboxRunner()
    # Reference a table that doesn't exist
    ddl = "CREATE TABLE fct_orders (order_sk INTEGER PRIMARY KEY REFERENCES dim_missing(customer_sk));"
    report = runner.execute_ddl(ddl)
    assert report.success is False
    assert report.failed_statement is not None
    runner.close()
