"""
duckdb_runner.py
Sandbox executor that validates LLM-generated DuckDB DDL against a real, in-memory
DuckDB connection before it is ever presented to the user as "trusted."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import duckdb
import pandas as pd


class DDLExecutionError(Exception):
    """Raised when one or more DDL statements fail to execute."""

    def __init__(self, statement: str, original_error: Exception) -> None:
        self.statement = statement
        self.original_error = original_error
        super().__init__(
            f"Failed executing statement:\n{statement}\n\nDuckDB error: {original_error}"
        )


@dataclass
class DDLExecutionReport:
    total_statements: int
    executed_statements: List[str] = field(default_factory=list)
    failed_statement: Optional[str] = None
    error_message: Optional[str] = None
    success: bool = True
    tables_created: List[str] = field(default_factory=list)


class DuckDBSandboxRunner:
    """Wraps an in-memory DuckDB connection for syntax and execution validation."""

    def __init__(self) -> None:
        self._conn = duckdb.connect(database=":memory:")

    def split_statements(self, ddl_script: str) -> List[str]:
        statements = [s.strip() for s in ddl_script.split(";")]
        return [s for s in statements if s]

    def execute_ddl(self, ddl_script: str) -> DDLExecutionReport:
        statements = self.split_statements(ddl_script)
        report = DDLExecutionReport(total_statements=len(statements))

        for stmt in statements:
            try:
                self._conn.execute(stmt)
                report.executed_statements.append(stmt)
            except duckdb.Error as exc:
                report.success = False
                report.failed_statement = stmt
                report.error_message = str(exc)
                return report

        tables_df = self._conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchdf()
        report.tables_created = tables_df["table_name"].tolist()
        return report

    def ingest_raw_json(self, json_path: str, landing_table_name: str = "raw_landing") -> None:
        """Land raw JSON into a staging table using DuckDB's native JSON reader."""
        self._conn.execute(
            f"CREATE OR REPLACE TABLE {landing_table_name} AS "
            f"SELECT * FROM read_json_auto('{json_path}', maximum_object_size=10485760)"
        )

    def preview_table(self, table_name: str, limit: int = 25) -> pd.DataFrame:
        return self._conn.execute(f"SELECT * FROM {table_name} LIMIT {limit}").fetchdf()

    def close(self) -> None:
        self._conn.close()
