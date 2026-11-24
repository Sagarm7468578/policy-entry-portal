import streamlit as st
from health_parser import get_custom_schema_info
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

if not st.session_state.logged_in:
    render_login_screen(google_configured, google_logged_in, g_email)
else:
    ensure_settings_loaded()
    active_schema = get_custom_schema_info(st.session_state.health_custom_columns)
    active_headers = active_schema["headers"]
    is_custom_cols = bool(st.session_state.health_custom_columns.strip())

    ctx = render_sidebar(active_headers, is_custom_cols, google_configured)
    render_workspace(ctx, active_headers, is_custom_cols)
