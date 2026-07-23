"""
tabs.py
Pure render functions for the four main tabs. Each function accepts only
already-computed data from st.session_state and never triggers new backend calls.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from app.schemas import StarSchemaResponse
from app.services.duckdb_runner import DDLExecutionReport
from app.services.llm_engine import LLMCallResult


def _copy_to_clipboard(text: str, key: str) -> None:
    """Renders a button that uses a JS bridge to write `text` to the clipboard."""
    if st.button("📋 Copy to Clipboard", key=key, help="Copy to clipboard"):
        components.html(
            f"""
            <script>
            (async () => {{
                try {{
                    await navigator.clipboard.writeText({json.dumps(text)});
                    window.parent.postMessage({{stClipboard: 'copied'}}, '*');
                }} catch (e) {{
                    console.error('Clipboard write failed:', e);
                }}
            }})();
            </script>
            """,
            height=0,
        )
        st.toast("Copied to clipboard", icon="✅")


def render_erd_tab(schema_result: Optional[StarSchemaResponse]) -> None:
    """Tab 1: Visual ERD using Plotly graph with fact table at center and dimensions around it."""
    if schema_result is None:
        st.info("No schema generated yet. Use the sidebar to generate a star schema.")
        return

    import math

    nodes = []
    edges = []

    fact_name = schema_result.fact_table.table_name
    fact_columns = [
        f"{col.name} ({col.data_type.value})"
        for col in schema_result.fact_table.measures
    ]
    nodes.append({
        "id": fact_name,
        "label": f"{fact_name}\n{'='*30}\n" + "\n".join(fact_columns[:5]) +
                 (f"\n... and {len(fact_columns)-5} more" if len(fact_columns) > 5 else ""),
        "x": 0, "y": 0, "type": "fact", "color": "#3C9992",
    })

    num_dims = len(schema_result.dimensions)
    radius = 3.0
    for i, dim in enumerate(schema_result.dimensions):
        angle = (2 * math.pi * i) / num_dims if num_dims > 0 else 0
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        dim_columns = [f"{attr.name} ({attr.data_type.value})" for attr in dim.attributes]
        nodes.append({
            "id": dim.table_name,
            "label": f"{dim.table_name}\n{'='*30}\n" + "\n".join(dim_columns[:4]) +
                     (f"\n... and {len(dim_columns)-4} more" if len(dim_columns) > 4 else ""),
            "x": x, "y": y, "type": "dimension", "color": "#7FD8CF",
        })
        fk_col = next(
            (col for col in schema_result.fact_table.measures
             if col.references_table == dim.table_name),
            None,
        )
        if fk_col:
            edges.append({"source": fact_name, "target": dim.table_name, "label": fk_col.name})

    fig = go.Figure()

    for edge in edges:
        source_node = next(n for n in nodes if n["id"] == edge["source"])
        target_node = next(n for n in nodes if n["id"] == edge["target"])
        fig.add_trace(go.Scatter(
            x=[source_node["x"], target_node["x"]],
            y=[source_node["y"], target_node["y"]],
            mode="lines",
            line=dict(color="#A9C2C0", width=2),
            hoverinfo="text",
            hovertext=f"{edge['source']}.{edge['label']} → {edge['target']}",
            showlegend=False,
        ))

    for node in nodes:
        fig.add_trace(go.Scatter(
            x=[node["x"]], y=[node["y"]],
            mode="markers+text",
            marker=dict(
                size=80, color=node["color"],
                line=dict(color="#FFFFFF", width=2),
                symbol="circle" if node["type"] == "fact" else "square",
            ),
            text=[node["label"]],
            textposition="middle center",
            textfont=dict(size=9, color="#FFFFFF"),
            hoverinfo="text", hovertext=node["label"],
            showlegend=False,
        ))

    fig.update_layout(
        title=f"Star Schema ERD: {schema_result.fact_table.table_name}",
        showlegend=False, hovermode="closest",
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=20, r=20, t=40, b=20), height=600,
    )
    st.plotly_chart(fig, use_container_width=True)

    col1, col2, col3 = st.columns(3)
    with col1: st.metric("Fact Tables", 1)
    with col2: st.metric("Dimension Tables", len(schema_result.dimensions))
    with col3:
        total_columns = len(schema_result.fact_table.measures)
        for dim in schema_result.dimensions:
            total_columns += len(dim.attributes)
        st.metric("Total Columns", total_columns)


def render_ddl_sandbox_tab(
    schema_result: Optional[StarSchemaResponse],
    ddl_report: Optional[DDLExecutionReport],
) -> None:
    if schema_result is None:
        st.info("No schema generated yet. Use the sidebar to generate a star schema.")
        return

    st.markdown("### DuckDB DDL Script")
    st.code(schema_result.duckdb_ddl, language="sql")

    st.markdown("---")
    st.markdown("### Sandbox Execution Report")

    if ddl_report is None:
        st.warning("DDL has not been executed in the sandbox yet.")
        return

    if ddl_report.success:
        st.success("✅ All DDL statements executed successfully!")
    else:
        st.error("❌ DDL execution failed!")
        st.markdown("#### Failed Statement:")
        st.code(ddl_report.failed_statement or "", language="sql")
        st.markdown("#### Error Message:")
        st.error(ddl_report.error_message or "Unknown error")

    col1, col2, col3 = st.columns(3)
    with col1: st.metric("Total Statements", ddl_report.total_statements)
    with col2: st.metric("Executed", len(ddl_report.executed_statements))
    with col3: st.metric("Tables Created", len(ddl_report.tables_created))

    if ddl_report.tables_created:
        st.markdown("#### Tables Created:")
        for table in ddl_report.tables_created:
            st.markdown(f"- `{table}`")

    st.markdown("---")
    if st.button("🔄 Re-run DDL in Sandbox", type="secondary"):
        with st.spinner("Re-executing DDL..."):
            from app.services.duckdb_runner import DuckDBSandboxRunner
            runner = DuckDBSandboxRunner()
            try:
                new_report = runner.execute_ddl(schema_result.duckdb_ddl)
                st.session_state.ddl_execution_report = new_report
            finally:
                runner.close()
            st.rerun()


def render_dbt_tab(schema_result: Optional[StarSchemaResponse]) -> None:
    if schema_result is None:
        st.info("No schema generated yet. Use the sidebar to generate a star schema.")
        return

    st.markdown("### Staging Models")
    for file in schema_result.dbt_models.staging_models:
        with st.expander(f"📄 {file.filename}", expanded=False):
            st.code(file.content, language="sql")
            _copy_to_clipboard(file.content, key=f"copy_{file.filename}")

    st.markdown("### Mart Models")
    for file in schema_result.dbt_models.mart_models:
        with st.expander(f"📄 {file.filename}", expanded=False):
            st.code(file.content, language="sql")
            _copy_to_clipboard(file.content, key=f"copy_{file.filename}")

    st.markdown("### Schema Metadata")
    with st.expander("📄 schema.yml", expanded=False):
        st.code(schema_result.dbt_models.schema_yml, language="yaml")
        _copy_to_clipboard(schema_result.dbt_models.schema_yml, key="copy_schema_yml")

    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    with col1: st.metric("Staging Models", len(schema_result.dbt_models.staging_models))
    with col2: st.metric("Mart Models", len(schema_result.dbt_models.mart_models))
    with col3:
        st.metric(
            "Total Files",
            len(schema_result.dbt_models.staging_models)
            + len(schema_result.dbt_models.mart_models)
            + 1,
        )


def render_debug_tab(
    schema_result: Optional[StarSchemaResponse],
    llm_call_result: Optional[LLMCallResult],
    telemetry_log: List[Dict],
) -> None:
    st.markdown("### Pipeline Metrics")

    if llm_call_result is not None:
        col1, col2, col3, col4 = st.columns(4)
        with col1: st.metric("LLM Latency", f"{llm_call_result.latency_seconds:.2f}s")
        with col2: st.metric("Prompt Tokens", llm_call_result.prompt_token_count)
        with col3: st.metric("Candidate Tokens", llm_call_result.candidates_token_count)
        with col4:
            total = llm_call_result.prompt_token_count + llm_call_result.candidates_token_count
            st.metric("Total Tokens", total)
    else:
        st.warning("No LLM call metrics available.")

    st.markdown("---")
    st.markdown("### Validated Pydantic Payload")
    if schema_result is not None:
        payload_dict = schema_result.model_dump(mode="python")
        st.json(payload_dict)
    else:
        st.info("No schema payload to display.")

    st.markdown("---")
    st.markdown("### Execution Telemetry Log")
    if not telemetry_log:
        st.info("No telemetry events recorded yet.")
        return
    for entry in reversed(telemetry_log):
        stage = entry.get("stage", "unknown")
        timestamp = entry.get("timestamp", "")
        with st.expander(f"📊 {stage} — {timestamp}", expanded=False):
            st.json(entry)

    st.markdown("---")
    st.markdown("### Telemetry Summary")
    col1, col2, col3 = st.columns(3)
    with col1: st.metric("Total Events", len(telemetry_log))
    with col2:
        stages = set(e.get("stage", "") for e in telemetry_log)
        st.metric("Unique Stages", len(stages))
    with col3:
        if telemetry_log:
            st.metric("Latest Event", telemetry_log[-1].get("timestamp", "N/A"))
