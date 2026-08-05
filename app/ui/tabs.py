"""
tabs.py
Pure render functions for the four main tabs. Each function accepts only
already-computed data from st.session_state and never triggers new backend calls.
"""

from __future__ import annotations

import html
import json
import math
from typing import Dict, List, Optional

import streamlit as st

from app.schemas import StarSchemaResponse
from app.services.duckdb_runner import DDLExecutionReport
from app.services.llm_engine import LLMCallResult


def _copy_to_clipboard(text: str, key: str) -> None:
    """Renders a button that uses a JS bridge to write `text` to the clipboard."""
    if st.button("📋 Copy to Clipboard", key=key, help="Copy to clipboard"):
        st.iframe(
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


# ---------------------------------------------------------------------------
# Visual ERD — custom interactive blueprint renderer
# ---------------------------------------------------------------------------
_ERD_HEAD = 58          # px reserved for the in-canvas title / legend strip
_ERD_MARGIN = 44        # px breathing room around the laid-out graph
_ERD_MAX_ROWS = 7       # columns shown per card before a "+N more" row


def _erd_cap(s: str, n: int = 34) -> str:
    s = "" if s is None else str(s)
    return s if len(s) <= n else s[: max(1, n - 1)] + "…"


def _erd_fact_rows(fact) -> List[Dict]:
    rows: List[Dict] = []
    for col in fact.measures:
        badges: List[str] = []
        if col.is_primary_key:
            badges.append("PK")
        if col.is_foreign_key:
            badges.append("FK")
        rows.append({
            "name": _erd_cap(col.name),
            "type": _erd_cap(getattr(col.data_type, "value", str(col.data_type)), 16),
            "badges": badges,
            "muted": False,
        })
    if len(rows) > _ERD_MAX_ROWS:
        extra = len(rows) - _ERD_MAX_ROWS
        rows = rows[:_ERD_MAX_ROWS]
        rows.append({"name": f"+{extra} more columns", "type": "", "badges": [], "muted": True})
    return rows or [{"name": "(no columns)", "type": "", "badges": [], "muted": True}]


def _erd_dim_rows(dim) -> List[Dict]:
    rows: List[Dict] = []
    for attr in dim.attributes:
        badges: List[str] = []
        if attr.is_surrogate_key:
            badges.append("SK")
        if attr.is_business_key:
            badges.append("BK")
        rows.append({
            "name": _erd_cap(attr.name),
            "type": _erd_cap(getattr(attr.data_type, "value", str(attr.data_type)), 16),
            "badges": badges,
            "muted": False,
        })
    if len(rows) > _ERD_MAX_ROWS:
        extra = len(rows) - _ERD_MAX_ROWS
        rows = rows[:_ERD_MAX_ROWS]
        rows.append({"name": f"+{extra} more columns", "type": "", "badges": [], "muted": True})
    return rows or [{"name": "(no columns)", "type": "", "badges": [], "muted": True}]


def _erd_card_size(name: str, rows: List[Dict]):
    """Return (width, height) in px, derived from the card's textual content."""
    header_metric = len(name) * 9.0 + 96          # dot + gaps + kind tag
    row_metrics = []
    for r in rows:
        badge_w = sum(30 for _ in r["badges"])
        combined = f'{r["name"]}  {r["type"]}' if r["type"] else r["name"]
        row_metrics.append(badge_w + len(combined) * 7.3 + 26)
    content_w = max([header_metric] + row_metrics)
    w = max(250, min(440, content_w + 18))
    h = 46 + 8 + 27 * max(1, len(rows)) + 10      # head + pad-top + rows + pad-bottom
    return w, h


def _erd_border(cx: float, cy: float, w: float, h: float, tx: float, ty: float):
    """Point on the rectangle border (center cx,cy / size w,h) facing target tx,ty."""
    dx, dy = tx - cx, ty - cy
    if dx == 0 and dy == 0:
        return cx, cy
    hx, hy = w / 2.0, h / 2.0
    sx = hx / abs(dx) if dx else float("inf")
    sy = hy / abs(dy) if dy else float("inf")
    s = min(sx, sy)
    return cx + dx * s, cy + dy * s


def _erd_arrow_points(x1: float, y1: float, x2: float, y2: float) -> str:
    """Triangle polygon (tip at x2,y2) oriented along the line direction."""
    dx, dy = x2 - x1, y2 - y1
    norm = math.hypot(dx, dy) or 1.0
    ux, uy = dx / norm, dy / norm
    bx, by = x2 - ux * 9, y2 - uy * 9
    px, py = -uy * 4.5, ux * 4.5
    return f"{x2:.1f},{y2:.1f} {bx + px:.1f},{by + py:.1f} {bx - px:.1f},{by - py:.1f}"


def _erd_badges_html(badges: List[str]) -> str:
    cls = {"PK": "b-pk", "FK": "b-fk", "SK": "b-sk", "BK": "b-bk"}
    return "".join(
        f'<span class="b {cls.get(b, "b-pk")}">{html.escape(b)}</span>' for b in badges
    )


def _erd_card_html(node: Dict, delay: float) -> str:
    rows_html = []
    for r in node["rows"]:
        muted = " muted" if r["muted"] else ""
        rows_html.append(
            f'<div class="row{muted}">'
            f'<span class="badges">{_erd_badges_html(r["badges"])}</span>'
            f'<span class="cname">{html.escape(r["name"])}</span>'
            f'<span class="ctype">{html.escape(r["type"])}</span>'
            f"</div>"
        )
    kind = node["kind"]
    tag = "FACT" if kind == "fact" else "DIM"
    return (
        f'<div class="node {kind}" data-id="{html.escape(node["id"])}" '
        f'style="left:{node["left"]:.1f}px;top:{node["top"]:.1f}px;'
        f'width:{node["w"]:.0f}px;height:{node["h"]:.0f}px;--d:{delay:.2f}s">'
        f'<div class="node-head"><span class="dot"></span>'
        f'<span class="tname">{html.escape(node["name"])}</span>'
        f'<span class="kind-tag">{tag}</span></div>'
        f'<div class="node-body">{"".join(rows_html)}</div>'
        f"</div>"
    )


_ERD_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  background-color:#0E1716;
  background-image:
    radial-gradient(1100px 620px at 18% 6%, rgba(60,153,146,.14), transparent 60%),
    radial-gradient(900px 700px at 88% 98%, rgba(127,216,207,.08), transparent 62%),
    linear-gradient(rgba(127,216,207,.045) 1px, transparent 1px),
    linear-gradient(90deg, rgba(127,216,207,.045) 1px, transparent 1px);
  background-size:auto,auto,34px 34px,34px 34px;
  color:#EAF3F2;
  font-family:'Space Grotesk',system-ui,sans-serif;
  overflow-x:auto; overflow-y:hidden;
  -webkit-font-smoothing:antialiased;
}
#erd{position:relative; width:__W__px; height:__H__px; margin:0 auto;}
.erd-head{position:absolute; top:0; left:0; right:0; height:__HEAD__px; z-index:4;
  display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap;
  gap:6px 14px; padding:0 8px;}
