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

/* Frosted top Streamlit bar blended into theme */
header[data-testid="stHeader"] {
    background: rgba(248, 250, 252, 0.94) !important;
    backdrop-filter: blur(10px) !important;
}

/* Refined Sidebar Gradient + Compact Top Spacing */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #f8fafc 0%, #eef2f7 100%) !important;
    border-right: 1px solid #dbe3ee !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
    padding-top: 1.4rem !important;
}

/* Frozen Main Header — zero top clipping + colorful shield emoji + gradient brand text */
[data-testid="stMainBlockContainer"],
.block-container {
    padding-top: 3.7rem !important;
}
[data-testid="stElementContainer"]:has(.pm-sticky-header),
.element-container:has(.pm-sticky-header) {
    position: sticky !important;
    top: 3.55rem !important;
    z-index: 990 !important;
    background: transparent !important;
}
.pm-sticky-header {
    background: rgba(255, 255, 255, 0.95) !important;
    backdrop-filter: blur(12px) !important;
    padding: 10px 16px 12px 16px !important;
    border: 1px solid #dbe4f0 !important;
    border-left: 4px solid #1d4ed8 !important;
    border-radius: 12px !important;
    box-shadow: 0 6px 18px -8px rgba(15, 23, 42, 0.14) !important;
}
.pm-sticky-header::before {
    background: rgba(248, 250, 252, 0.96) !important;
    top: -3.6rem !important;
    height: 3.6rem !important;
}
.pm-title {
    display: flex;
    align-items: center;
    gap: 8px;
}
.pm-title-icon {
    font-size: 1.9rem;
    line-height: 1;
    -webkit-text-fill-color: initial !important;
}
.pm-title-text {
    background: linear-gradient(90deg, #0f172a 0%, #1d4ed8 65%, #0f766e 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

/* Frozen Sidebar User Card blended cleanly */
section[data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.pm-sb-user-wrap),
section[data-testid="stSidebar"] .element-container:has(.pm-sb-user-wrap),
.pm-sb-user-wrap,
.pm-sb-user-wrap::before {
    background: #f8fafc !important;
}

/* Elevated White Cards for Expanders, Metrics, Alerts & DataFrames */
[data-testid="stExpander"] {
    background: rgba(255, 255, 255, 0.95) !important;
    border: 1px solid #dce4ef !important;
    border-radius: 12px !important;
    box-shadow: 0 2px 10px -4px rgba(15, 23, 42, 0.08) !important;
}
[data-testid="stMetric"] {
    background: rgba(255, 255, 255, 0.96) !important;
    border: 1px solid #dbe4f0 !important;
    border-radius: 12px !important;
    padding: 12px 16px !important;
    box-shadow: 0 2px 8px -3px rgba(15, 23, 42, 0.07) !important;
}
[data-testid="stAlert"] {
    border-radius: 10px !important;
}
[data-testid="stDataFrame"] {
    border-radius: 10px !important;
    overflow: hidden !important;
    box-shadow: 0 2px 10px -4px rgba(15, 23, 42, 0.08) !important;
}

/* Crisp Modern Buttons (Primary Gradient + Crisp White Secondary) */
.stButton > button,
.stDownloadButton > button,
.stLinkButton > a {
    border-radius: 9px !important;
    font-weight: 600 !important;
    transition: transform 0.12s ease, box-shadow 0.15s ease, border-color 0.15s ease !important;
}
.stButton > button[kind="secondary"],
.stDownloadButton > button,
.stLinkButton > a {
    background: #ffffff !important;
    border: 1px solid #cbd5e1 !important;
    box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06) !important;
}
.stButton > button[kind="secondary"]:hover,
.stDownloadButton > button:hover,
.stLinkButton > a:hover {
    border-color: #64748b !important;
    box-shadow: 0 3px 8px -2px rgba(15, 23, 42, 0.12) !important;
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
