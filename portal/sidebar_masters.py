import pandas as pd
import streamlit as st
from portal.backend import (
    save_user_sheet_settings,
    fetch_linked_client_master,
    fetch_linked_accounts_master,
)
from portal.sidebar_modes import render_category_folder_panel


def render_client_master_panel():
    """Renders Client Master sidebar panel and returns (m_count, manual_master_file)."""
    manual_master_file = None
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

    return m_count, manual_master_file


def render_accounts_master_panel():
    """Renders Accounts Master sidebar panel (Health / Motor / SME) and returns manual_acc_files dict."""
    manual_acc_files = {"health": None, "motor": None, "sme": None}
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
    return manual_acc_files


def render_renewal_list_panel():
    """Renders Renewal List Drive folders panel (Health / Motor / SME)."""
    render_category_folder_panel(
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
