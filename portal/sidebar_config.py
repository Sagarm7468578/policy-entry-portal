import re
import streamlit as st
from health_parser import (
    OUTPUT_COLUMNS,
    ALL_SYSTEM_FIELDS,
    normalize_custom_columns_spec,
    spec_to_multiline,
)
from portal.backend import (
    save_user_sheet_settings,
    fetch_headers_from_drive_target,
)

COMMISSION_RATE_OPTIONS = [str(r) for r in range(5, 26)]


def _norm_rate_opt(raw_val, default_str):
    digits = re.sub(r"[^0-9]", "", str(raw_val or ""))
    return digits if digits in COMMISSION_RATE_OPTIONS else default_str


def render_commission_panel():
    """Renders age-based Share / Commission % configuration panel (5% to 25%)."""
    cur_u60 = _norm_rate_opt(st.session_state.health_share_under60, "12")
    cur_p60 = _norm_rate_opt(st.session_state.health_share_60plus, "8")
    with st.expander(f"💰 Share / Commission ({cur_u60}% / {cur_p60}%)", expanded=False):
        st.caption(
            "Configure age-based Health commission rates (5%–25%).  \n"
            "Auto-fills **Share %** from DOB age and calculates **Share** = `Premium × Share %`."
        )
        sel_u60 = st.selectbox(
            "Age Below 60 Commission %",
            options=COMMISSION_RATE_OPTIONS,
            index=COMMISSION_RATE_OPTIONS.index(cur_u60),
            format_func=lambda x: f"{x}%",
            key="sb_share_under60",
        )
        sel_p60 = st.selectbox(
            "Age 60+ Commission %",
            options=COMMISSION_RATE_OPTIONS,
            index=COMMISSION_RATE_OPTIONS.index(cur_p60),
            format_func=lambda x: f"{x}%",
            key="sb_share_60plus",
        )
        if st.button("💾 Save Commission Rates", type="primary", use_container_width=True, key="btn_save_share_rates"):
            with st.spinner("Saving commission rates..."):
                s_res = save_user_sheet_settings(
                    st.session_state.user_id,
                    health_share_under60=sel_u60,
                    health_share_60plus=sel_p60,
                )
            if s_res.get("success"):
                st.session_state.health_share_under60 = sel_u60
                st.session_state.health_share_60plus = sel_p60
                st.success(f"Saved: Below 60 = {sel_u60}% | 60+ = {sel_p60}%")
                st.rerun()
            else:
                st.error(s_res.get("message", "Failed to save commission rates."))


def render_custom_columns_panel(active_headers, is_custom_cols, is_mode3, is_bugging, is_direct_sheet, mode2_target_type):
    """Renders Custom Sheet Columns editor, header importer, and available auto-fill fields reference."""
    col_badge = f"Custom: {len(active_headers)}" if is_custom_cols else f"Default: {len(OUTPUT_COLUMNS)}"
    with st.expander(f"🛠️ Sheet Columns ({col_badge})", expanded=False):
        st.caption(
            "Enter one column per line in exact order.  \n"
            "• Auto-fill fields: Client Name, Policy Number, Occupation, Accounts, Share, Share %, PYP premium, etc.  \n"
            "• Blank/Manual column: Enter any custom column name (e.g. `Mail`, `Print`, `Folder`)  \n"
            "• Rename header: `Client Name => Insured Name`"
        )
        import_src_url = st.session_state.mode3_excel_url if (is_mode3 or is_bugging) else st.session_state.fixed_sheet_url
        import_src_tab = st.session_state.mode3_excel_tab if (is_mode3 or is_bugging) else st.session_state.fixed_sheet_tab
        if (is_direct_sheet or is_bugging) and mode2_target_type == "google_sheet" and import_src_url:
            if st.button("📥 Import Headers from Linked Sheet/Excel", use_container_width=True, key="import_sheet_hdrs"):
                with st.spinner("Reading Row 1 headers..."):
                    imp_hdrs, imp_err = fetch_headers_from_drive_target(import_src_url, import_src_tab)
                if imp_hdrs:
                    imported_spec = normalize_custom_columns_spec("\n".join(imp_hdrs))
                    s_res = save_user_sheet_settings(st.session_state.user_id, health_custom_columns=imported_spec)
                    if s_res.get("success"):
                        st.session_state.health_custom_columns = imported_spec
                        st.session_state.col_editor_key += 1
                        st.rerun()
                    else:
                        st.error(s_res.get("message", "Failed to save columns."))
                else:
                    st.warning(imp_err or "Row 1 is empty — paste your columns manually below and click Save.")

        cols_text = st.text_area(
            "Custom Columns (1 per line)",
            value=spec_to_multiline(st.session_state.health_custom_columns),
            height=240,
            key=f"custom_cols_textarea_{st.session_state.col_editor_key}",
        )
        cc1, cc2 = st.columns(2)
        with cc1:
            if st.button("💾 Save", type="primary", use_container_width=True, key="save_custom_cols"):
                norm_spec = normalize_custom_columns_spec(cols_text)
                with st.spinner("Saving column layout..."):
                    s_res = save_user_sheet_settings(st.session_state.user_id, health_custom_columns=norm_spec)
                if s_res.get("success"):
                    st.session_state.health_custom_columns = norm_spec
                    st.session_state.col_editor_key += 1
                    st.rerun()
                else:
                    st.error(s_res.get("message", "Failed to save columns."))
        with cc2:
            if st.button("🔄 Reset", use_container_width=True, key="reset_custom_cols"):
                with st.spinner("Resetting to default columns..."):
                    s_res = save_user_sheet_settings(st.session_state.user_id, health_custom_columns="")
                if s_res.get("success"):
                    st.session_state.health_custom_columns = ""
                    st.session_state.col_editor_key += 1
                    st.rerun()
                else:
                    st.error(s_res.get("message", "Failed to reset columns."))
        with st.popover("📋 Available Auto-Fill Fields", use_container_width=True):
            st.write(", ".join(ALL_SYSTEM_FIELDS))
