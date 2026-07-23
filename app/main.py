"""
main.py
Top-level Streamlit entrypoint. All backend mutation happens above the
st.tabs() call; tabs are pure renderers over st.session_state.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# sys.path bootstrap — MUST execute before any `from app.*` import.
#
# Streamlit Community Cloud invokes `streamlit run app/main.py` from the
# repository root. CPython then prepends the script's *own* directory
# (`<repo>/app`) to sys.path[0], not the repository root. Without this
# injection, `from app.schemas import ...` resolves to `<repo>/app/app/...`
# and raises ModuleNotFoundError.
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
_ROOT_STR = str(ROOT_DIR)
if _ROOT_STR not in sys.path:
    sys.path.insert(0, _ROOT_STR)
os.environ.setdefault("PYTHONPATH", _ROOT_STR)

import datetime as dt
import json

import streamlit as st

from app.schemas import StarSchemaResponse
from app.services.duckdb_runner import DDLExecutionError, DuckDBSandboxRunner
from app.services.llm_engine import (
    SchemaGenerationError,
    SchemaValidationError,
    StarSchemaGenerator,
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
    "api_key": "",
    "schema_result": None,
    "llm_call_result": None,
    "ddl_execution_report": None,
    "pipeline_error": None,
    "telemetry_log": [],
    "last_run_timestamp": None,
}
for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value

console = TelemetryConsole()

# Sample payloads
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


def render_sidebar() -> bool:
    """Renders sidebar controls. Returns True if the generate button was clicked."""
    with st.sidebar:
        st.markdown("### Configuration")

        # Defensive secret access
        try:
            secret_key: str = st.secrets.get("GOOGLE_API_KEY", "") or ""
        except (KeyError, AttributeError):
            secret_key = ""

        st.session_state.api_key = st.text_input(
            "Google AI Studio API Key",
            value=st.session_state.api_key or secret_key,
            type="password",
            help="Falls back to st.secrets['GOOGLE_API_KEY'] if left blank.",
        )

        # Static Model Engine Status Display (Replaces dropdown selector)
        st.info("⚡ Model Engine: Gemini 3.5 Flash (Auto-fallback: 2.5 Flash)")

        sample = st.selectbox(
            "Sample payload",
            options=["-- none --", "Stripe: charge.succeeded", "Shopify: order/create"],
        )
        if sample == "Stripe: charge.succeeded":
            st.session_state.raw_json_input = SAMPLE_STRIPE_PAYLOAD
        elif sample == "Shopify: order/create":
            st.session_state.raw_json_input = SAMPLE_SHOPIFY_PAYLOAD

        st.session_state.raw_json_input = st.text_area(
            "Raw JSON payload",
            value=st.session_state.raw_json_input,
            height=280,
        )

        generate_clicked = st.button(
            "Generate Star-Schema",
            type="primary",
            disabled=st.session_state.pipeline_stage
            in {"validating_json", "calling_llm", "executing_ddl"},
            use_container_width=True,
        )
    return generate_clicked


def run_pipeline() -> None:
    """Single-path orchestration: LLM call -> validation -> DuckDB execution."""
    st.session_state.pipeline_error = None
    st.session_state.pipeline_stage = "calling_llm"

    try:
        # ---- Validate JSON input ----
        st.session_state.pipeline_stage = "validating_json"
        with st.spinner("Validating JSON payload..."):
            try:
                json.loads(st.session_state.raw_json_input)
                console.log_json_validation(0.01, True, None)
            except json.JSONDecodeError as exc:
                console.log_json_validation(0.01, False, str(exc))
                raise SchemaGenerationError(f"Invalid JSON payload: {exc}") from exc

        # ---- Call LLM ----
        st.session_state.pipeline_stage = "calling_llm"
        with st.spinner("Calling Gemini 3.5 Flash for schema design..."):
            generator = StarSchemaGenerator(api_key=st.session_state.api_key)
            call_result = generator.generate(st.session_state.raw_json_input)
            st.session_state.llm_call_result = call_result
            console.log_llm_call(call_result)

        # ---- Execute DDL ----
        st.session_state.pipeline_stage = "executing_ddl"
        with st.spinner("Validating DDL against in-memory DuckDB sandbox..."):
            runner = DuckDBSandboxRunner()
            try:
                report = runner.execute_ddl(call_result.response.duckdb_ddl)
                st.session_state.ddl_execution_report = report
                console.log_ddl_execution(report)

                if not report.success:
                    raise DDLExecutionError(
                        report.failed_statement or "",
                        Exception(report.error_message),
                    )
            finally:
                runner.close()

        # ---- Success ----
        st.session_state.schema_result = call_result.response
        st.session_state.pipeline_stage = "complete"
        st.session_state.last_run_timestamp = dt.datetime.now()

    except SchemaGenerationError as exc:
        st.session_state.pipeline_error = f"LLM generation failed: {exc}"
        st.session_state.pipeline_stage = "error"
    except SchemaValidationError as exc:
        st.session_state.pipeline_error = f"Schema validation failed: {exc}"
        st.session_state.pipeline_stage = "error"
    except DDLExecutionError as exc:
        st.session_state.pipeline_error = f"DuckDB DDL execution failed: {exc}"
        st.session_state.pipeline_stage = "error"
    finally:
        st.session_state.research_active = False


# ---- Orchestration: runs BEFORE any tab is rendered ----
generate_clicked = render_sidebar()

if generate_clicked and not st.session_state.research_active:
    st.session_state.research_active = True
    run_pipeline()

# ---- Hero header ----
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

# ---- Tabs render read-only from session_state ----
tab1, tab2, tab3, tab4 = st.tabs(
    ["Visual ERD", "DuckDB DDL Sandbox", "dbt Core Files", "Pydantic Payload & Telemetry"]
)

with tab1:
    render_erd_tab(st.session_state.schema_result)

with tab2:
    render_ddl_sandbox_tab(st.session_state.schema_result, st.session_state.ddl_execution_report)

with tab3:
    render_dbt_tab(st.session_state.schema_result)

with tab4:
    render_debug_tab(
        st.session_state.schema_result,
        st.session_state.llm_call_result,
        st.session_state.telemetry_log,
    )
