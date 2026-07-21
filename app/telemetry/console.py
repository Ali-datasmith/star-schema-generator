"""
console.py
Rich-console telemetry for backend execution stages: JSON validation timing,
LLM prompt latency/token usage, and DuckDB DDL execution checks. Every event
is also appended to st.session_state.telemetry_log for in-app display on
Tab 4, so the console output and the UI stay in lock-step.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List

import streamlit as st
from rich.console import Console
from rich.table import Table

from app.services.duckdb_runner import DDLExecutionReport
from app.services.llm_engine import LLMCallResult


class TelemetryConsole:
    """Wraps rich.console.Console and mirrors events into Streamlit session state."""

    def __init__(self) -> None:
        self._console = Console()
        if "telemetry_log" not in st.session_state:
            st.session_state.telemetry_log = []

    def _record(self, stage: str, payload: Dict[str, Any]) -> None:
        entry = {
            "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
            "stage": stage,
            **payload,
        }
        st.session_state.telemetry_log.append(entry)

    def log_json_validation(self, duration_seconds: float, is_valid: bool, error: str | None = None) -> None:
        table = Table(title="JSON Payload Validation", show_header=True, header_style="bold #3C9992")
        table.add_column("Metric")
        table.add_column("Value")
        table.add_row("Valid", str(is_valid))
        table.add_row("Duration (s)", f"{duration_seconds:.4f}")
        if error:
            table.add_row("Error", error)
        self._console.print(table)
        self._record(
            "json_validation",
            {"duration_seconds": duration_seconds, "is_valid": is_valid, "error": error},
        )

    def log_llm_call(self, result: LLMCallResult) -> None:
        table = Table(title="LLM Structured Generation", show_header=True, header_style="bold #3C9992")
        table.add_column("Metric")
        table.add_column("Value")
        table.add_row("Latency (s)", f"{result.latency_seconds:.3f}")
        table.add_row("Prompt tokens", str(result.prompt_token_count))
        table.add_row("Candidate tokens", str(result.candidates_token_count))
        table.add_row("Fact table", result.response.fact_table.table_name)
        table.add_row("Dimension count", str(len(result.response.dimensions)))
        self._console.print(table)
        self._record(
            "llm_call",
            {
                "latency_seconds": result.latency_seconds,
                "prompt_token_count": result.prompt_token_count,
                "candidates_token_count": result.candidates_token_count,
                "fact_table": result.response.fact_table.table_name,
                "dimension_count": len(result.response.dimensions),
            },
        )

    def log_ddl_execution(self, report: DDLExecutionReport) -> None:
        table = Table(title="DuckDB DDL Execution", show_header=True, header_style="bold #3C9992")
        table.add_column("Metric")
        table.add_column("Value")
        table.add_row("Success", str(report.success))
        table.add_row("Total statements", str(report.total_statements))
        table.add_row("Executed statements", str(len(report.executed_statements)))
        table.add_row("Tables created", ", ".join(report.tables_created) or "-")
        if not report.success:
            table.add_row("Failed statement", report.failed_statement or "-")
            table.add_row("Error", report.error_message or "-")
        self._console.print(table)
        self._record(
            "ddl_execution",
            {
                "success": report.success,
                "total_statements": report.total_statements,
                "executed_statements": len(report.executed_statements),
                "tables_created": report.tables_created,
                "failed_statement": report.failed_statement,
                "error_message": report.error_message,
            },
        )

    def get_log(self) -> List[Dict[str, Any]]:
        return st.session_state.telemetry_log
