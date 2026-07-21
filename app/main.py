"""
main.py
Top-level Streamlit entrypoint. All backend mutation happens above the
st.tabs() call; tabs are pure renderers over st.session_state.
"""

from __future__ import annotations

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
console = TelemetryConsole()

DEFAULTS = {
    "research_active": False,
    "pipeline_stage": "idle",
    "raw_json_input": "",
    "api_key": "",
    "selected_model": "gemini-2.5-flash",
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
      "application": null,
      "application_fee": null,
      "application_fee_amount": null,
      "balance_transaction": "txn_3OqZxQ2eZvKYlo2C0JqZy",
      "billing_details": {
        "address": {
          "city": "San Francisco",
          "country": "US",
          "line1": "123 Market St",
          "line2": null,
          "postal_code": "94103",
          "state": "CA"
        },
        "email": "customer@example.com",
        "name": "John Doe",
        "phone": null
      },
      "calculated_statement_descriptor": "ACME CORP",
      "captured": true,
      "created": 1699999999,
      "currency": "usd",
      "customer": "cus_NffrFeUfNV2Hib",
      "description": "Order #12345",
      "destination": null,
      "dispute": null,
      "disputed": false,
      "failure_balance_transaction": null,
      "failure_code": null,
      "failure_message": null,
      "fraud_details": {},
      "invoice": null,
      "livemode": false,
      "metadata": {
        "order_id": "ord_12345",
        "product_id": "prod_ABC123"
      },
      "on_behalf_of": null,
      "order": null,
      "outcome": {
        "network_status": "approved_by_network",
        "network_risk_level": "normal",
        "risk_level": "normal",
        "risk_score": 25,
        "seller_message": "Payment complete.",
        "type": "authorized"
      },
      "paid": true,
      "payment_intent": "pi_3OqZxQ2eZvKYlo2C0JqZw",
      "payment_method": "pm_1OqZxQ2eZvKYlo2C0JqZv",
      "payment_method_details": {
        "card": {
          "brand": "visa",
          "checks": {
            "address_line1_check": "pass",
            "address_postal_code_check": "pass",
            "cvc_check": "pass"
          },
          "country": "US",
          "exp_month": 12,
          "exp_year": 2025,
          "fingerprint": "mToIsGcC05o6P8tg",
          "funding": "credit",
          "installments": null,
          "last4": "4242",
          "mandate": null,
          "network": "visa",
          "three_d_secure": null,
          "wallet": null
        },
        "type": "card"
      },
      "receipt_email": null,
      "receipt_number": null,
      "receipt_url": "https://pay.stripe.com/receipts/acct_1032D82eZvKYlo2C/ch_3OqZxQ2eZvKYlo2C0JqZx/rcpt_NffrFeUfNV2Hib",
      "refunded": false,
      "refunds": {
        "object": "list",
        "data": [],
        "has_more": false,
        "url": "/v1/charges/ch_3OqZxQ2eZvKYlo2C0JqZx/refunds"
      },
      "review": null,
      "shipping": null,
      "source": null,
      "source_transfer": null,
      "statement_descriptor": null,
      "statement_descriptor_suffix": null,
      "status": "succeeded",
      "transfer_data": null,
      "transfer_group": null
    }
  },
  "livemode": false,
  "pending_webhooks": 1,
  "request": {
    "id": "req_NffrFeUfNV2Hib",
    "idempotency_key": "abc123"
  },
  "type": "charge.succeeded"
}"""

SAMPLE_SHOPIFY_PAYLOAD = """{
  "id": 450789469,
  "admin_graphql_api_id": "gid://shopify/Order/450789469",
  "app_id": null,
  "browser_ip": "192.168.1.1",
  "buyer_accepts_marketing": false,
  "cancel_reason": null,
  "cancelled_at": null,
  "cart_token": "68778783ad298f1c80c3bafcddeea02f",
  "checkout_id": 901414060,
  "checkout_token": "bd5a8aa19798f8a5c9e7e9f7e9e7e9e7",
  "client_details": {
    "accept_language": "en-US,en;q=0.9",
    "browser_height": 1080,
    "browser_ip": "192.168.1.1",
    "browser_width": 1920,
    "session_hash": "abc123",
    "user_agent": "Mozilla/5.0"
  },
  "closed_at": null,
  "confirmed": true,
  "contact_email": "customer@example.com",
  "created_at": "2024-01-15T10:30:00-05:00",
  "currency": "USD",
  "current_subtotal_price": "199.99",
  "current_total_discounts": "0.00",
  "current_total_price": "214.99",
  "current_total_tax": "15.00",
  "customer": {
    "id": 207119551,
    "email": "customer@example.com",
    "accepts_marketing": false,
    "created_at": "2024-01-10T09:00:00-05:00",
    "updated_at": "2024-01-15T10:30:00-05:00",
    "first_name": "John",
    "last_name": "Doe",
    "orders_count": 5,
    "state": "enabled",
    "total_spent": "999.95",
    "last_order_id": 450789469,
    "note": "VIP customer",
    "verified_email": true,
    "multipass_identifier": null,
    "tax_exempt": false,
    "phone": "+1234567890",
    "tags": "vip, loyal",
    "last_order_name": "#1005",
    "currency": "USD",
    "admin_graphql_api_id": "gid://shopify/Customer/207119551",
    "default_address": {
      "id": 247680492,
      "customer_id": 207119551,
      "first_name": "John",
      "last_name": "Doe",
      "company": "Acme Corp",
      "address1": "123 Main St",
      "address2": "Suite 100",
      "city": "San Francisco",
      "province": "California",
      "country": "United States",
      "zip": "94103",
      "phone": "+1234567890",
      "name": "John Doe",
      "province_code": "CA",
      "country_code": "US",
      "country_name": "United States",
      "default": true
    }
  },
  "discount_applications": [],
  "discount_codes": [],
  "email": "customer@example.com",
  "financial_status": "paid",
  "fulfillment_status": null,
  "fulfillments": [],
  "gateway": "shopify_payments",
  "landing_site": "/",
  "landing_site_ref": null,
  "location_id": null,
  "name": "#1005",
  "note": "Please deliver to front door",
  "note_attributes": [
    {
      "name": "Gift wrap",
      "value": "Yes"
    }
  ],
  "number": 5,
  "order_number": 1005,
  "order_status_url": "https://store.myshopify.com/1234567/orders/abc123/authenticate",
  "payment_gateway_names": ["shopify_payments"],
  "payment_terms": null,
  "phone": "+1234567890",
  "presentment_currency": "USD",
  "processed_at": "2024-01-15T10:30:00-05:00",
  "processing_method": "direct",
  "referring_site": "https://google.com",
  "refunds": [],
  "source_identifier": "web",
  "source_name": "web",
  "source_url": null,
  "subtotal_price": "199.99",
  "subtotal_price_set": {
    "shop_money": {
      "amount": "199.99",
      "currency_code": "USD"
    },
    "presentment_money": {
      "amount": "199.99",
      "currency_code": "USD"
    }
  },
  "tags": "",
  "tax_lines": [
    {
      "price": "15.00",
      "rate": 0.075,
      "title": "California Sales Tax",
      "price_set": {
        "shop_money": {
          "amount": "15.00",
          "currency_code": "USD"
        },
        "presentment_money": {
          "amount": "15.00",
          "currency_code": "USD"
        }
      }
    }
  ],
  "taxes_included": false,
  "test": false,
  "token": "abc123def456",
  "total_discounts": "0.00",
  "total_discounts_set": {
    "shop_money": {
      "amount": "0.00",
      "currency_code": "USD"
    },
    "presentment_money": {
      "amount": "0.00",
      "currency_code": "USD"
    }
  },
  "total_line_items_price": "199.99",
  "total_line_items_price_set": {
    "shop_money": {
      "amount": "199.99",
      "currency_code": "USD"
    },
    "presentment_money": {
      "amount": "199.99",
      "currency_code": "USD"
    }
  },
  "total_outstanding": "0.00",
  "total_price": "214.99",
  "total_price_set": {
    "shop_money": {
      "amount": "214.99",
      "currency_code": "USD"
    },
    "presentment_money": {
      "amount": "214.99",
      "currency_code": "USD"
    }
  },
  "total_shipping_price_set": {
    "shop_money": {
      "amount": "0.00",
      "currency_code": "USD"
    },
    "presentment_money": {
      "amount": "0.00",
      "currency_code": "USD"
    }
  },
  "total_tax": "15.00",
  "total_tax_set": {
    "shop_money": {
      "amount": "15.00",
      "currency_code": "USD"
    },
    "presentment_money": {
      "amount": "15.00",
      "currency_code": "USD"
    }
  },
  "total_tip_received": "0.00",
  "total_weight": 500,
  "updated_at": "2024-01-15T10:30:00-05:00",
  "user_id": null,
  "line_items": [
    {
      "id": 518995019,
      "admin_graphql_api_id": "gid://shopify/LineItem/518995019",
      "fulfillable_quantity": 1,
      "fulfillment_service": "manual",
      "fulfillment_status": null,
      "gift_card": false,
      "grams": 500,
      "name": "Premium Widget",
      "origin_location": {
        "id": 1059367774,
        "country_code": "US",
        "province_code": "CA",
        "name": "Warehouse",
        "address1": "456 Storage Ave",
        "address2": "",
        "city": "Los Angeles",
        "zip": "90001"
      },
      "price": "199.99",
      "product_exists": true,
      "product_id": 632910392,
      "properties": [],
      "quantity": 1,
      "requires_shipping": true,
      "sku": "WIDGET-PRO-001",
      "taxable": true,
      "title": "Premium Widget",
      "total_discount": "0.00",
      "variant_id": 808950810,
      "variant_inventory_management": "shopify",
      "variant_title": "Large / Blue",
      "vendor": "Widget Co",
      "tax_lines": [],
      "duties": [],
      "discount_allocations": []
    }
  ],
  "billing_address": {
    "address1": "123 Main St",
    "address2": "Suite 100",
    "city": "San Francisco",
    "company": "Acme Corp",
    "country": "United States",
    "country_code": "US",
    "first_name": "John",
    "last_name": "Doe",
    "latitude": 37.7749,
    "longitude": -122.4194,
    "name": "John Doe",
    "phone": "+1234567890",
    "province": "California",
    "province_code": "CA",
    "zip": "94103"
  },
  "shipping_address": {
    "address1": "123 Main St",
    "address2": "Suite 100",
    "city": "San Francisco",
    "company": "Acme Corp",
    "country": "United States",
    "country_code": "US",
    "first_name": "John",
    "last_name": "Doe",
    "latitude": 37.7749,
    "longitude": -122.4194,
    "name": "John Doe",
    "phone": "+1234567890",
    "province": "California",
    "province_code": "CA",
    "zip": "94103"
  },
  "shipping_lines": []
}"""


def render_sidebar() -> bool:
    """Renders sidebar controls. Returns True if the generate button was clicked."""
    with st.sidebar:
        st.markdown("### Configuration")
        secret_key = st.secrets.get("GOOGLE_API_KEY", "")
        st.session_state.api_key = st.text_input(
            "Google AI Studio API Key",
            value=st.session_state.api_key or secret_key,
            type="password",
            help="Falls back to st.secrets['GOOGLE_API_KEY'] if left blank.",
        )

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
            disabled=st.session_state.pipeline_stage in {"validating_json", "calling_llm", "executing_ddl"},
            use_container_width=True,
        )
    return generate_clicked


def run_pipeline() -> None:
    """Single-path orchestration: LLM call -> validation -> DuckDB execution."""
    st.session_state.pipeline_error = None
    st.session_state.pipeline_stage = "calling_llm"

    try:
        # Validate JSON input
        st.session_state.pipeline_stage = "validating_json"
        with st.spinner("Validating JSON payload..."):
            try:
                json.loads(st.session_state.raw_json_input)
                console.log_json_validation(0.01, True, None)
            except json.JSONDecodeError as exc:
                console.log_json_validation(0.01, False, str(exc))
                raise SchemaGenerationError(f"Invalid JSON payload: {exc}") from exc

        # Call LLM
        st.session_state.pipeline_stage = "calling_llm"
        with st.spinner("Calling Gemini 2.5 Flash for schema design..."):
            generator = StarSchemaGenerator(
                api_key=st.session_state.api_key,
                model=st.session_state.selected_model,
            )
            call_result = generator.generate(st.session_state.raw_json_input)
            st.session_state.llm_call_result = call_result
            console.log_llm_call(call_result)

        # Execute DDL
        st.session_state.pipeline_stage = "executing_ddl"
        with st.spinner("Validating DDL against in-memory DuckDB sandbox..."):
            runner = DuckDBSandboxRunner()
            report = runner.execute_ddl(call_result.response.duckdb_ddl)
            st.session_state.ddl_execution_report = report
            console.log_ddl_execution(report)
            runner.close()

            if not report.success:
                raise DDLExecutionError(report.failed_statement or "", Exception(report.error_message))

        # Success
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
            Built with Python 3.10+, Pydantic v2, Gemini 2.5 Flash, DuckDB, and Streamlit
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
