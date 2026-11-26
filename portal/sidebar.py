import os
import re
import pandas as pd
import streamlit as st
from health_parser import (
    OUTPUT_COLUMNS,
    ALL_SYSTEM_FIELDS,
    normalize_custom_columns_spec,
    spec_to_multiline,
    build_sample_master_bytes,
    build_sample_accounts_master_bytes,
)
from portal.backend import (
    IS_CLOUD,
    call_backend,
    save_user_sheet_settings,
    fetch_linked_client_master,
    fetch_linked_accounts_master,
    fetch_headers_from_drive_target,
    save_local_excel_path,
)
from portal.state import DEFAULTS

COMMISSION_RATE_OPTIONS = [str(r) for r in range(5, 26)]


def _norm_rate_opt(raw_val, default_str):
    digits = re.sub(r"[^0-9]", "", str(raw_val or ""))
    return digits if digits in COMMISSION_RATE_OPTIONS else default_str


def _render_category_folder_panel(title, caption, folder_specs, expanded=False, reset_health_scan=False, footer_tip=""):
    linked_cnt = sum(bool(st.session_state[u_key]) for _, u_key, _ in folder_specs)
    badge = f"✅ {linked_cnt}/3 Linked" if linked_cnt > 0 else "⚪ Not Linked"
    with st.expander(f"{title} ({badge})", expanded=expanded):
        st.caption(caption)
        tabs = st.tabs(["🏥 Health", "🚗 Motor", "🏢 SME"])
        for tab_ui, (cat_label, url_key, name_key) in zip(tabs, folder_specs):
            with tab_ui:
                curr_url, curr_name = st.session_state[url_key], st.session_state[name_key]
                if curr_url:
                    disp_nm = f"**{curr_name}**  \n" if curr_name else ""
                    st.success(f"{disp_nm}✅ {cat_label} Folder Linked")
                    if curr_url.startswith("http"):
                        st.link_button(f"🔗 Open {cat_label} Folder", curr_url, use_container_width=True)
                    if st.button(f"🔓 Unlink {cat_label}", use_container_width=True, key=f"unlink_{url_key}"):
                        with st.spinner("Unlinking folder..."):
                            u_res = save_user_sheet_settings(st.session_state.user_id, **{url_key: ""})
                        if u_res.get("success"):
                            st.session_state[url_key] = st.session_state[name_key] = ""
                            if reset_health_scan and url_key == "health_folder_url":
                                st.session_state.update({"drive_scan_info": None, "drive_last_scan_key": "", "drive_selected_year": "", "drive_selected_month": ""})
                            st.rerun()
                        else:
                            st.error(u_res.get("message", "Failed to unlink folder."))
                else:
                    f_inp = st.text_input(f"{cat_label} Drive Folder Link", placeholder="https://drive.google.com/drive/folders/...", key=f"inp_{url_key}")
                    if st.button(f"🔗 Link {cat_label} Folder", type="primary", use_container_width=True, key=f"btn_{url_key}"):
                        clean_f = f_inp.strip()
                        if not clean_f:
                            st.warning("Please paste a valid Google Drive folder link.")
                        else:
                            with st.spinner("Verifying and linking folder..."):
                                v_res = call_backend({"action": "verify_drive_folder", "folder_url": clean_f})
                                if not v_res.get("success"):
                                    st.error(v_res.get("message", "Could not access folder. Ensure Viewer/Editor sharing permission is enabled."))
                                else:
                                    s_res = save_user_sheet_settings(st.session_state.user_id, **{url_key: clean_f})
                                    if s_res.get("success"):
                                        st.session_state[url_key], st.session_state[name_key] = clean_f, v_res.get("folder_name", "")
                                        if reset_health_scan and url_key == "health_folder_url":
                                            st.session_state.update({"drive_scan_info": None, "drive_last_scan_key": "", "drive_selected_year": "", "drive_selected_month": ""})
                                        st.rerun()
                                    else:
                                        st.error(s_res.get("message", "Failed to save folder link."))
                    if footer_tip:
                        st.caption(footer_tip)


