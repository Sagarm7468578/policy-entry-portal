import base64
import pandas as pd
import streamlit as st
from health_parser import process_health_pdf
from portal.backend import (
    call_backend,
    apply_renewal_list_lookup,
    apply_share_commission,
    scan_drive_folder_pdfs,
)
from portal.state import (
    get_active_master_df,
    get_active_accounts_df,
    save_and_record_batch,
)
from portal.retest_engine import get_skip_pdf_reason, attach_retest_cache


def _on_select_all_pdfs_change():
    st.session_state.drive_pdf_sel_default = bool(st.session_state.get("m3_select_all_cb", True))
    st.session_state.drive_pdf_sel_ver += 1


def render_mode3_workspace(ctx):
    """Renders Mode 3 (Google Drive Folder Scanner + Direct Drive Excel .xlsx entry)."""
    active_folder_url = st.session_state.health_folder_url
    active_m3_excel_url = st.session_state.mode3_excel_url

    if not active_m3_excel_url:
        st.warning("📊 Please link your Google Drive `.xlsx` Excel file first via **Left Sidebar → Mode 3 Drive Excel**.")
    if not active_folder_url:
        st.warning("📁 Please link your **`MEDICLAIM`** parent folder (or direct month folder) via **Left Sidebar → Drive Auto-Folders → Health**.")
        return

    desired_scan_key = f"{active_folder_url}||{st.session_state.drive_selected_year}||{st.session_state.drive_selected_month}"
    if st.session_state.drive_scan_info is None or st.session_state.drive_last_scan_key != desired_scan_key:
        with st.spinner("Scanning Google Drive folder..."):
            info, f_err = scan_drive_folder_pdfs(
                st.session_state.user_id,
                active_folder_url,
                st.session_state.drive_selected_year,
                st.session_state.drive_selected_month,
            )
            st.session_state.drive_scan_info, st.session_state.drive_scan_error = info, f_err
            if info:
                if info.get("root_folder_name"):
                    st.session_state.health_folder_name = info["root_folder_name"]
                st.session_state.drive_selected_year = info.get("selected_year", "")
                st.session_state.drive_selected_month = info.get("selected_month", "")
                st.session_state.drive_last_scan_key = f"{active_folder_url}||{st.session_state.drive_selected_year}||{st.session_state.drive_selected_month}"
            else:
                st.session_state.drive_last_scan_key = desired_scan_key

    info = st.session_state.drive_scan_info or {}
    hdr1, hdr2 = st.columns([4, 1])
    with hdr1:
        st.subheader(f"📁 {info.get('active_path') or st.session_state.health_folder_name or 'Linked Drive Folder'}")
    with hdr2:
        if st.button("🔄 Scan Folder", use_container_width=True, key="rescan_drive_folder"):
            st.session_state.drive_scan_info, st.session_state.drive_last_scan_key = None, ""
            st.session_state.pop("last_results", None)
            st.rerun()

    avail_years, avail_months = info.get("available_years", []), info.get("available_months", [])
    if avail_years:
        ym1, ym2 = st.columns(2)
        with ym1:
            yr_idx = avail_years.index(info.get("selected_year")) if info.get("selected_year") in avail_years else 0
            chosen_yr = st.selectbox("📅 Year Folder", avail_years, index=yr_idx, key="sb_drive_year")
        with ym2:
            if avail_months:
                mo_idx = avail_months.index(info.get("selected_month")) if info.get("selected_month") in avail_months else 0
                chosen_mo = st.selectbox("📆 Month Folder", avail_months, index=mo_idx, key="sb_drive_month")
            else:
                chosen_mo = ""
                st.caption("No month subfolders found inside this year folder.")

        if chosen_yr != info.get("selected_year", ""):
            st.session_state.drive_selected_year, st.session_state.drive_selected_month, st.session_state.drive_scan_info = chosen_yr, "", None
            st.session_state.pop("last_results", None)
            st.rerun()
        elif avail_months and chosen_mo != info.get("selected_month", ""):
            st.session_state.drive_selected_month, st.session_state.drive_scan_info = chosen_mo, None
            st.session_state.pop("last_results", None)
            st.rerun()

    if st.session_state.drive_scan_error:
        st.error(f"⚠️ {st.session_state.drive_scan_error}")
        return

    all_drive_files = info.get("files", [])
    new_or_retry_files = [f for f in all_drive_files if f.get("last_status") != "DONE"]
    already_done_files = [f for f in all_drive_files if f.get("last_status") == "DONE"]

    if not all_drive_files:
        st.info("✅ No PDF files found in this folder. Add Health Policy PDFs and click **Scan Folder**.")
        return

    include_done = True
    if already_done_files:
        st.success(f"📄 Total PDFs: **{len(all_drive_files)}**  |  🆕 Pending: **{len(new_or_retry_files)}**  |  ✅ Previously Entered: **{len(already_done_files)}**")
        include_done = st.checkbox(f"Include previously entered PDFs ({len(already_done_files)}) for reprocessing", value=True, key="include_done_m3")
    else:
        st.success(f"📄 **{len(new_or_retry_files)} Pending PDFs** ready for processing...")

    candidate_files = all_drive_files if include_done else new_or_retry_files
    if not candidate_files:
        st.info("🎉 All PDFs in this folder have already been entered. Add new PDFs and click **Scan Folder**.")
        return

    list_sig = f"{info.get('active_folder_id', '')}|{include_done}|{','.join(f['id'] for f in candidate_files)}"
    if st.session_state.drive_pdf_list_sig != list_sig:
        st.session_state.drive_pdf_list_sig = list_sig
        st.session_state.drive_pdf_sel_default = True
        st.session_state.m3_select_all_cb = True
        st.session_state.drive_pdf_sel_ver += 1

    with st.expander(f"📋 Select Policy PDFs ({len(candidate_files)} available)", expanded=True):
        st.checkbox("☑️ Select All PDFs For Entry", key="m3_select_all_cb", on_change=_on_select_all_pdfs_change)
        df_selectable = pd.DataFrame([
            {
                "Select": st.session_state.drive_pdf_sel_default,
                "#": str(i + 1),
                "File Name": f["name"],
                "Status": "✅ Entered" if f.get("last_status") == "DONE" else ("⚠️ Prev Error" if f.get("last_status") == "ERROR" else "🆕 New"),
                "Modified": f.get("updated", ""),
            }
            for i, f in enumerate(candidate_files)
        ])
        # Compact 6-row visible height + left-aligned columns so Header & Details align on the same side
        visible_rows = min(len(candidate_files), 6)
        list_height = 38 + visible_rows * 35
        edited_df = st.data_editor(
            df_selectable,
            use_container_width=True,
            hide_index=True,
            height=list_height,
            disabled=["#", "File Name", "Status", "Modified"],
            column_config={
                "Select": st.column_config.CheckboxColumn("Select", default=True, width="small"),
                "#": st.column_config.TextColumn("#", width="small"),
                "File Name": st.column_config.TextColumn("File Name", width="large"),
                "Status": st.column_config.TextColumn("Status", width="small"),
                "Modified": st.column_config.TextColumn("Modified", width="medium"),
            },
            key=f"m3_pdf_editor_{st.session_state.drive_pdf_sel_ver}",
        )
        target_files = [candidate_files[i] for i in edited_df.index[edited_df["Select"] == True].tolist()]
        st.caption(f"✅ Selected for Entry: **{len(target_files)} / {len(candidate_files)} PDFs**")

    skip_duplicates_m3 = st.checkbox("Auto-skip duplicate policies", value=False, key="skip_dup_m3")

    if st.button(
        f"🚀 Process {len(target_files)} Selected PDFs & Save to Drive Excel (.xlsx)",
        type="primary",
        use_container_width=True,
        disabled=(len(target_files) == 0),
        key="start_mode3_btn",
    ):
        if not active_m3_excel_url:
            st.warning("Please link your Google Drive `.xlsx` file first via **Left Sidebar → Mode 3 Drive Excel**.")
            return
        st.session_state.pop("last_results", None)

        master_df = get_active_master_df(ctx["manual_master_file"])
        accounts_df = get_active_accounts_df("health", ctx["manual_acc_files"])
        extracted_rows, done_files, error_files, error_details, debug_list = [], [], [], [], []
        done_track_items, error_track_items, retest_pdfs = [], [], []

        progress, status_text = st.progress(0), st.empty()
        for idx, f_meta in enumerate(target_files):
            fname, fid = f_meta["name"], f_meta["id"]
            status_text.text(f"Reading from Drive ({idx + 1}/{len(target_files)}): {fname}")
            dl_res = call_backend({"action": "get_drive_pdf", "file_id": fid})
            if not dl_res.get("success") or not dl_res.get("content_b64"):
                err_reason = dl_res.get("message", "Could not download PDF from Google Drive.")
                error_files.append((fname, b""))
                error_details.append({"File Name": fname, "Reason": err_reason})
                error_track_items.append({"id": fid, "name": fname})
                progress.progress((idx + 1) / len(target_files))
                continue

            pdf_bytes = base64.b64decode(dl_res["content_b64"])
            row_dict, is_ok, err_msg, debug_info = process_health_pdf(fname, pdf_bytes, master_df, accounts_df=accounts_df)

            skip_reason = get_skip_pdf_reason(fname, is_ok, err_msg, debug_info)
            if skip_reason:
                error_files.append((fname, pdf_bytes))
                error_details.append({"File Name": fname, "Reason": skip_reason})
                error_track_items.append({"id": fid, "name": fname})
            else:
                debug_list.append(debug_info)
                extracted_rows.append(row_dict)
                retest_pdfs.append({"file_name": fname, "pdf_bytes": pdf_bytes})
                if is_ok:
                    done_files.append((fname, pdf_bytes))
                    done_track_items.append({"id": fid, "name": fname})
                else:
                    error_files.append((fname, pdf_bytes))
                    error_details.append({"File Name": fname, "Reason": err_msg})
                    error_track_items.append({"id": fid, "name": fname})
            progress.progress((idx + 1) / len(target_files))

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

        with st.spinner("Updating Drive tracking status..."):
            call_backend({
                "action": "finalize_drive_batch",
                "user_id": st.session_state.user_id,
                "target_folder_id": info.get("active_folder_id", ""),
                "folder_url": active_folder_url,
                "done_items": done_track_items,
                "error_items": error_track_items,
                "copy_errors_to_folder": False,
            })

        save_and_record_batch(
            extracted_rows, done_files, error_files, error_details, debug_list,
            mode_tag="Mode 3 (Drive Excel)", is_direct_sheet=True, mode2_target_type="google_sheet",
            skip_duplicates=skip_duplicates_m3, drive_target_url=active_m3_excel_url,
            drive_target_tab=st.session_state.mode3_excel_tab, is_mode3_excel_slot=True,
        )
        attach_retest_cache(retest_pdfs, extracted_rows)
        st.session_state.drive_scan_info, st.session_state.drive_last_scan_key = None, ""
        st.rerun()
