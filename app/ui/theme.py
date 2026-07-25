"""
theme.py
Injects the glassmorphism / spatial UI CSS theme. Call inject_glassmorphism_css()
once, immediately after st.set_page_config().

This revision adds:
  * Radiant typography glow on the hero headline (breathing), hero sublines,
    body markdown headers / subheaders, and metric values.
  * A refined sidebar: brand accent strip, tracked section label, live-engine
    status card, brighter labels, blooming focus rings, divided caption,
    shimmer CTA, and a themed scrollbar.
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

/* ------------------------------------------------------------------ */
/* Hero header                                                        */
/* ------------------------------------------------------------------ */
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

/* ------------------------------------------------------------------ */
/* Generic glass panel utility class for custom components            */
/* ------------------------------------------------------------------ */
.glass-panel {
    background: var(--glass-bg);
    border: 1px solid var(--glass-border);
    border-radius: var(--radius-md);
    box-shadow: var(--glass-shadow);
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
    padding: 1.25rem 1.5rem;
}

/* ------------------------------------------------------------------ */
/* Sidebar — structure, hierarchy, rhythm                             */
/* ------------------------------------------------------------------ */
section[data-testid="stSidebar"] {
    position: relative;
    background:
        radial-gradient(120% 55% at 50% -8%, rgba(60, 153, 146, 0.18), transparent 62%),
        linear-gradient(180deg, rgba(16, 27, 26, 0.98), rgba(10, 17, 16, 0.98));
    border-right: 1px solid rgba(127, 216, 207, 0.12);
    box-shadow: 6px 0 34px rgba(0, 0, 0, 0.38);
}
/* top brand accent strip */
section[data-testid="stSidebar"]::before {
    content: "";
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
    background: linear-gradient(90deg,
        transparent, #3C9992 28%, #7FD8CF 50%, #3C9992 72%, transparent);
    opacity: 0.92;
    z-index: 5;
}
/* inner scroll padding / breathing room */
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
    padding: 2rem 1.4rem 2.6rem;
}
/* themed scrollbar */
section[data-testid="stSidebar"] [data-testid="stSidebarContent"]::-webkit-scrollbar { width: 8px; }
section[data-testid="stSidebar"] [data-testid="stSidebarContent"]::-webkit-scrollbar-track { background: transparent; }
section[data-testid="stSidebar"] [data-testid="stSidebarContent"]::-webkit-scrollbar-thumb {
    background: rgba(127, 216, 207, 0.22);
    border-radius: 8px;
}
section[data-testid="stSidebar"] [data-testid="stSidebarContent"]::-webkit-scrollbar-thumb:hover {
    background: rgba(127, 216, 207, 0.4);
}

/* section title ("Configuration") — tracked label + glowing bullet + rule */
section[data-testid="stSidebar"] .stMarkdown h3,
section[data-testid="stSidebar"] h3 {
    display: flex;
    align-items: center;
    gap: 0.55rem;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.22em;
    font-weight: 700;
    color: #7FD8CF;
    margin: 0.1rem 0 1.25rem;
    padding-bottom: 0.75rem;
    border-bottom: 1px solid rgba(127, 216, 207, 0.16);
    text-shadow: 0 0 10px rgba(60, 153, 146, 0.4);
}
section[data-testid="stSidebar"] .stMarkdown h3::before,
section[data-testid="stSidebar"] h3::before {
    content: "";
    width: 7px; height: 7px;
    border-radius: 2px;
    flex: 0 0 auto;
    background: linear-gradient(135deg, #7FD8CF, #3C9992);
    box-shadow: 0 0 9px rgba(127, 216, 207, 0.75);
    transform: rotate(45deg);
}

/* field labels — brighter, tighter, clearer hierarchy */
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] .stTextInput label,
section[data-testid="stSidebar"] .stSelectbox label,
section[data-testid="stSidebar"] .stTextArea label {
    font-size: 0.8rem;
    font-weight: 600;
    letter-spacing: 0.02em;
    color: #CDEFEA;
    margin-bottom: 0.35rem;
}

/* inputs / select / textarea — consistent surfaces */
section[data-testid="stSidebar"] .stTextInput input,
section[data-testid="stSidebar"] .stTextArea textarea,
section[data-testid="stSidebar"] .stSelectbox [data-baseweb="select"] > div {
    background: rgba(255, 255, 255, 0.045);
    border: 1px solid rgba(127, 216, 207, 0.16);
    border-radius: 11px;
    color: var(--text-primary);
    transition: border-color 0.18s ease, box-shadow 0.18s ease, background 0.18s ease;
}
section[data-testid="stSidebar"] .stTextInput input:hover,
section[data-testid="stSidebar"] .stTextArea textarea:hover,
section[data-testid="stSidebar"] .stSelectbox [data-baseweb="select"]:hover > div {
    border-color: rgba(127, 216, 207, 0.32);
}
section[data-testid="stSidebar"] .stTextInput input:focus,
section[data-testid="stSidebar"] .stTextArea textarea:focus {
    border-color: rgba(127, 216, 207, 0.6);
    background: rgba(255, 255, 255, 0.06);
    box-shadow: 0 0 0 3px rgba(60, 153, 146, 0.18), 0 0 18px rgba(60, 153, 146, 0.2);
}
section[data-testid="stSidebar"] .stSelectbox [data-baseweb="select"]:focus-within > div {
    border-color: rgba(127, 216, 207, 0.6);
    box-shadow: 0 0 0 3px rgba(60, 153, 146, 0.18), 0 0 18px rgba(60, 153, 146, 0.2);
}

/* model-engine status card — live indicator */
section[data-testid="stSidebar"] [data-testid="stAlert"] {
    position: relative;
    margin: 0.25rem 0 0.5rem;
    padding: 0.85rem 2.3rem 0.85rem 1.05rem;
    background: linear-gradient(135deg, rgba(60, 153, 146, 0.18), rgba(60, 153, 146, 0.05));
    border: 1px solid rgba(127, 216, 207, 0.22);
    border-left: 2px solid #7FD8CF;
    border-radius: 12px;
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.25), inset 0 0 26px rgba(60, 153, 146, 0.06);
    overflow: hidden;
}
section[data-testid="stSidebar"] [data-testid="stAlert"] p,
section[data-testid="stSidebar"] [data-testid="stAlert"] div {
    color: #CDEFEA;
    font-size: 0.82rem;
    line-height: 1.5;
}
section[data-testid="stSidebar"] [data-testid="stAlert"]::before {
    content: "";
    position: absolute;
    top: 15px; right: 15px;
    width: 8px; height: 8px;
    border-radius: 50%;
    background: #7FD8CF;
    box-shadow: 0 0 0 0 rgba(127, 216, 207, 0.6);
    animation: livePulse 2.2s ease-out infinite;
}
@keyframes livePulse {
    0%   { box-shadow: 0 0 0 0 rgba(127, 216, 207, 0.55); }
    70%  { box-shadow: 0 0 0 9px rgba(127, 216, 207, 0); }
    100% { box-shadow: 0 0 0 0 rgba(127, 216, 207, 0); }
}

/* caption — divided footnote */
section[data-testid="stSidebar"] .stCaption,
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
    margin-top: 0.95rem;
    padding-top: 0.85rem;
    border-top: 1px solid rgba(255, 255, 255, 0.07);
    color: #8FB0AC;
    font-size: 0.74rem;
    line-height: 1.55;
}

/* primary CTA — spacing, depth, hover shimmer */
section[data-testid="stSidebar"] .stButton { margin-top: 1.35rem; }
section[data-testid="stSidebar"] .stButton > button {
    position: relative;
    overflow: hidden;
    padding: 0.82rem 1rem;
    font-size: 0.95rem;
    font-weight: 600;
    letter-spacing: 0.02em;
    border-radius: 12px;
    background: linear-gradient(135deg, #3C9992, #23635e);
    border: 1px solid rgba(127, 216, 207, 0.4);
    box-shadow: 0 6px 20px rgba(60, 153, 146, 0.3),
                inset 0 1px 0 rgba(255, 255, 255, 0.12);
}
section[data-testid="stSidebar"] .stButton > button::after {
    content: "";
    position: absolute;
    inset: 0;
    background: linear-gradient(120deg,
        transparent 30%, rgba(255, 255, 255, 0.2) 50%, transparent 70%);
    transform: translateX(-130%);
    transition: transform 0.6s ease;
    pointer-events: none;
}
section[data-testid="stSidebar"] .stButton > button:hover {
    box-shadow: 0 10px 30px rgba(60, 153, 146, 0.45),
                0 0 22px rgba(127, 216, 207, 0.3),
                inset 0 1px 0 rgba(255, 255, 255, 0.18);
}
section[data-testid="stSidebar"] .stButton > button:hover::after {
    transform: translateX(130%);
}
section[data-testid="stSidebar"] .stButton > button:disabled {
    opacity: 0.45;
    box-shadow: none;
}
section[data-testid="stSidebar"] .stButton > button:disabled::after { display: none; }

/* collapse / expand control — glass chip */
section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] button,
button[kind="header"][data-testid="collapsedControl"] {
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(127, 216, 207, 0.18);
    border-radius: 9px;
}

/* ------------------------------------------------------------------ */
/* Buttons (global, outside sidebar)                                  */
/* ------------------------------------------------------------------ */
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

/* ------------------------------------------------------------------ */
/* Tabs                                                               */
/* ------------------------------------------------------------------ */
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

/* ------------------------------------------------------------------ */
/* Metrics                                                            */
/* ------------------------------------------------------------------ */
[data-testid="stMetric"] {
    background: var(--glass-bg);
    border: 1px solid var(--glass-border);
    border-radius: var(--radius-md);
    padding: 0.9rem 1rem;
}
[data-testid="stMetricLabel"] { color: var(--text-secondary); }
[data-testid="stMetricValue"] {
    color: var(--accent);
    text-shadow: 0 0 12px rgba(60, 153, 146, 0.35);
}

/* ------------------------------------------------------------------ */
/* Code blocks                                                        */
/* ------------------------------------------------------------------ */
.stCodeBlock, pre {
    border: 1px solid var(--glass-border) !important;
    border-radius: var(--radius-md) !important;
}

/* ------------------------------------------------------------------ */
/* Expander                                                           */
/* ------------------------------------------------------------------ */
.streamlit-expanderHeader {
    background: var(--glass-bg);
    border-radius: var(--radius-md);
    border: 1px solid var(--glass-border);
}

/* ------------------------------------------------------------------ */
/* Text areas / inputs (global)                                       */
/* ------------------------------------------------------------------ */
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

/* ================================================================== */
/* Radiant typography glow                                            */
/* (placed last so hero / sidebar overrides win on equal specificity) */
/* ================================================================== */

/* body markdown headers / subheaders — subtle radiant edge */
.stMarkdown h1, .stMarkdown h2, .stMarkdown h3,
[data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3 {
    text-shadow:
        0 0 1px rgba(127, 216, 207, 0.3),
        0 0 12px rgba(60, 153, 146, 0.22),
        0 0 26px rgba(60, 153, 146, 0.12);
}

/* hero sublines — soft static halo */
.glass-hero p {
    text-shadow:
        0 0 10px rgba(127, 216, 207, 0.18),
        0 0 22px rgba(60, 153, 146, 0.1);
}

/* hero headline — explicit-color halo (works on gradient-clipped text)
   plus a slow breathing cycle on the shadow only */
.glass-hero h1 {
    text-shadow:
        0 0 1px rgba(127, 216, 207, 0.55),
        0 0 14px rgba(60, 153, 146, 0.5),
        0 0 30px rgba(60, 153, 146, 0.32),
        0 0 56px rgba(60, 153, 146, 0.18);
    animation: heroGlow 5s ease-in-out infinite;
}
@keyframes heroGlow {
    0%, 100% {
        text-shadow:
            0 0 1px rgba(127, 216, 207, 0.5),
            0 0 12px rgba(60, 153, 146, 0.42),
            0 0 26px rgba(60, 153, 146, 0.26),
            0 0 48px rgba(60, 153, 146, 0.14);
    }
    50% {
        text-shadow:
            0 0 2px rgba(127, 216, 207, 0.72),
            0 0 18px rgba(60, 153, 146, 0.6),
            0 0 38px rgba(60, 153, 146, 0.4),
            0 0 72px rgba(60, 153, 146, 0.24);
    }
}
</style>
"""


def inject_glassmorphism_css() -> None:
    st.markdown(GLASSMORPHISM_CSS, unsafe_allow_html=True)