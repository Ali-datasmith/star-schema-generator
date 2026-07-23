"""
main.py

Top-level Streamlit entrypoint.

This refactored version applies Project A's working Streamlit lifecycle:

1. Initialize session state early.
2. Sidebar widgets only write intended state.
3. The Generate button sets research_active=True and reruns.
4. A single execution guard owns the backend pipeline.
5. The pipeline always resets research_active=False.
6. The app reruns into a consistent UI state.
7. Tabs render only from persisted session state.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# sys.path bootstrap — MUST execute before any `from app.*` import.
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
_ROOT_STR = str(ROOT_DIR)

if _ROOT_STR not in sys.path:
    sys.path.insert(0, _ROOT_STR)

os.environ.setdefault("PYTHONPATH", _ROOT_STR)

import datetime as dt
import json
import time

import streamlit as st

from app.schemas import StarSchemaResponse
from app.services.duckdb_runner import DDLExecutionError, DuckDBSandboxRunner
from app.services.llm_engine import (
    SchemaGenerationError,
    SchemaValidationError,
    StarSchemaGenerator,
    classify_error,
)
from app.telemetry.console import TelemetryConsole
from app.ui.theme import inject_glassmorphism_css
from app.ui.tabs import (
    render_ddl_sandbox_tab,
    render_debug_tab,
    render_dbt_tab,
    render_erd_tab,
)

st.set_page_config(
    page_title="Data Warehouse Star-Schema Generator",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_glassmorphism_css()

# ---------------------------------------------------------------------------
# Session-state initialization
# ---------------------------------------------------------------------------
DEFAULTS = {
    "research_active": False,
    "pipeline_stage": "idle",
    "raw_json_input": "",
    "json_input_widget": "",
    "api_key": "",
    "schema_result": None,
    "llm_call_result": None,
    "ddl_execution_report": None,
    "pipeline_error": None,
    "telemetry_log": [],
    "last_run_timestamp": None,
    "last_sample": "-- none --",
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value

console = TelemetryConsole()

# ---------------------------------------------------------------------------
# Sample payloads
# ---------------------------------------------------------------------------
SAMPLE_STRIPE_PAYLOAD = """{
  "id": "evt_1OqZxR2eZvKYlo2C0JqZvK",
  "object": "event",
  "api_version": "2020-08-27",
  "created": 1699999999,
  "data": {
    "object": {
      "id": "ch_3OqZxQ2eZvKYlo2C0JqZx",
      "object": "charge",
      "amount": 2000,
      "amount_captured": 2000,
      "amount_refunded": 0,
      "currency": "usd",
      "customer": "cus_NffrFeUfNV2Hib",
      "description": "Order #12345",
      "paid": true,
      "status": "succeeded",
      "payment_method_details": {
        "card": {"brand": "visa", "last4": "4242", "exp_month": 12, "exp_year": 2025},
        "type": "card"
      },
      "billing_details": {
        "name": "John Doe",
        "email": "customer@example.com"
      }
    }
  },
  "livemode": false,
  "pending_webhooks": 1,
  "type": "charge.succeeded"
}"""

SAMPLE_SHOPIFY_PAYLOAD = """{
  "id": 450789469,
  "name": "#1005",
  "email": "customer@example.com",
  "currency": "USD",
  "financial_status": "paid",
  "total_price": "214.99",
  "subtotal_price": "199.99",
  "total_tax": "15.00",
  "created_at": "2024-01-15T10:30:00-05:00",
  "customer": {
    "id": 207119551,
    "email": "customer@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "orders_count": 5,
    "total_spent": "999.95"
  },
  "line_items": [
    {
      "id": 518995019,
      "title": "Premium Widget",
      "quantity": 1,
      "price": "199.99",
      "sku": "WIDGET-PRO-001",
      "product_id": 632910392
    }
  ]
}"""

SAMPLE_OPTIONS = [
    "-- none --",
    "Stripe: charge.succeeded",
    "Shopify: order/create",
]

SAMPLE_PAYLOADS = {
    "Stripe: charge.succeeded": SAMPLE_STRIPE_PAYLOAD,
    "Shopify: order/create": SAMPLE_SHOPIFY_PAYLOAD,
}


def render_sidebar() -> None:
    """
    Renders sidebar controls.

    The Generate button does not execute the pipeline directly.
    It only sets execution state and triggers a rerun.
    """

    with st.sidebar:
        st.markdown("### Configuration")

        # Defensive secret access.
        try:
            secret_key: str = st.secrets.get("GOOGLE_API_KEY", "") or ""
        except Exception:
            secret_key = ""

        # Initialize the API-key widget once.
        if "api_key_widget" not in st.session_state:
            st.session_state.api_key_widget = (
                st.session_state.get("api_key", "") or secret_key
            )

        st.session_state.api_key = st.text_input(
            "Google AI Studio API Key",
            key="api_key_widget",
            type="password",
            help=(
                "Optional. If blank, the app falls back to GOOGLE_API_KEY "
                "from Streamlit secrets or environment variables."
            ),
        )

        st.info("⚡ Model Engine: Gemini 3.5 Flash (structured JSON, single-call guard)")

        sample = st.selectbox(
            "Sample payload",
            options=SAMPLE_OPTIONS,
            key="sample_selector",
        )

        # Only overwrite the text area when the sample selection actually changes.
        if sample != st.session_state.last_sample:
            st.session_state.last_sample = sample
            payload = SAMPLE_PAYLOADS.get(sample, "")

            if payload:
                st.session_state.raw_json_input = payload
                st.session_state.json_input_widget = payload

        st.text_area(
            "Raw JSON payload",
            value=st.session_state.raw_json_input,
            height=280,
            key="json_input_widget",
        )

        st.caption(
            "The payload is validated locally, sent to Gemini as structured JSON, "
            "then executed inside an in-memory DuckDB sandbox."
        )

        generate_disabled = st.session_state.research_active

        if st.button(
            "Generate Star-Schema",
            type="primary",
            disabled=generate_disabled,
            use_container_width=True,
        ):
            current_input = str(st.session_state.get("json_input_widget", "")).strip()

            if not current_input:
                st.session_state.pipeline_error = (
                    "Please provide a raw JSON payload before generating."
                )
                st.rerun()

            # Persist canonical execution input.
            st.session_state.raw_json_input = current_input

            # Clear previous execution artifacts.
            st.session_state.pipeline_error = None
            st.session_state.schema_result = None
            st.session_state.llm_call_result = None
            st.session_state.ddl_execution_report = None
            st.session_state.pipeline_stage = "queued"

            # Single-path execution ownership.
            st.session_state.research_active = True
            st.rerun()


def run_pipeline() -> None:
    """
    Single-path orchestration:

    JSON validation -> Gemini structured generation -> Pydantic validation -> DuckDB DDL execution.

    This function always resets research_active before returning.
    """

    st.session_state.pipeline_error = None

    status = st.status("Generating star schema", expanded=True)

    try:
        # ---- Validate JSON input ----
        st.session_state.pipeline_stage = "validating_json"
        status.write("Validating JSON payload...")

        validation_start = time.perf_counter()

        try:
            json.loads(st.session_state.raw_json_input)
            console.log_json_validation(
                time.perf_counter() - validation_start,
                True,
                None,
            )
        except json.JSONDecodeError as exc:
            console.log_json_validation(
                time.perf_counter() - validation_start,
                False,
                str(exc),
            )
            raise SchemaGenerationError(f"Invalid JSON payload: {exc}") from exc

        # ---- Call LLM ----
        st.session_state.pipeline_stage = "calling_llm"
        status.write("Calling Gemini structured output...")

        generator = StarSchemaGenerator(api_key=st.session_state.api_key)
        call_result = generator.generate(st.session_state.raw_json_input)

        st.session_state.llm_call_result = call_result
        console.log_llm_call(call_result)

        # ---- Execute DDL ----
        st.session_state.pipeline_stage = "executing_ddl"
        status.write("Validating DDL against in-memory DuckDB sandbox...")

        runner = DuckDBSandboxRunner()

        try:
            report = runner.execute_ddl(call_result.response.duckdb_ddl)
            st.session_state.ddl_execution_report = report
            console.log_ddl_execution(report)

            if not report.success:
                raise DDLExecutionError(
                    report.failed_statement or "",
                    Exception(report.error_message or "DDL execution failed."),
                )
        finally:
            runner.close()

        # ---- Success ----
        st.session_state.schema_result = call_result.response
        st.session_state.pipeline_stage = "complete"
        st.session_state.last_run_timestamp = dt.datetime.now()

        status.update(
            label="Star schema generated!",
            state="complete",
            expanded=False,
        )

    except SchemaGenerationError as exc:
        st.session_state.pipeline_error = str(exc)
        st.session_state.pipeline_stage = "error"
        status.update(
            label="Generation failed",
            state="error",
            expanded=True,
        )

    except SchemaValidationError as exc:
        st.session_state.pipeline_error = str(exc)
        st.session_state.pipeline_stage = "error"
        status.update(
            label="Schema validation failed",
            state="error",
            expanded=True,
        )

    except DDLExecutionError as exc:
        st.session_state.pipeline_error = str(exc)
        st.session_state.pipeline_stage = "error"
        status.update(
            label="DuckDB DDL execution failed",
            state="error",
            expanded=True,
        )

    except Exception as exc:
        st.session_state.pipeline_error = classify_error(exc)
        st.session_state.pipeline_stage = "error"
        status.update(
            label="Unexpected failure",
            state="error",
            expanded=True,
        )

    finally:
        st.session_state.research_active = False


# ---------------------------------------------------------------------------
# Sidebar rendering
# ---------------------------------------------------------------------------
render_sidebar()

# ---------------------------------------------------------------------------
# SINGLE-PATH GUARD
#
# Execution happens only when research_active is True.
# After execution, the app reruns into a clean state.
# ---------------------------------------------------------------------------
if st.session_state.research_active:
    run_pipeline()
    st.rerun()

# ---------------------------------------------------------------------------
# Hero header
# ---------------------------------------------------------------------------
st.markdown(
    """
    <div class="glass-hero">
        <h1>Data Warehouse Star-Schema Generator</h1>
        <p>Raw JSON &rarr; Pydantic-validated dimensional model &rarr; DuckDB DDL &rarr; dbt Core</p>
        <p style="margin-top: 0.5rem; font-size: 0.85rem; color: #A9C2C0;">
            Built with Python 3.10+, Pydantic v2, Gemini 3.5 Flash, DuckDB, and Streamlit
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

if st.session_state.pipeline_error:
    st.error(st.session_state.pipeline_error)

# ---------------------------------------------------------------------------
# Tabs render read-only from session_state
# ---------------------------------------------------------------------------
tab1, tab2, tab3, tab4 = st.tabs(
    [
        "Visual ERD",
        "DuckDB DDL Sandbox",
        "dbt Core Files",
        "Pydantic Payload & Telemetry",
    ]
)

with tab1:
    render_erd_tab(st.session_state.schema_result)

with tab2:
    render_ddl_sandbox_tab(
        st.session_state.schema_result,
        st.session_state.ddl_execution_report,
    )

with tab3:
    render_dbt_tab(st.session_state.schema_result)

with tab4:
    render_debug_tab(
        st.session_state.schema_result,
        st.session_state.llm_call_result,
        st.session_state.telemetry_log,
    )