import pandas as pd
import streamlit as st
from health_parser import (
    project_rows_to_schema,
    process_health_pdf,
    build_excel_bytes,
)
from portal.backend import (
    call_backend,
    load_saved_health_rows,
    apply_renewal_list_lookup,
    apply_share_commission,
)
from portal.state import (
    DEFAULT_HEALTH_EXCEL_NAME,
    MAX_PDF_ROUNDS,
    get_active_master_df,
    get_active_accounts_df,
    save_and_record_batch,
)
from portal.auth_wallet import (
    render_wallet_banner_if_billable,
    check_wallet_before_batch,
)
from portal.retest_engine import is_scanned_error, attach_retest_cache


def render_upload_workspace(ctx):
    """Renders Mode 1 (Cloud Download) & Mode 2 (Direct Google Sheet / Local Excel) PDF uploader."""
    render_wallet_banner_if_billable("m12")

    is_mode2, mode2_target_type = ctx["is_mode2"], ctx["mode2_target_type"]
    hdr1, hdr2 = st.columns([4, 1])
    with hdr1:
        st.subheader("📤 Upload Policy PDFs")
    with hdr2:
        if st.button("🗑️ Clear All PDFs", use_container_width=True):
            st.session_state.pdf_uploader_key += 1
            st.session_state.pop("last_results", None)
            st.rerun()

    uploaded_pdfs = st.file_uploader(
        "Select one or more Health Policy PDFs",
        type=["pdf"],
        accept_multiple_files=True,
        key=f"pdf_uploader_{st.session_state.pdf_uploader_key}",
        label_visibility="collapsed",
    )
    skip_duplicates = st.checkbox("Auto-skip duplicate policies (same Policy Number + Expiry Date)", value=False)
    btn_label = "🚀 Start Policy Entry (Mode 2: Direct Save to Sheet)" if is_mode2 else "🚀 Start Policy Entry (Mode 1: Cloud Portal)"

    if st.button(btn_label, type="primary", use_container_width=True):
        if not uploaded_pdfs:
            st.warning("Please upload at least one Policy PDF.")
        elif is_mode2 and mode2_target_type == "google_sheet" and not st.session_state.fixed_sheet_url:
            st.warning("Please link your Policy Entry Google Sheet via **Left Sidebar → 🔌 Connectors** first.")
        elif is_mode2 and mode2_target_type == "local_excel" and not st.session_state.local_excel_path:
            st.warning("Please link your Local Excel (.xlsx) file path via **Left Sidebar → 🔌 Connectors** first.")
        elif not check_wallet_before_batch(len(uploaded_pdfs)):
            return
        else:
            st.session_state.pop("last_results", None)
            master_df = get_active_master_df(ctx["manual_master_file"])
            accounts_df = get_active_accounts_df("health", ctx["manual_acc_files"])
            extracted_rows, done_files, error_files, error_details, debug_list = [], [], [], [], []
            retest_pdfs = []

            progress, status_text = st.progress(0), st.empty()
            for idx, pdf in enumerate(uploaded_pdfs):
                status_text.text(f"Processing ({idx + 1}/{len(uploaded_pdfs)}): {pdf.name}")
                pdf_bytes = pdf.read()
                row_dict, is_ok, err_msg, debug_info = process_health_pdf(pdf.name, pdf_bytes, master_df, accounts_df=accounts_df)
                if is_scanned_error(is_ok, err_msg):
                    error_files.append((pdf.name, pdf_bytes))
                    error_details.append({"File Name": pdf.name, "Reason": err_msg})
                else:
                    debug_list.append(debug_info)
                    extracted_rows.append(row_dict)
                    retest_pdfs.append({"file_name": pdf.name, "pdf_bytes": pdf_bytes})
                    if is_ok:
                        done_files.append((pdf.name, pdf_bytes))
                    else:
                        error_files.append((pdf.name, pdf_bytes))
                        error_details.append({"File Name": pdf.name, "Reason": err_msg})
                progress.progress((idx + 1) / len(uploaded_pdfs))

            status_text.empty()
            progress.empty()

            if extracted_rows:
                apply_share_commission(
                    extracted_rows,
                    st.session_state.health_share_under60,
                    st.session_state.health_share_60plus,
                )

            if st.session_state.health_renewal_folder_url and extracted_rows:
                with st.spinner("Matching Renewal List PDFs for PYP Premium & Renewal Status..."):
                    apply_renewal_list_lookup(extracted_rows, st.session_state.health_renewal_folder_url)

            save_and_record_batch(
                extracted_rows, done_files, error_files, error_details, debug_list,
                mode_tag="Mode 2" if is_mode2 else "Mode 1", is_direct_sheet=is_mode2,
                mode2_target_type=mode2_target_type, skip_duplicates=skip_duplicates,
                drive_target_url=st.session_state.fixed_sheet_url, drive_target_tab=st.session_state.fixed_sheet_tab,
            )
            attach_retest_cache(retest_pdfs, extracted_rows)
            st.session_state.pdf_uploader_key += 1
            st.rerun()


