import streamlit as st

_SAAS_THEME_CSS = """
<style>
/* Soft FinTech / InsurTech Mesh Background */
[data-testid="stAppViewContainer"] {
    background:
        radial-gradient(circle at 12% 14%, rgba(59, 130, 246, 0.08) 0%, transparent 42%),
        radial-gradient(circle at 88% 18%, rgba(14, 165, 233, 0.08) 0%, transparent 40%),
        radial-gradient(circle at 75% 88%, rgba(16, 185, 129, 0.06) 0%, transparent 44%),
        linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%) !important;
    background-attachment: fixed !important;
}

/* Transparent top Streamlit bar blended into theme */
header[data-testid="stHeader"] {
    background: rgba(248, 250, 252, 0.92) !important;
    backdrop-filter: blur(10px) !important;
}

/* Refined Sidebar Gradient + Crisp Border */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #f8fafc 0%, #eef2f7 100%) !important;
    border-right: 1px solid #dbe3ee !important;
}

/* Match Frozen Main Header & Sidebar User Card to Soft Theme */
[data-testid="stElementContainer"]:has(.pm-sticky-header),
.element-container:has(.pm-sticky-header) {
    background: rgba(248, 250, 252, 0.94) !important;
    backdrop-filter: blur(10px) !important;
    border-radius: 0 0 12px 12px !important;
}
.pm-sticky-header {
    background: rgba(248, 250, 252, 0.94) !important;
    padding: 8px 14px 12px 14px !important;
    border: 1px solid #e2e8f0 !important;
    border-top: none !important;
    border-radius: 0 0 12px 12px !important;
    box-shadow: 0 6px 18px -8px rgba(15, 23, 42, 0.14) !important;
}
.pm-sticky-header::before {
    background: rgba(248, 250, 252, 0.96) !important;
}
.pm-title {
    background: linear-gradient(90deg, #0f172a 0%, #1d4ed8 65%, #0f766e 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}
section[data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.pm-sb-user-wrap),
section[data-testid="stSidebar"] .element-container:has(.pm-sb-user-wrap),
.pm-sb-user-wrap,
.pm-sb-user-wrap::before {
    background: #f8fafc !important;
}

/* Elevated White Cards for Expanders, Metrics & DataFrames */
[data-testid="stExpander"] {
    background: rgba(255, 255, 255, 0.92) !important;
    border: 1px solid #dce4ef !important;
    border-radius: 12px !important;
    box-shadow: 0 2px 10px -4px rgba(15, 23, 42, 0.08) !important;
}
[data-testid="stMetric"] {
    background: rgba(255, 255, 255, 0.94) !important;
    border: 1px solid #e2e8f0 !important;
    border-radius: 12px !important;
    padding: 12px 16px !important;
    box-shadow: 0 2px 8px -3px rgba(15, 23, 42, 0.07) !important;
}
[data-testid="stDataFrame"] {
    border-radius: 10px !important;
    overflow: hidden !important;
    box-shadow: 0 2px 10px -4px rgba(15, 23, 42, 0.08) !important;
}

/* Crisp Modern Buttons */
.stButton > button,
.stDownloadButton > button,
.stLinkButton > a {
    border-radius: 9px !important;
    font-weight: 600 !important;
    transition: transform 0.12s ease, box-shadow 0.15s ease !important;
}
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #1d4ed8 0%, #0f766e 100%) !important;
    border: none !important;
    box-shadow: 0 4px 12px -3px rgba(29, 78, 216, 0.4) !important;
}
.stButton > button[kind="primary"]:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 16px -3px rgba(29, 78, 216, 0.5) !important;
}
</style>
"""


def apply_portal_theme():
    """Applies the subtle FinTech SaaS visual theme (soft mesh background + crisp white cards)."""
    st.markdown(_SAAS_THEME_CSS, unsafe_allow_html=True)
