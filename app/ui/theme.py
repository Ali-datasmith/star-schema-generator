"""
theme.py
Injects the glassmorphism / spatial UI CSS theme. Call inject_glassmorphism_css()
once, immediately after st.set_page_config().
"""

import streamlit as st

GLASSMORPHISM_CSS = """
<style>
:root {
    --accent: #3C9992;
    --accent-soft: rgba(60, 153, 146, 0.16);
    --accent-strong: rgba(60, 153, 146, 0.55);
    --glass-bg: rgba(255, 255, 255, 0.06);
    --glass-border: rgba(255, 255, 255, 0.14);
    --glass-shadow: 0 8px 32px rgba(0, 0, 0, 0.28);
    --text-primary: #EAF3F2;
    --text-secondary: #A9C2C0;
    --radius-lg: 20px;
    --radius-md: 14px;
}

.stApp {
    background: radial-gradient(circle at 15% 10%, rgba(60, 153, 146, 0.15), transparent 45%),
                radial-gradient(circle at 85% 85%, rgba(60, 153, 146, 0.10), transparent 40%),
                #0E1716;
    color: var(--text-primary);
}

/* Hero header */
.glass-hero {
    background: var(--glass-bg);
    border: 1px solid var(--glass-border);
    border-radius: var(--radius-lg);
    box-shadow: var(--glass-shadow);
    backdrop-filter: blur(18px);
    -webkit-backdrop-filter: blur(18px);
    padding: 2.25rem 2.5rem;
    margin-bottom: 1.5rem;
}
.glass-hero h1 {
    margin: 0 0 0.4rem 0;
    font-size: 2.1rem;
    font-weight: 700;
    background: linear-gradient(90deg, var(--accent), #7FD8CF);
    -webkit-background-clip: text;
    background-clip: text;
    color: transparent;
}
.glass-hero p {
    margin: 0;
    color: var(--text-secondary);
    font-size: 1rem;
}

/* Generic glass panel utility class for custom components */
.glass-panel {
    background: var(--glass-bg);
    border: 1px solid var(--glass-border);
    border-radius: var(--radius-md);
    box-shadow: var(--glass-shadow);
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
    padding: 1.25rem 1.5rem;
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background: rgba(14, 23, 22, 0.92);
    border-right: 1px solid var(--glass-border);
}

/* Buttons */
.stButton > button {
    background: linear-gradient(135deg, var(--accent), #2C7A74);
    color: #FFFFFF;
    border: 1px solid var(--accent-strong);
    border-radius: 10px;
    font-weight: 600;
    box-shadow: 0 4px 14px var(--accent-soft);
    transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.stButton > button:hover {
    transform: translateY(-1px);
    box-shadow: 0 6px 20px var(--accent-strong);
}
.stButton > button:disabled {
    opacity: 0.45;
    box-shadow: none;
}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
    gap: 0.5rem;
    background: var(--glass-bg);
    border-radius: 12px;
    padding: 0.35rem;
    border: 1px solid var(--glass-border);
}
.stTabs [data-baseweb="tab"] {
    border-radius: 9px;
    color: var(--text-secondary);
    padding: 0.5rem 1rem;
}
.stTabs [aria-selected="true"] {
    background: var(--accent-soft) !important;
    color: var(--text-primary) !important;
    font-weight: 600;
}

/* Metrics */
[data-testid="stMetric"] {
    background: var(--glass-bg);
    border: 1px solid var(--glass-border);
    border-radius: var(--radius-md);
    padding: 0.9rem 1rem;
}
[data-testid="stMetricLabel"] { color: var(--text-secondary); }
[data-testid="stMetricValue"] { color: var(--accent); }

/* Code blocks */
.stCodeBlock, pre {
    border: 1px solid var(--glass-border) !important;
    border-radius: var(--radius-md) !important;
}

/* Expander */
.streamlit-expanderHeader {
    background: var(--glass-bg);
    border-radius: var(--radius-md);
    border: 1px solid var(--glass-border);
}

/* Text areas / inputs */
.stTextArea textarea, .stTextInput input {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid var(--glass-border);
    color: var(--text-primary);
    border-radius: 10px;
}
.stTextArea textarea:focus, .stTextInput input:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 2px var(--accent-soft);
}
</style>
"""


def inject_glassmorphism_css() -> None:
    st.markdown(GLASSMORPHISM_CSS, unsafe_allow_html=True)
