import os
import streamlit as st
from portal.backend import (
    IS_CLOUD,
    call_backend,
    save_user_sheet_settings,
    save_local_excel_path,
)


def qp_get(key: str, default: str = "") -> str:
    try:
        val = st.query_params.get(key, default)
        if isinstance(val, list):
            return str(val[0]) if val else default
        return str(val) if val is not None else default
    except Exception:
        return default


def qp_set(key: str, val: str):
    try:
        if val:
            if qp_get(key, "") != val:
                st.query_params[key] = val
        else:
            st.query_params.pop(key, None)
    except Exception:
        pass


def render_category_folder_panel(title, caption, folder_specs, expanded=False, reset_health_scan=False, footer_tip=""):
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
                                st.session_state.update({
                                    "drive_scan_info": None,
                                    "drive_last_scan_key": "",
                                    "drive_selected_year": "",
                                    "drive_selected_month": "",
                                })
                                qp_set("yr", "")
                                qp_set("mo", "")
                            st.rerun()
                        else:
                            st.error(u_res.get("message", "Failed to unlink folder."))
                else:
                    f_inp = st.text_input(
                        f"{cat_label} Drive Folder Link",
                        placeholder="https://drive.google.com/drive/folders/...",
                        key=f"inp_{url_key}",
                    )
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
                                            st.session_state.update({
                                                "drive_scan_info": None,
                                                "drive_last_scan_key": "",
                                                "drive_selected_year": "",
                                                "drive_selected_month": "",
                                            })
                                            qp_set("yr", "")
                                            qp_set("mo", "")
                                        st.rerun()
                                    else:
                                        st.error(s_res.get("message", "Failed to save folder link."))
                    if footer_tip:
                        st.caption(footer_tip)


def render_mode3_panels(is_mode3: bool, is_bugging: bool):
    """Renders Mode 3 Drive Excel panel and Drive Auto-Folders panel (shared with Bugging Mode)."""
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

    if is_mode3 or is_bugging:
        render_category_folder_panel(
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


def render_mode2_panel() -> str:
    """Renders Mode 2 Policy Entry Sheet panel and returns mode2_target_type."""
    mode2_target_type = "google_sheet"
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
    return mode2_target_type