def render_sidebar(active_headers, is_custom_cols, google_configured):
    mode2_target_type = "google_sheet"
    manual_master_file = None
    manual_acc_files = {"health": None, "motor": None, "sme": None}

    with st.sidebar:
        display_user = st.session_state.user_name or st.session_state.user_id
        email_line = f"  \n📧 `{st.session_state.user_email}`" if st.session_state.user_email else ""
        st.success(f"👤 **{display_user}**{email_line}  \n📅 Valid Till: **{st.session_state.expiry}**")

        default_mode_idx = 2 if (st.session_state.health_folder_url or st.session_state.mode3_excel_url) else (1 if (st.session_state.fixed_sheet_url or st.session_state.local_excel_path) else 0)
        working_mode = st.radio(
            "⚙️ Working Mode",
            ["Mode 1: Cloud Portal (Excel Download)", "Mode 2: Fixed Google Sheet (Upload)", "Mode 3: Drive Folder + Drive Excel (.xlsx)"],
            index=default_mode_idx,
        )
        is_mode1, is_mode2, is_mode3 = working_mode.startswith("Mode 1"), working_mode.startswith("Mode 2"), working_mode.startswith("Mode 3")
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

        # 1. MODE 3: DRIVE EXCEL + AUTO-FOLDERS
        if is_mode3:
            is_m3_excel_linked = bool(st.session_state.mode3_excel_url)
            with st.expander(f"📊 Mode 3 Drive Excel ({'✅ Linked' if is_m3_excel_linked else '⚪ Not Linked'})", expanded=not is_m3_excel_linked):
                if is_m3_excel_linked:
                    ex_title = f"**{st.session_state.mode3_excel_name}**  \n" if st.session_state.mode3_excel_name else ""
                    st.success(f"{ex_title}📑 Tab: `{st.session_state.mode3_excel_tab or '1st Tab (Auto)'}`  \nDirect in-place `.xlsx` auto-save active")
                    if st.session_state.mode3_excel_url.startswith("http"):
                        st.link_button("🔗 Open Drive Excel File", st.session_state.mode3_excel_url, use_container_width=True)
                    if st.button("🔓 Unlink Drive Excel", use_container_width=True, key="unlink_m3_excel"):
                        with st.spinner("Unlinking Drive Excel..."):
                            u_res = save_user_sheet_settings(st.session_state.user_id, mode3_excel_url="", mode3_excel_tab="")
                        if u_res.get("success"):
                            st.session_state.mode3_excel_url = st.session_state.mode3_excel_tab = st.session_state.mode3_excel_name = ""
                            st.rerun()
                        else:
                            st.error(u_res.get("message", "Failed to unlink file."))
                else:
                    m3_url_inp = st.text_input("Google Drive Excel (.xlsx) Link", placeholder="https://drive.google.com/file/d/.../view", key="m3_excel_url_input")
                    m3_tab_inp = st.text_input("Excel Sheet Tab (Blank = 1st Tab)", value="", key="m3_excel_tab_input")
                    if st.button("🔗 Link Drive Excel Permanently", type="primary", use_container_width=True, key="btn_link_m3_excel"):
                        clean_u, clean_t = m3_url_inp.strip(), m3_tab_inp.strip()
                        if not clean_u:
                            st.warning("Please paste the Share Link of your Google Drive `.xlsx` Excel file.")
                        else:
                            with st.spinner("Verifying and linking Google Drive Excel..."):
                                v_res = call_backend({"action": "verify_sheet", "sheet_url": clean_u})
                                if not v_res.get("success"):
                                    st.error(v_res.get("message", "Could not access Excel file."))
                                else:
                                    s_res = save_user_sheet_settings(st.session_state.user_id, mode3_excel_url=clean_u, mode3_excel_tab=clean_t)
                                    if s_res.get("success"):
                                        st.session_state.mode3_excel_url, st.session_state.mode3_excel_tab, st.session_state.mode3_excel_name = clean_u, clean_t, v_res.get("sheet_name", "")
                                        st.rerun()
                                    else:
                                        st.error(s_res.get("message", "Failed to save link."))
                    st.caption("💡 In Google Drive, right-click the `.xlsx` file → Share (Editor) → Copy link and paste above.")

            _render_category_folder_panel(
                title="📁 Drive Auto-Folders",
                caption="Link your main parent folder (`MEDICLAIM` / `MOTOR` / `SME`) or a direct month folder once.",
                folder_specs=[
                    ("Health", "health_folder_url", "health_folder_name"),
                    ("Motor", "motor_folder_url", "motor_folder_name"),
                    ("SME", "sme_folder_url", "sme_folder_name"),
                ],
                expanded=not bool(st.session_state.health_folder_url),
                reset_health_scan=True,
            )

        # 2. MODE 2: POLICY ENTRY SHEET
        if is_mode2:
            is_policy_linked = bool(st.session_state.fixed_sheet_url or (not IS_CLOUD and st.session_state.local_excel_path))
            with st.expander(f"🎯 Policy Entry Sheet ({'✅ Linked' if is_policy_linked else '⚪ Not Linked'})", expanded=not is_policy_linked):
                target_options = ["☁️ Google Sheet / Drive Excel"] if IS_CLOUD else ["💻 Local PC Excel (.xlsx)", "☁️ Google Sheet / Drive Excel"]
                chosen_target = st.radio("Save Destination", target_options, key="sidebar_mode2_target")
                if chosen_target.startswith("💻"):
                    mode2_target_type = "local_excel"
                    if st.session_state.local_excel_path:
                        st.success(f"**Local Excel Linked**  \n`{os.path.basename(st.session_state.local_excel_path)}`  \n📑 Tab: `{st.session_state.local_sheet_name}`")
                        if st.button("🔓 Unlink Excel", use_container_width=True, key="unlink_local_excel"):
                            st.session_state.local_excel_path = ""
                            save_local_excel_path("", "Policy Entries")
                            st.rerun()
                    else:
                        l_path_inp = st.text_input("Fixed Excel Path (.xlsx)", placeholder=r"I:\My Drive\POLICY ENTRY EXCEL\HEALTH.xlsx", key="sb_local_path_input")
                        l_tab_inp = st.text_input("Sheet Tab Name", value="Policy Entries", key="sb_local_tab_input")
                        if st.button("🔗 Link Path", type="primary", use_container_width=True):
                            clean_p = l_path_inp.strip().strip('"')
                            if not clean_p:
                                st.warning("Please enter a valid file path.")
                            else:
                                st.session_state.local_excel_path = clean_p
                                st.session_state.local_sheet_name = l_tab_inp.strip() or "Policy Entries"
                                save_local_excel_path(clean_p, st.session_state.local_sheet_name)
                                st.rerun()
                else:
                    mode2_target_type = "google_sheet"
                    if st.session_state.fixed_sheet_url:
                        title_txt = f"**{st.session_state.fixed_sheet_name}**  \n" if st.session_state.fixed_sheet_name else ""
                        st.success(f"{title_txt}📑 Tab: `{st.session_state.fixed_sheet_tab}`  \nAuto-save active (Zero download)")
                        if st.session_state.fixed_sheet_url.startswith("http"):
                            st.link_button("🔗 Open Policy Sheet", st.session_state.fixed_sheet_url, use_container_width=True)
                        if st.button("🔓 Unlink Policy Sheet", use_container_width=True, key="unlink_policy_gsheet"):
                            with st.spinner("Unlinking Policy Sheet..."):
                                u_res = save_user_sheet_settings(st.session_state.user_id, fixed_sheet_url="", fixed_sheet_tab="Policy Entries")
                            if u_res.get("success"):
                                st.session_state.fixed_sheet_url, st.session_state.fixed_sheet_tab, st.session_state.fixed_sheet_name = "", "Policy Entries", ""
                                st.rerun()
                            else:
                                st.error(u_res.get("message", "Failed to unlink sheet."))
                    else:
                        s_url_inp = st.text_input("Policy Sheet / Drive Excel URL", placeholder="https://docs.google.com/spreadsheets/d/...", key="policy_sheet_url_input")
                        s_tab_inp = st.text_input("Sheet Tab Name", value=st.session_state.fixed_sheet_tab or "Policy Entries", key="policy_sheet_tab_input")
                        if st.button("🔗 Link Policy Sheet", type="primary", use_container_width=True):
                            clean_url, clean_tab = s_url_inp.strip(), s_tab_inp.strip() or "Policy Entries"
                            if not clean_url:
                                st.warning("Please enter a Google Sheet or Drive Excel URL.")
                            else:
                                with st.spinner("Verifying and linking sheet..."):
                                    v_res = call_backend({"action": "verify_sheet", "sheet_url": clean_url})
                                    if not v_res.get("success"):
                                        st.error(v_res.get("message", "Could not access file."))
                                    else:
                                        s_res = save_user_sheet_settings(st.session_state.user_id, fixed_sheet_url=clean_url, fixed_sheet_tab=clean_tab)
                                        if s_res.get("success"):
                                            st.session_state.fixed_sheet_url, st.session_state.fixed_sheet_tab, st.session_state.fixed_sheet_name = clean_url, clean_tab, v_res.get("sheet_name", "")
                                            st.rerun()
                                        else:
                                            st.error(s_res.get("message", "Failed to save link."))
                        st.caption("💡 Share the file with Editor permission before linking.")

        # 3. CLIENT MASTER PANEL
        m_df = st.session_state.linked_master_df
        m_count = len(m_df) if isinstance(m_df, pd.DataFrame) else 0
        is_cm_linked = bool(st.session_state.client_master_url)
        cm_badge = f"✅ {m_count} Clients" if (is_cm_linked and not st.session_state.linked_master_error) else ("⚠️ Error" if is_cm_linked else "⚪ Not Linked")

        with st.expander(f"👥 Client Master ({cm_badge})", expanded=not is_cm_linked):
            if is_cm_linked:
                if st.session_state.linked_master_error:
                    st.error(f"⚠️ {st.session_state.linked_master_error}")
                else:
                    st.success(f"**{st.session_state.client_master_sheet_name or 'Client Master Sheet'}**  \n👥 **{m_count} Clients Loaded**")
                mc1, mc2 = st.columns(2)
                with mc1:
                    if st.button("🔄 Refresh", use_container_width=True, key="refresh_linked_master"):
                        with st.spinner("Refreshing Client Master..."):
                            m_df, m_name, m_err = fetch_linked_client_master(st.session_state.client_master_url, st.session_state.client_master_tab)
                            st.session_state.linked_master_df, st.session_state.client_master_sheet_name, st.session_state.linked_master_error = m_df, m_name, m_err
                        st.rerun()
                with mc2:
                    if st.button("🔓 Unlink", use_container_width=True, key="unlink_client_master"):
                        with st.spinner("Unlinking Client Master..."):
                            u_res = save_user_sheet_settings(st.session_state.user_id, client_master_url="", client_master_tab="")
                        if u_res.get("success"):
                            st.session_state.client_master_url = st.session_state.client_master_tab = st.session_state.client_master_sheet_name = st.session_state.linked_master_error = ""
                            st.session_state.linked_master_df = None
                            st.rerun()
                        else:
                            st.error(u_res.get("message", "Failed to unlink Client Master."))
                if st.session_state.client_master_url.startswith("http"):
                    st.link_button("🔗 Open Client Master", st.session_state.client_master_url, use_container_width=True)
            else:
                cm_tab1, cm_tab2 = st.tabs(["🔗 Google Sheet", "📤 File"])
                with cm_tab1:
                    cm_url_inp = st.text_input("Client Master Sheet URL", placeholder="https://docs.google.com/spreadsheets/d/...", key="cm_url_input")
                    cm_tab_inp = st.text_input("Tab Name (Blank = 1st Tab)", value="", key="cm_tab_input")
                    if st.button("🔗 Link Master Sheet", type="primary", use_container_width=True):
                        clean_cm_url, clean_cm_tab = cm_url_inp.strip(), cm_tab_inp.strip()
                        if not clean_cm_url:
                            st.warning("Please enter the Client Master sheet link.")
                        else:
                            with st.spinner("Verifying and linking Client Master..."):
                                m_df, m_name, m_err = fetch_linked_client_master(clean_cm_url, clean_cm_tab)
                                if m_err:
                                    st.error(m_err)
                                else:
                                    s_res = save_user_sheet_settings(st.session_state.user_id, client_master_url=clean_cm_url, client_master_tab=clean_cm_tab)
                                    if s_res.get("success"):
                                        st.session_state.client_master_url, st.session_state.client_master_tab, st.session_state.client_master_sheet_name, st.session_state.linked_master_df, st.session_state.linked_master_error = clean_cm_url, clean_cm_tab, m_name, m_df, ""
                                        st.rerun()
                                    else:
                                        st.error(s_res.get("message", "Failed to save link."))
                with cm_tab2:
                    manual_master_file = st.file_uploader("Upload Master (.xlsx / .csv)", type=["xlsx", "csv"], key="client_master_uploader")

        # 4. ACCOUNTS MASTER PANEL (HEALTH / MOTOR / SME)
        acc_linked_cnt = sum(bool(st.session_state[f"{ck}_accounts_url"]) for ck in ("health", "motor", "sme"))
        with st.expander(f"🏦 Accounts Master ({f'✅ {acc_linked_cnt}/3 Linked' if acc_linked_cnt else '⚪ Not Linked'})", expanded=False):
            st.caption("Link separate Accounts Master sheets (`Company Name`, `Agency`, `Accounts`) for Health, Motor, and SME.")
            for tab_ui, (cat_label, ck) in zip(st.tabs(["🏥 Health", "🚗 Motor", "🏢 SME"]), [("Health", "health"), ("Motor", "motor"), ("SME", "sme")]):
                with tab_ui:
                    u_key, t_key, n_key, d_key, e_key = f"{ck}_accounts_url", f"{ck}_accounts_tab", f"{ck}_accounts_name", f"{ck}_accounts_df", f"{ck}_accounts_error"
                    curr_url, curr_df, curr_err = st.session_state[u_key], st.session_state[d_key], st.session_state[e_key]
                    if curr_url:
                        if curr_err:
                            st.error(f"⚠️ {curr_err}")
                        else:
                            tab_info = f"  \n📑 Tab: `{st.session_state[t_key]}`" if st.session_state[t_key] else ""
                            st.success(f"**{st.session_state[n_key] or f'{cat_label} Accounts Master'}**{tab_info}  \n🏦 **{len(curr_df) if isinstance(curr_df, pd.DataFrame) else 0} Rules Loaded**")
                        ac1, ac2 = st.columns(2)
                        with ac1:
                            if st.button("🔄 Refresh", use_container_width=True, key=f"refresh_acc_{ck}"):
                                with st.spinner(f"Refreshing {cat_label} Accounts..."):
                                    a_df, a_name, a_err = fetch_linked_accounts_master(curr_url, st.session_state[t_key])
                                    st.session_state[d_key], st.session_state[n_key], st.session_state[e_key] = a_df, a_name, a_err
                                st.rerun()
                        with ac2:
                            if st.button("🔓 Unlink", use_container_width=True, key=f"unlink_acc_{ck}"):
                                with st.spinner("Unlinking..."):
                                    u_res = save_user_sheet_settings(st.session_state.user_id, **{u_key: "", t_key: ""})
                                if u_res.get("success"):
                                    st.session_state[u_key] = st.session_state[t_key] = st.session_state[n_key] = st.session_state[e_key] = ""
                                    st.session_state[d_key] = None
                                    st.rerun()
                                else:
                                    st.error(u_res.get("message", "Failed to unlink."))
                        if curr_url.startswith("http"):
                            st.link_button(f"🔗 Open {cat_label} Accounts", curr_url, use_container_width=True)
                    else:
                        src_t1, src_t2 = st.tabs(["🔗 Sheet / Drive Excel", "📤 File"])
                        with src_t1:
                            a_url_inp = st.text_input(f"{cat_label} Accounts Sheet/Excel URL", placeholder="https://docs.google.com/spreadsheets/d/...", key=f"inp_acc_url_{ck}")
                            a_tab_inp = st.text_input("Tab Name (Blank = 1st Tab)", value="", key=f"inp_acc_tab_{ck}")
                            if st.button(f"🔗 Link {cat_label} Accounts", type="primary", use_container_width=True, key=f"btn_link_acc_{ck}"):
                                clean_au, clean_at = a_url_inp.strip(), a_tab_inp.strip()
                                if not clean_au:
                                    st.warning(f"Please enter the {cat_label} Accounts Master link.")
                                else:
                                    with st.spinner(f"Verifying and linking {cat_label} Accounts Master..."):
                                        a_df, a_name, a_err = fetch_linked_accounts_master(clean_au, clean_at)
                                        if a_err:
                                            st.error(a_err)
                                        else:
                                            s_res = save_user_sheet_settings(st.session_state.user_id, **{u_key: clean_au, t_key: clean_at})
                                            if s_res.get("success"):
                                                st.session_state[u_key], st.session_state[t_key], st.session_state[n_key], st.session_state[d_key], st.session_state[e_key] = clean_au, clean_at, a_name, a_df, ""
                                                st.rerun()
                                            else:
                                                st.error(s_res.get("message", "Failed to save link."))
                        with src_t2:
                            manual_acc_files[ck] = st.file_uploader(f"Upload {cat_label} Accounts (.xlsx / .csv)", type=["xlsx", "csv"], key=f"upload_acc_{ck}")

        # 5. RENEWAL LIST PANEL (HEALTH / MOTOR / SME)
        _render_category_folder_panel(
            title="🔄 Renewal List",
            caption="Link separate Renewal List PDF folders (`GIC RENEWALS/HEALTH` or `2026`).  \nMatched policies auto-fill `PYP premium` and set `OUR RENEWAL` = `YES` (else `NO`).",
            folder_specs=[
                ("Health", "health_renewal_folder_url", "health_renewal_folder_name"),
                ("Motor", "motor_renewal_folder_url", "motor_renewal_folder_name"),
                ("SME", "sme_renewal_folder_url", "sme_renewal_folder_name"),
            ],
            expanded=False,
            footer_tip="💡 Linking the main category folder (e.g. `HEALTH`) auto-detects year subfolders (`2026`, `2027`...).",
        )

        # 6. COMMISSION / SHARE % PANEL (USER-CONFIGURABLE 5% TO 25%)
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

        # 7. CUSTOM SHEET COLUMNS PANEL
        col_badge = f"Custom: {len(active_headers)}" if is_custom_cols else f"Default: {len(OUTPUT_COLUMNS)}"
        with st.expander(f"🛠️ Sheet Columns ({col_badge})", expanded=False):
            st.caption(
                "Enter one column per line in exact order.  \n"
                "• Auto-fill fields: Client Name, Policy Number, Occupation, Accounts, Share, Share %, PYP premium, etc.  \n"
                "• Blank/Manual column: Enter any custom column name (e.g. `Mail`, `Print`, `Folder`)  \n"
                "• Rename header: `Client Name => Insured Name`"
            )
            import_src_url = st.session_state.mode3_excel_url if is_mode3 else st.session_state.fixed_sheet_url
            import_src_tab = st.session_state.mode3_excel_tab if is_mode3 else st.session_state.fixed_sheet_tab
            if is_direct_sheet and mode2_target_type == "google_sheet" and import_src_url:
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

            cols_text = st.text_area("Custom Columns (1 per line)", value=spec_to_multiline(st.session_state.health_custom_columns), height=240, key=f"custom_cols_textarea_{st.session_state.col_editor_key}")
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

        st.divider()
        st.download_button("📋 Sample Client Master", data=build_sample_master_bytes(), file_name="Sample_Client_Master.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        st.download_button("🏦 Sample Accounts Master", data=build_sample_accounts_master_bytes(), file_name="Sample_Accounts_Master.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        if st.button("🚪 Sign Out", use_container_width=True):
            was_google = st.session_state.auth_method == "google"
            for k, v in DEFAULTS.items():
                st.session_state[k] = v.copy() if isinstance(v, (dict, list)) else v
            st.session_state.pop("last_results", None)
            if was_google and google_configured:
                st.logout()
            else:
                st.rerun()

    return {
        "is_mode1": is_mode1,
        "is_mode2": is_mode2,
        "is_mode3": is_mode3,
        "is_direct_sheet": is_direct_sheet,
        "policy_category": policy_category,
        "mode2_target_type": mode2_target_type,
        "manual_master_file": manual_master_file,
        "manual_acc_files": manual_acc_files,
        "m_count": m_count,
    }