def render_batch_history():
    """Renders download history expander for Mode 1 & Mode 2."""
    if not st.session_state.batch_history:
        return
    with st.expander(f"🗂️ Last {len(st.session_state.batch_history)} Batches Download History (Max {MAX_PDF_ROUNDS})", expanded=(len(st.session_state.batch_history) > 1)):
        st.caption("Download Excel copies or Error PDFs from recent batches.")
        for b in st.session_state.batch_history:
            c_info, c_xlsx, c_err = st.columns([2.5, 1.5, 1.5])
            with c_info:
                st.markdown(
                    f"**Batch #{b['round_no']}** — `{b['time_display']}`  \n"
                    f"Total: **{b['total_count']}** | Done: **{b['done_count']} ✅** | Error: **{b['error_count']} ❌**"
                )
            with c_xlsx:
                if b.get("round_excel_bytes") and b.get("batch_rows"):
                    st.download_button(
                        f"📊 Batch #{b['round_no']} Excel",
                        data=b["round_excel_bytes"],
                        file_name=f"Batch_{b['round_no']}_Health_Entries_{b['timestamp']}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                        key=f"hist_xlsx_{b['round_no']}_{b['timestamp']}",
                    )
            with c_err:
                if b["err_zip_bytes"]:
                    st.download_button(
                        f"⚠️ Batch #{b['round_no']} Errors (ZIP)",
                        data=b["err_zip_bytes"],
                        file_name=f"Batch_{b['round_no']}_Error_Policies_{b['timestamp']}.zip",
                        mime="application/zip",
                        use_container_width=True,
                        key=f"hist_err_{b['round_no']}_{b['timestamp']}",
                    )
                else:
                    st.caption("No Error PDFs ✅")
            st.divider()


def render_mode1_cloud_sheet():
    """Renders Mode 1 Cloud Master Sheet table, download, and reset panel."""
    st.divider()
    saved_rows = st.session_state.saved_health_rows or []
    sh1, sh2 = st.columns([3, 1])
    with sh1:
        st.subheader(f"📊 Health Policy Master Sheet (Total Saved: {len(saved_rows)})")
    with sh2:
        if st.button("🔄 Refresh Sheet", use_container_width=True):
            with st.spinner("Refreshing saved sheet..."):
                loaded_rows, load_err = load_saved_health_rows(st.session_state.user_id)
                st.session_state.saved_health_rows = loaded_rows
                if load_err:
                    st.error(load_err)
                else:
                    st.rerun()

    if saved_rows:
        proj_saved, saved_schema = project_rows_to_schema(saved_rows, st.session_state.health_custom_columns)
        master_excel_bytes = build_excel_bytes(proj_saved, columns=saved_schema["headers"], col_types=saved_schema["col_types"])
        st.download_button(
            f"📥 Download {DEFAULT_HEALTH_EXCEL_NAME} ({len(proj_saved)} Entries)",
            data=master_excel_bytes,
            file_name=DEFAULT_HEALTH_EXCEL_NAME,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
        )
        st.dataframe(pd.DataFrame(proj_saved, columns=saved_schema["headers"]), use_container_width=True, hide_index=True)

        with st.expander("🗑️ Reset Cloud Sheet (Clear All Saved Entries)"):
            st.warning("Please download a backup of your Excel file before clearing saved entries.")
            confirm_clear = st.checkbox("I confirm I want to permanently clear all saved Health entries.")
            if st.button("Clear Saved Health Sheet", disabled=not confirm_clear):
                with st.spinner("Clearing saved entries..."):
                    clr_res = call_backend({"action": "clear_health_entries", "user_id": st.session_state.user_id})
                if clr_res.get("success"):
                    st.session_state.saved_health_rows = []
                    st.session_state.pop("last_results", None)
                    st.success("Cloud sheet cleared successfully.")
                    st.rerun()
                else:
                    st.error(clr_res.get("message", "Failed to clear saved sheet."))
    else:
        st.info("Your Cloud Health Sheet is currently empty. Upload PDFs above to start recording entries.")
