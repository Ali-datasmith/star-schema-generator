"""
main.py
Top-level Streamlit entrypoint. All backend mutation happens above the
st.tabs() call; tabs are pure renderers over st.session_state.

Execution lifecycle mirrors Project A's proven "single-path guard" pattern:
a button click only ever sets `research_active = True` and calls
`st.rerun()`; the actual network/DDL work happens on the *next* run, behind
`if st.session_state.research_active:`. This guarantees exactly one
in-flight pipeline run at a time even across Streamlit's rerun-on-widget-
interaction model, and keeps the spinner/status UI in a full, clean render
pass rather than partway through a synchronous button-click handler.
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

from app.services.duckdb_runner import DDLExecutionError, DuckDBSandboxRunner
from app.services.llm_engine import (
    DEFAULT_MODELS,
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
# Session-state initialization — must happen before any widget renders.
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

# Model chain actually used for generation. Resolvable via st.secrets /
# env so the displayed model and the executed model can never drift again.
try:
    _configured_models = st.secrets.get("GEMINI_MODELS", "")
except (KeyError, AttributeError):
    _configured_models = ""
_configured_models = _configured_models or os.environ.get("GEMINI_MODELS", "")
MODEL_CHAIN = (
    [m.strip() for m in _configured_models.split(",") if m.strip()]
    if _configured_models
    else DEFAULT_MODELS
)

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

        # Model chain display now reflects the chain actually executed —
        # no more drift between the label and MODELS in llm_engine.py.
        st.info(f"⚡ Model chain: {' → '.join(MODEL_CHAIN)}")

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
            disabled=st.session_state.research_active,
            use_container_width=True,
        )
    return generate_clicked


# ---------------------------------------------------------------------------
# 1. SINGLE-PATH GUARD (Project A pattern)
#    A button click below only flips research_active + reruns. All actual
#    network/DDL work happens here, on the *next* run, so there is always
#    exactly one in-flight pipeline and the UI never renders mid-mutation.
# ---------------------------------------------------------------------------
if st.session_state.research_active:
    with st.status("Running Star-Schema pipeline...", expanded=True) as status:
        st.session_state.pipeline_error = None
        try:
            # ---- Validate JSON input ----
            st.session_state.pipeline_stage = "validating_json"
            st.write("Validating JSON payload...")
            try:
                json.loads(st.session_state.raw_json_input)
                console.log_json_validation(0.01, True, None)
            except json.JSONDecodeError as exc:
                console.log_json_validation(0.01, False, str(exc))
                raise SchemaGenerationError(f"Invalid JSON payload: {exc}") from exc

            # ---- Call LLM ----
            st.session_state.pipeline_stage = "calling_llm"
            st.write(f"Calling Gemini ({' → '.join(MODEL_CHAIN)})...")
            generator = StarSchemaGenerator(api_key=st.session_state.api_key, models=MODEL_CHAIN)
            call_result = generator.generate(st.session_state.raw_json_input)
            st.session_state.llm_call_result = call_result
            console.log_llm_call(call_result)

            # ---- Execute DDL ----
            st.session_state.pipeline_stage = "executing_ddl"
            st.write("Validating DDL against in-memory DuckDB sandbox...")
            runner = DuckDBSandboxRunner()
            try:
                report = runner.execute_ddl(call_result.response.duckdb_ddl)
                st.session_state.ddl_execution_report = report
                console.log_ddl_execution(report)
                if not report.success:
                    raise DDLExecutionError(
                        report.failed_statement or "", Exception(report.error_message)
                    )
            finally:
                runner.close()

            # ---- Success ----
            st.session_state.schema_result = call_result.response
            st.session_state.pipeline_stage = "complete"
            st.session_state.last_run_timestamp = dt.datetime.now()
            st.session_state.pipeline_error = None
            st.session_state.research_active = False
            status.update(label="Star-Schema generated!", state="complete", expanded=False)
            st.rerun()

        except Exception as e:
            err_str = str(e)
            err_type = type(e).__name__

            # Categorized, human-readable error mapping (same taxonomy as
            # the working reference project) instead of a raw traceback.
            if isinstance(e, SchemaValidationError) or "validation" in err_str.lower() or "pydantic" in err_str.lower():
                msg = f"Schema Validation Failure: AI returned malformed JSON. {err_str}"
            elif isinstance(e, DDLExecutionError):
                msg = f"DuckDB DDL Execution Failure: {err_str}"
            elif "quota" in err_str.lower() or "429" in err_str or "rate limit" in err_str.lower():
                msg = f"API Quota / Rate Limit Exhaustion: {err_str}"
            elif "503" in err_str or "overloaded" in err_str.lower() or "unavailable" in err_str.lower():
                msg = f"Model Server Overloaded (503): {err_str}"
            elif "404" in err_str or "not_found" in err_str.lower():
                msg = f"Model Not Found (404) — check GEMINI_MODELS: {err_str}"
            elif "timeout" in err_str.lower() or "deadline" in err_str.lower():
                msg = f"Network Timeout / Server Unavailable: {err_str}"
            elif "api_key" in err_str.lower() or "auth" in err_str.lower() or "401" in err_str or "403" in err_str:
                msg = f"Authentication Error: Invalid or missing GOOGLE_API_KEY. {err_str}"
            else:
                msg = f"Unexpected System Error ({err_type}): {err_str}"

            st.session_state.pipeline_error = msg
            st.session_state.pipeline_stage = "error"
            st.session_state.research_active = False
            status.update(label="Pipeline Failed!", state="error", expanded=True)
            st.rerun()

# ---------------------------------------------------------------------------
# 2. UI Rendering (purely state-driven)
# ---------------------------------------------------------------------------
generate_clicked = render_sidebar()

if generate_clicked and not st.session_state.research_active:
    st.session_state.pipeline_error = None
    st.session_state.research_active = True
    st.rerun()

st.markdown(
    """
    <div class="glass-hero">
        <h1>Data Warehouse Star-Schema Generator</h1>
        <p>Raw JSON &rarr; Pydantic-validated dimensional model &rarr; DuckDB DDL &rarr; dbt Core</p>
        <p style="margin-top: 0.5rem; font-size: 0.85rem; color: #A9C2C0;">
            Built with Python 3.10+, Pydantic v2, Gemini, DuckDB, and Streamlit
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

if st.session_state.pipeline_error:
    st.error(st.session_state.pipeline_error)

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