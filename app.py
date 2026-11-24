import streamlit as st
from health_parser import get_custom_schema_info
from portal.backend import is_admin_user
from portal.state import (
    init_session_state,
    handle_auto_google_login,
    render_login_screen,
    ensure_settings_loaded,
)
from portal.sidebar import render_sidebar
from portal.workspace import render_workspace

st.set_page_config(page_title="Policy Entry Portal", page_icon="📄", layout="wide")

init_session_state()
google_configured, google_logged_in, g_email = handle_auto_google_login()

# Clients ke liye top-right Share/GitHub/Menu aur bottom Streamlit/Manage chrome hide karein (Admin ko sab dikhega)
if not is_admin_user():
    st.markdown(
        """
        <style>
            #MainMenu,
            footer,
            [data-testid="stToolbarActions"],
            [data-testid="stAppDeployButton"],
            [data-testid="stMainMenu"],
            [data-testid="manage-app-button"],
            [class*="viewerBadge"],
            .stActionButton,
            .stDeployButton {
                display: none !important;
                visibility: hidden !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )

if not st.session_state.logged_in:
    render_login_screen(google_configured, google_logged_in, g_email)
else:
    ensure_settings_loaded()
    active_schema = get_custom_schema_info(st.session_state.health_custom_columns)
    active_headers = active_schema["headers"]
    is_custom_cols = bool(st.session_state.health_custom_columns.strip())

    ctx = render_sidebar(active_headers, is_custom_cols, google_configured)
    render_workspace(ctx, active_headers, is_custom_cols)
