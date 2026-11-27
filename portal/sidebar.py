import html as _html
import streamlit as st
from health_parser import (
    build_sample_master_bytes,
    build_sample_accounts_master_bytes,
)
from portal.backend import is_admin_user
from portal.state import DEFAULTS
from portal.sidebar_modes import (
    qp_get,
    qp_set,
    render_mode3_panels,
    render_mode2_panel,
)
from portal.sidebar_masters import (
    render_client_master_panel,
    render_accounts_master_panel,
    render_renewal_list_panel,
)
from portal.sidebar_config import (
    render_commission_panel,
    render_custom_columns_panel,
)

_FROZEN_SIDEBAR_USER_CSS = """
<style>
section[data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.pm-sb-user-wrap),
section[data-testid="stSidebar"] .element-container:has(.pm-sb-user-wrap) {
    position: sticky !important;
    top: 0 !important;
    z-index: 990 !important;
    background: var(--secondary-background-color, #f0f2f6) !important;
}
.pm-sb-user-wrap {
    position: relative;
    background: var(--secondary-background-color, #f0f2f6);
    padding: 6px 0 8px 0;
    margin-bottom: 4px;
}
.pm-sb-user-wrap::before {
    content: "";
    position: absolute;
    left: -1.5rem;
    right: -1.5rem;
    top: -2.5rem;
    height: 2.5rem;
    background: var(--secondary-background-color, #f0f2f6);
    pointer-events: none;
}
.pm-sb-user-card {
    background: #e8f5ee;
    border: 1px solid #bbf7d0;
    border-radius: 0.5rem;
    padding: 10px 12px;
    color: #14532d;
    font-size: 0.875rem;
    line-height: 1.5;
    box-shadow: 0 3px 8px -4px rgba(15, 23, 42, 0.16);
}
.pm-sb-user-name {
    font-weight: 700;
    word-break: break-word;
}
.pm-sb-user-email {
    margin-top: 2px;
    font-size: 0.8rem;
    word-break: break-all;
}
.pm-sb-user-email code {
    background: rgba(255, 255, 255, 0.72);
    color: #0f766e;
    padding: 1px 5px;
    border-radius: 4px;
    font-size: 0.78rem;
}
.pm-sb-user-exp {
    margin-top: 3px;
    font-size: 0.84rem;
}
</style>
"""


def _render_frozen_user_card():
    display_user = _html.escape(str(st.session_state.user_name or st.session_state.user_id or ""))
    raw_email = str(st.session_state.user_email or "").strip()
    expiry_txt = _html.escape(str(st.session_state.expiry or ""))
    email_html = (
        f"<div class='pm-sb-user-email'>📧 <code>{_html.escape(raw_email)}</code></div>"
        if raw_email
        else ""
    )
    st.markdown(_FROZEN_SIDEBAR_USER_CSS, unsafe_allow_html=True)
    st.markdown(
        "<div class='pm-sb-user-wrap'>"
        "  <div class='pm-sb-user-card'>"
        f"    <div class='pm-sb-user-name'>👤 {display_user}</div>"
        f"    {email_html}"
        f"    <div class='pm-sb-user-exp'>📅 Valid Till: <strong>{expiry_txt}</strong></div>"
        "  </div>"
        "</div>",
        unsafe_allow_html=True,
    )


def render_sidebar(active_headers, is_custom_cols, google_configured):
    mode2_target_type = "google_sheet"

    with st.sidebar:
        _render_frozen_user_card()

        mode_options = [
            "Mode 1: Cloud Portal (Excel Download)",
            "Mode 2: Fixed Google Sheet (Upload)",
            "Mode 3: Drive Folder + Drive Excel (.xlsx)",
        ]
        mode_codes = ["m1", "m2", "m3"]
        if is_admin_user():
            mode_options.append("🐞 Bugging Mode (Preview Only)")
            mode_codes.append("bug")

        saved_mode_code = qp_get("mode", "").strip().lower()
        if saved_mode_code in mode_codes:
            default_mode_idx = mode_codes.index(saved_mode_code)
        else:
            default_mode_idx = (
                2 if (st.session_state.health_folder_url or st.session_state.mode3_excel_url)
                else (1 if (st.session_state.fixed_sheet_url or st.session_state.local_excel_path) else 0)
            )

        working_mode = st.radio(
            "⚙️ Working Mode",
            mode_options,
            index=default_mode_idx,
            key="sb_working_mode_radio",
        )
        qp_set("mode", mode_codes[mode_options.index(working_mode)])

        is_mode1 = working_mode.startswith("Mode 1")
        is_mode2 = working_mode.startswith("Mode 2")
        is_mode3 = working_mode.startswith("Mode 3")
        is_bugging = working_mode.startswith("🐞") and is_admin_user()
        is_direct_sheet = is_mode2 or is_mode3

        policy_category = st.selectbox(
            "📂 Module / Policy Type",
            [
                "Health Insurance",
                "Motor Insurance (Coming Soon)",
                "SME Insurance (Coming Soon)",
                "LIC Due Reminders (Coming Soon)",
                "SME Renewal Messages (Coming Soon)",
                "Client Birthday Wishes (Coming Soon)",
            ],
        )
        st.divider()

        # Mode-specific panels (Mode 3 / Bugging Mode / Mode 2)
        if is_mode3 or is_bugging:
            render_mode3_panels(is_mode3, is_bugging)
        if is_mode2:
            mode2_target_type = render_mode2_panel()

        # Master data & folder panels
        m_count, manual_master_file = render_client_master_panel()
        manual_acc_files = render_accounts_master_panel()
        render_renewal_list_panel()

        # Commission & Sheet Columns configuration panels
        render_commission_panel()
        render_custom_columns_panel(
            active_headers,
            is_custom_cols,
            is_mode3,
            is_bugging,
            is_direct_sheet,
            mode2_target_type,
        )

        st.divider()
        st.download_button(
            "📋 Sample Client Master",
            data=build_sample_master_bytes(),
            file_name="Sample_Client_Master.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
        st.download_button(
            "🏦 Sample Accounts Master",
            data=build_sample_accounts_master_bytes(),
            file_name="Sample_Accounts_Master.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
        if st.button("🚪 Sign Out", use_container_width=True):
            was_google = st.session_state.auth_method == "google"
            for k, v in DEFAULTS.items():
                st.session_state[k] = v.copy() if isinstance(v, (dict, list)) else v
            st.session_state.pop("last_results", None)
            st.session_state.pop("active_entry_job", None)
            try:
                st.query_params.clear()
            except Exception:
                pass
            if was_google and google_configured:
                st.logout()
            else:
                st.rerun()

    return {
        "is_mode1": is_mode1,
        "is_mode2": is_mode2,
        "is_mode3": is_mode3,
        "is_bugging": is_bugging,
        "is_direct_sheet": is_direct_sheet,
        "policy_category": policy_category,
        "mode2_target_type": mode2_target_type,
        "manual_master_file": manual_master_file,
        "manual_acc_files": manual_acc_files,
        "m_count": m_count,
    }
