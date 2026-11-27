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


def render_sidebar(active_headers, is_custom_cols, google_configured):
    mode2_target_type = "google_sheet"

    with st.sidebar:
        display_user = st.session_state.user_name or st.session_state.user_id
        email_line = f"  \n📧 `{st.session_state.user_email}`" if st.session_state.user_email else ""
        st.success(f"👤 **{display_user}**{email_line}  \n📅 Valid Till: **{st.session_state.expiry}**")

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