.erd-title{display:flex; align-items:baseline; gap:10px; position:sticky; left:8px;
  background:linear-gradient(90deg,#0E1716 72%,rgba(14,23,22,0)); padding-right:18px;}
.et-k{color:#A9C2C0; text-transform:uppercase; letter-spacing:2.6px; font-size:11px; font-weight:600;}
.et-sep{color:#2f5b57; font-weight:300;}
.et-name{font-family:'JetBrains Mono',monospace; font-size:20px; font-weight:700; color:#7FD8CF; letter-spacing:.2px;}
.erd-legend{display:flex; flex-wrap:wrap; justify-content:flex-end; gap:8px 15px; align-items:center;
  font-size:11.5px; color:#A9C2C0; letter-spacing:.4px; position:sticky; right:8px;
  background:linear-gradient(270deg,#0E1716 72%,rgba(14,23,22,0)); padding-left:18px;}
.lg{display:inline-flex; align-items:center; gap:7px;}
.lg i{width:13px; height:13px; display:inline-block;}
.lg-fact{background:linear-gradient(135deg,#3C9992,#2C7A74); border-radius:50%;}
.lg-dim{background:linear-gradient(135deg,#1d4a46,#3C9992); border-radius:3px;}
.lg-fk{width:18px; height:0; border-top:2px dashed #7FD8CF;}
svg.layer{position:absolute; inset:0; width:__W__px; height:__H__px; overflow:visible; z-index:1;}
.edge-line{stroke:#5f8783; stroke-width:1.6; opacity:.55; transition:stroke .18s,opacity .18s,stroke-width .18s;}
.edge-flow{stroke:#7FD8CF; stroke-width:2; stroke-dasharray:5 11; opacity:.35; animation:flow 1.1s linear infinite; transition:opacity .18s;}
.arrow{fill:#5f8783; opacity:.7; transition:fill .18s,opacity .18s;}
@keyframes flow{to{stroke-dashoffset:-32;}}
.fact-glow{position:absolute; width:360px; height:360px; border-radius:50%; z-index:0;
  background:radial-gradient(circle, rgba(60,153,146,.30), rgba(60,153,146,0) 68%);
  transform:translate(-50%,-50%); pointer-events:none; animation:pulse 4.5s ease-in-out infinite;}
@keyframes pulse{0%,100%{opacity:.5; transform:translate(-50%,-50%) scale(1);}50%{opacity:.85; transform:translate(-50%,-50%) scale(1.09);}}
.node{position:absolute; z-index:2; border-radius:14px; overflow:hidden;
  background:rgba(13,24,23,.94); border:1px solid rgba(255,255,255,.12);
  box-shadow:0 10px 30px rgba(0,0,0,.45); cursor:pointer; opacity:1;
  animation:fade .55s ease backwards; animation-delay:var(--d,0s);
  transition:transform .18s ease, box-shadow .18s ease, border-color .18s ease;}
.node:hover{transform:translateY(-4px); border-color:rgba(127,216,207,.55);
  box-shadow:0 18px 46px rgba(0,0,0,.55), 0 0 0 1px rgba(127,216,207,.22);}
.node-head{height:46px; display:flex; align-items:center; gap:9px; padding:0 13px; position:relative;}
.node.fact .node-head{background:linear-gradient(135deg,#3C9992,#23635e);}
.node.dim .node-head{background:linear-gradient(135deg,#16302e,#23504b); border-bottom:1px solid rgba(127,216,207,.18);}
.node.dim .node-head::before{content:""; position:absolute; left:0; top:0; bottom:0; width:4px; background:#7FD8CF;}
.dot{width:9px; height:9px; border-radius:50%; background:#EAF3F2; box-shadow:0 0 0 3px rgba(255,255,255,.12); flex:0 0 auto;}
.node.dim .dot{background:#7FD8CF; box-shadow:0 0 0 3px rgba(127,216,207,.18);}
.tname{font-family:'JetBrains Mono',monospace; font-size:13.5px; font-weight:600; color:#fff; letter-spacing:.2px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}
.node.dim .tname{color:#CDEFEA;}
.kind-tag{margin-left:auto; flex:0 0 auto; font-size:9.5px; letter-spacing:1.5px; font-weight:700; padding:3px 7px; border-radius:6px; background:rgba(0,0,0,.28); color:rgba(255,255,255,.82);}
.node-body{padding:8px 6px 10px;}
.row{display:flex; align-items:center; gap:8px; height:27px; padding:0 8px; border-radius:7px;}
.row:nth-child(odd){background:rgba(255,255,255,.025);}
.row.muted{opacity:.5;}
.badges{display:flex; gap:4px; flex:0 0 auto;}
.badges:empty{display:none;}
.b{font-family:'JetBrains Mono',monospace; font-size:9px; font-weight:700; letter-spacing:.5px; padding:2px 5px; border-radius:5px; line-height:1;}
.b-pk,.b-sk{background:rgba(127,216,207,.18); color:#9fe6dd;}
.b-fk{background:rgba(232,180,90,.16); color:#f0c987;}
.b-bk{background:rgba(150,170,255,.16); color:#b9c4ff;}
.cname{font-family:'JetBrains Mono',monospace; font-size:12px; color:#EAF3F2; flex:1 1 auto; min-width:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}
.ctype{font-family:'JetBrains Mono',monospace; font-size:10.5px; color:#7fa9a4; flex:0 0 auto; white-space:nowrap;}
.row.muted .cname{color:#7fa9a4; font-style:italic;}
.elabel{position:absolute; z-index:3; transform:translate(-50%,-50%); font-family:'JetBrains Mono',monospace; font-size:10px;
  color:#CDEFEA; background:rgba(13,24,23,.92); border:1px solid rgba(127,216,207,.3);
  padding:3px 9px 3px 8px; border-radius:20px; white-space:nowrap; pointer-events:none;
  box-shadow:0 4px 14px rgba(0,0,0,.4); transition:opacity .18s, border-color .18s, color .18s;}
.elabel::before{content:"\\2192  "; color:#7FD8CF;}
#erd.dim .node:not(.active){opacity:.3; filter:saturate(.5);}
#erd.dim .edge:not(.active) .edge-line{opacity:.08;}
#erd.dim .edge:not(.active) .edge-flow{opacity:.05;}
#erd.dim .edge:not(.active) .arrow{opacity:.08;}
#erd.dim .elabel:not(.active){opacity:.1;}
#erd.dim .node.active{opacity:1;}
.edge.active .edge-line{stroke:#7FD8CF; opacity:1; stroke-width:2.4;}
.edge.active .edge-flow{opacity:.95;}
.edge.active .arrow{fill:#7FD8CF; opacity:1;}
.elabel.active{border-color:#7FD8CF; color:#fff;}
@keyframes fade{from{opacity:0;}to{opacity:1;}}
</style>
</head>
<body>
<div id="erd">
  <div class="fact-glow" style="left:__FCX__px;top:__FCY__px;"></div>
  <div class="erd-head">
    <div class="erd-title"><span class="et-k">Star Schema</span><span class="et-sep">/</span><span class="et-name">__TITLE__</span></div>
    <div class="erd-legend">
      <span class="lg"><i class="lg-fact"></i>Fact</span>
      <span class="lg"><i class="lg-dim"></i>Dimension</span>
      <span class="lg"><i class="lg-fk"></i>Foreign key</span>
    </div>
  </div>
  <svg class="layer" viewBox="0 0 __W__ __H__" xmlns="http://www.w3.org/2000/svg">__EDGES__</svg>
  __CARDS__
  __LABELS__
</div>
<script>
(function(){
  var root=document.getElementById('erd');
  if(!root) return;
  var nodes=Array.prototype.slice.call(root.querySelectorAll('.node'));
  var edges=Array.prototype.slice.call(root.querySelectorAll('.edge'));
  var labels=Array.prototype.slice.call(root.querySelectorAll('.elabel'));
  function clear(){
    root.classList.remove('dim');
    nodes.forEach(function(n){n.classList.remove('active');});
    edges.forEach(function(e){e.classList.remove('active');});
    labels.forEach(function(l){l.classList.remove('active');});
  }
  function activate(id){
    root.classList.add('dim');
    nodes.forEach(function(n){ if(n.getAttribute('data-id')===id) n.classList.add('active'); });
    edges.forEach(function(e){
      var s=e.getAttribute('data-source'), t=e.getAttribute('data-target');
      if(s===id||t===id){
        e.classList.add('active');
        var other=(s===id)?t:s;
        var on=nodes.filter(function(n){return n.getAttribute('data-id')===other;})[0];
        if(on) on.classList.add('active');
      }
    });
    labels.forEach(function(l){
      var s=l.getAttribute('data-source'), t=l.getAttribute('data-target');
      if(s===id||t===id) l.classList.add('active');
    });
  }
  nodes.forEach(function(n){
    n.addEventListener('mouseenter',function(){activate(n.getAttribute('data-id'));});
  });
  root.addEventListener('mouseleave',clear);
})();
</script>
</body>
</html>"""


def render_erd_tab(schema_result: Optional[StarSchemaResponse]) -> None:
    """Tab 1: interactive star-schema blueprint (HTML/SVG, no Plotly)."""
    if schema_result is None:
        st.info("No schema generated yet. Use the sidebar to generate a star schema.")
        return

    fact = schema_result.fact_table
    fact_name = fact.table_name
    fact_rows = _erd_fact_rows(fact)
    fact_w, fact_h = _erd_card_size(fact_name, fact_rows)

    dim_specs: List[Dict] = []
    for i, dim in enumerate(schema_result.dimensions):
        d_rows = _erd_dim_rows(dim)
        d_w, d_h = _erd_card_size(dim.table_name, d_rows)
        dim_specs.append({
            "id": f"d{i}", "kind": "dim", "name": dim.table_name,
            "rows": d_rows, "w": d_w, "h": d_h,
        })

    # ---- radial layout (fact at origin, dimensions spaced around it) ----
    n = len(dim_specs)
    max_dim_w = max((d["w"] for d in dim_specs), default=0)
    max_dim_h = max((d["h"] for d in dim_specs), default=0)
    if n == 0:
        r = 0.0
    elif n == 1:
        r = fact_w / 2 + max_dim_w / 2 + 150
    else:
        chord_need = max_dim_w + 90
        r_chord = chord_need / (2 * math.sin(math.pi / n))
        diag = (math.hypot(max_dim_w, max_dim_h) / 2
                + math.hypot(fact_w, fact_h) / 2 + 90)
        r_clear = fact_w / 2 + max_dim_w / 2 + 130
        r = max(r_chord, r_clear, diag, 340)

    nodes: List[Dict] = []
    # fact card (centered at origin in layout-space)
    nodes.append({
        "id": "fact", "kind": "fact", "name": fact_name, "rows": fact_rows,
        "w": fact_w, "h": fact_h, "cx": 0.0, "cy": 0.0,
    })
    for i, d in enumerate(dim_specs):
        angle = -math.pi / 2 + (2 * math.pi * i / n)
        d["cx"] = r * math.cos(angle)
        d["cy"] = r * math.sin(angle)
        nodes.append(d)

    for nd in nodes:
        nd["left"] = nd["cx"] - nd["w"] / 2
        nd["top"] = nd["cy"] - nd["h"] / 2

    # ---- bounding box -> canvas size + centering offsets ----
    min_l = min(nd["left"] for nd in nodes)
    min_t = min(nd["top"] for nd in nodes)
    max_r = max(nd["left"] + nd["w"] for nd in nodes)
    max_b = max(nd["top"] + nd["h"] for nd in nodes)
    content_w = max_r - min_l
    content_h = max_b - min_t
    w_canvas = max(content_w + 2 * _ERD_MARGIN, 1040)
    h_canvas = _ERD_HEAD + content_h + 2 * _ERD_MARGIN
    off_x = (w_canvas - content_w) / 2 - min_l
    off_y = _ERD_HEAD + _ERD_MARGIN - min_t
    for nd in nodes:
        nd["left"] += off_x
        nd["top"] += off_y
        nd["cx"] = nd["left"] + nd["w"] / 2
        nd["cy"] = nd["top"] + nd["h"] / 2

    by_id = {nd["id"]: nd for nd in nodes}
    fact_node = by_id["fact"]

    # ---- connectors (border-accurate) + FK label pills ----
    edges_svg: List[str] = []
    labels_html: List[str] = []
    for d in dim_specs:
        dn = by_id[d["id"]]
        x1, y1 = _erd_border(fact_node["cx"], fact_node["cy"], fact_node["w"], fact_node["h"], dn["cx"], dn["cy"])
        x2, y2 = _erd_border(dn["cx"], dn["cy"], dn["w"], dn["h"], fact_node["cx"], fact_node["cy"])
        arrow = _erd_arrow_points(x1, y1, x2, y2)
        edges_svg.append(
            f'<g class="edge" data-source="fact" data-target="{d["id"]}">'
            f'<line class="edge-line" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>'
            f'<line class="edge-flow" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>'
            f'<polygon class="arrow" points="{arrow}"/></g>'
        )
        # FK column that points at this dimension
        fk_col = next(
            (c for c in fact.measures if c.references_table == d["name"]), None
        )
        if fk_col:
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            labels_html.append(
                f'<div class="elabel" data-source="fact" data-target="{d["id"]}" '
                f'style="left:{mx:.1f}px;top:{my:.1f}px">{html.escape(_erd_cap(fk_col.name, 24))}</div>'
            )

    # ---- card markup (fact first so its halo/animation leads) ----
    cards_html = [_erd_card_html(fact_node, 0.0)]
    for i, d in enumerate(dim_specs):
        cards_html.append(_erd_card_html(by_id[d["id"]], 0.12 + i * 0.07))

    rendered = (
        _ERD_TEMPLATE
        .replace("__W__", f"{w_canvas:.0f}")
        .replace("__H__", f"{h_canvas:.0f}")
        .replace("__HEAD__", str(_ERD_HEAD))
        .replace("__TITLE__", html.escape(fact_name))
        .replace("__FCX__", f"{fact_node['cx']:.1f}")
        .replace("__FCY__", f"{fact_node['cy']:.1f}")
        .replace("__EDGES__", "".join(edges_svg))
        .replace("__CARDS__", "".join(cards_html))
        .replace("__LABELS__", "".join(labels_html))
    )

    st.iframe(rendered, height=int(h_canvas) + 2, scrolling=True)

    # ---- summary metrics (theme-styled, below the canvas) ----
    total_columns = len(fact.measures) + sum(len(d.attributes) for d in schema_result.dimensions)
    fk_count = sum(1 for c in fact.measures if c.is_foreign_key)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Fact Tables", 1)
    c2.metric("Dimension Tables", len(schema_result.dimensions))
    c3.metric("Total Columns", total_columns)
    c4.metric("Foreign Keys", fk_count)


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
