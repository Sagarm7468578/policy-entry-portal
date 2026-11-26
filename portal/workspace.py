import base64
import importlib
import os
import sys
from datetime import datetime, timedelta, timezone
import pandas as pd
import streamlit as st
from health_parser import (
    OUTPUT_COLUMNS,
    project_rows_to_schema,
    process_health_pdf,
    build_excel_bytes,
)
from portal.backend import (
    is_admin_user,
    call_backend,
    load_saved_health_rows,
    apply_renewal_list_lookup,
    apply_share_commission,
    scan_drive_folder_pdfs,
)
from portal.state import (
    DEFAULT_HEALTH_EXCEL_NAME,
    MAX_PDF_ROUNDS,
    get_active_master_df,
    get_active_accounts_df,
    save_and_record_batch,
)
from portal.bug_highlighter import render_preview_table

IST = timezone(timedelta(hours=5, minutes=30))


def _on_select_all_pdfs_change():
    st.session_state.drive_pdf_sel_default = bool(st.session_state.get("m3_select_all_cb", True))
    st.session_state.drive_pdf_sel_ver += 1


def _is_scanned_error(is_ok: bool, err_msg: str) -> bool:
    if is_ok:
        return False
    low = str(err_msg or "").lower()
    return ("scanned" in low) or ("image pdf" in low)


def _reload_health_parsers():
    """Evicts cached parser modules and re-imports fresh code from disk so 1-click Re-Test picks up new GitHub commits immediately."""
    importlib.invalidate_caches()
    for mod_name in list(sys.modules.keys()):
        if mod_name == "health_parser" or mod_name == "health_parsers" or mod_name.startswith("health_parsers."):
            sys.modules.pop(mod_name, None)
    hp_mod = importlib.import_module("health_parser")
    return hp_mod.process_health_pdf, hp_mod.project_rows_to_schema


def _attach_retest_cache(retest_pdfs: list, extracted_rows: list):
    """Stores current round's PDF bytes in memory so Admin can Re-Test Preview without re-downloading or saving to Excel."""
    if "last_results" not in st.session_state:
        return
    lr = st.session_state["last_results"]
    batch_rows = lr.get("batch_rows") or []
    if len(batch_rows) == len(retest_pdfs):
        lr["retest_pdfs"] = retest_pdfs
    else:
        kept_pols = {str(r.get("Policy Number", "")).strip() for r in batch_rows}
        lr["retest_pdfs"] = [
            item for item, er in zip(retest_pdfs, extracted_rows)
            if str(er.get("Policy Number", "")).strip() in kept_pols
        ]
    lr["retest_count"] = 0
    lr["retest_time"] = ""


def _run_preview_retest(ctx, res):
    """Reloads latest parsers and re-parses cached PDFs for Preview Mode ONLY (no Excel/Sheet save)."""
    cached_pdfs = res.get("retest_pdfs") or []
    if not cached_pdfs:
        st.warning("No cached PDFs found for this batch — please run a fresh batch once to enable 1-click Re-Test.")
        return

    with st.spinner(f"🔄 Reloading latest parsers & re-testing {len(cached_pdfs)} PDFs (Preview only — No Excel save)..."):
        fresh_process_pdf, fresh_project_schema = _reload_health_parsers()
        master_df = get_active_master_df(ctx["manual_master_file"])
        accounts_df = get_active_accounts_df("health", ctx["manual_acc_files"])

        new_rows = []
        new_debug_list = []
        for item in cached_pdfs:
            row_dict, _is_ok, _err_msg, debug_info = fresh_process_pdf(
                item["file_name"],
                item["pdf_bytes"],
                master_df,
                accounts_df=accounts_df,
            )
            new_rows.append(row_dict)
            new_debug_list.append(debug_info)

        if new_rows:
            apply_share_commission(
                new_rows,
                st.session_state.health_share_under60,
                st.session_state.health_share_60plus,
            )
            if st.session_state.health_renewal_folder_url:
                apply_renewal_list_lookup(new_rows, st.session_state.health_renewal_folder_url)

        proj_rows, proj_schema = fresh_project_schema(new_rows, st.session_state.health_custom_columns)
        res["batch_rows"] = proj_rows
        res["batch_columns"] = proj_schema["headers"]
        res["debug_list"] = new_debug_list
        res["retest_count"] = int(res.get("retest_count", 0)) + 1
        res["retest_time"] = datetime.now(IST).strftime("%I:%M:%S %p")


def _render_status_bar(ctx, active_headers, is_custom_cols):
    is_mode2, is_mode3 = ctx["is_mode2"], ctx["is_mode3"]
    if is_mode3:
        ps_label = "Drive Excel"
        ps_status = f"✅ `{st.session_state.mode3_excel_name or 'Drive Excel (.xlsx)'}`" if st.session_state.mode3_excel_url else "⚠️ Not Linked"
    elif is_mode2:
        ps_label = "Policy Sheet"
        if ctx["mode2_target_type"] == "local_excel":
            ps_status = f"✅ `{os.path.basename(st.session_state.local_excel_path)}`" if st.session_state.local_excel_path else "⚠️ Not Linked"
        else:
            ps_status = f"✅ `{st.session_state.fixed_sheet_name or st.session_state.fixed_sheet_tab}`" if st.session_state.fixed_sheet_url else "⚠️ Not Linked"
    else:
        ps_label, ps_status = "Policy Sheet", "☁️ Cloud Master Sheet"

    manual_master = ctx["manual_master_file"]
    cm_status = (f"✅ {ctx['m_count']} Clients" if not st.session_state.linked_master_error else "⚠️ Link Error") if st.session_state.client_master_url else (f"📄 `{manual_master.name}`" if manual_master else "⚪ Not Linked")
    h_acc_df = st.session_state.health_accounts_df
    h_acc_cnt = len(h_acc_df) if isinstance(h_acc_df, pd.DataFrame) else 0
    manual_h_acc = ctx["manual_acc_files"]["health"]
    acc_status = (f"✅ {h_acc_cnt} Rules" if not st.session_state.health_accounts_error else "⚠️ Error") if st.session_state.health_accounts_url else (f"📄 `{manual_h_acc.name}`" if manual_h_acc else "⚪ Not Linked")
    rn_status = f"✅ `{st.session_state.health_renewal_folder_name or 'Linked'}`" if st.session_state.health_renewal_folder_url else "⚪ Not Linked"
    share_status = f"{st.session_state.health_share_under60 or '12'}% / {st.session_state.health_share_60plus or '8'}%"
    cols_status = f"🛠️ {len(active_headers)} Custom Cols" if is_custom_cols else f"🛠️ {len(OUTPUT_COLUMNS)} Default Cols"
    mode_short = "Mode 3 (Drive Excel + Folder)" if is_mode3 else ("Mode 2 (Google Sheet)" if is_mode2 else "Mode 1 (Download)")
    folder_part = ""
    if is_mode3:
        scan_inf = st.session_state.drive_scan_info or {}
        hf_nm = scan_inf.get("active_path") or st.session_state.health_folder_name or "Health Folder"
        folder_part = f"  |  **PDF Folder:** {'✅ `' + hf_nm + '`' if st.session_state.health_folder_url else '⚠️ Not Linked'}"

    st.caption(
        f"**Mode:** {mode_short}{folder_part}  |  **{ps_label}:** {ps_status}  |  "
        f"**Client Master:** {cm_status}  |  **Accounts:** {acc_status}  |  "
        f"**Renewal List:** {rn_status}  |  **Share %:** `{share_status}`  |  **Format:** {cols_status}"
    )


def _render_plan_load_warning():
    """Admin-only safety banner if any file in health_parsers/plans/ failed to load (e.g. filename typo)."""
    if not is_admin_user():
        return
    try:
        from health_parsers.plans import PLAN_LOAD_ERRORS
        if PLAN_LOAD_ERRORS:
            details = " | ".join(f"`{m}.py`: {err}" for m, err in PLAN_LOAD_ERRORS.items())
            st.warning(f"⚠️ Plan Parser Load Notice: {details}")
    except Exception:
        pass


def _render_mode3_workspace(ctx, active_headers):
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
            info, f_err = scan_drive_folder_pdfs(st.session_state.user_id, active_folder_url, st.session_state.drive_selected_year, st.session_state.drive_selected_month)
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
                "Select": st.session_state.drive_pdf_sel_default, "#": i + 1, "File Name": f["name"],
                "Status": "✅ Entered" if f.get("last_status") == "DONE" else ("⚠️ Prev Error" if f.get("last_status") == "ERROR" else "🆕 New"),
                "Modified": f.get("updated", ""),
            }
            for i, f in enumerate(candidate_files)
        ])
        edited_df = st.data_editor(
            df_selectable, use_container_width=True, hide_index=True,
            disabled=["#", "File Name", "Status", "Modified"],
            column_config={"Select": st.column_config.CheckboxColumn("Select", default=True, width="small"), "#": st.column_config.NumberColumn("#", width="small")},
            key=f"m3_pdf_editor_{st.session_state.drive_pdf_sel_ver}",
        )
        target_files = [candidate_files[i] for i in edited_df.index[edited_df["Select"] == True].tolist()]
        st.caption(f"✅ Selected for Entry: **{len(target_files)} / {len(candidate_files)} PDFs**")

    skip_duplicates_m3 = st.checkbox("Auto-skip duplicate policies", value=False, key="skip_dup_m3")

    if st.button(f"🚀 Process {len(target_files)} Selected PDFs & Save to Drive Excel (.xlsx)", type="primary", use_container_width=True, disabled=(len(target_files) == 0), key="start_mode3_btn"):
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

            if _is_scanned_error(is_ok, err_msg):
                error_files.append((fname, pdf_bytes))
                error_details.append({"File Name": fname, "Reason": err_msg})
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
                "action": "finalize_drive_batch", "user_id": st.session_state.user_id,
                "target_folder_id": info.get("active_folder_id", ""), "folder_url": active_folder_url,
                "done_items": done_track_items, "error_items": error_track_items,
                "copy_errors_to_folder": False,
            })

        save_and_record_batch(
            extracted_rows, done_files, error_files, error_details, debug_list,
            mode_tag="Mode 3 (Drive Excel)", is_direct_sheet=True, mode2_target_type="google_sheet",
            skip_duplicates=skip_duplicates_m3, drive_target_url=active_m3_excel_url,
            drive_target_tab=st.session_state.mode3_excel_tab, is_mode3_excel_slot=True,
        )
        _attach_retest_cache(retest_pdfs, extracted_rows)
        st.session_state.drive_scan_info, st.session_state.drive_last_scan_key = None, ""
        st.rerun()


def _render_upload_workspace(ctx):
    is_mode2, mode2_target_type = ctx["is_mode2"], ctx["mode2_target_type"]
    hdr1, hdr2 = st.columns([4, 1])
    with hdr1:
        st.subheader("📤 Upload Policy PDFs")
    with hdr2:
        if st.button("🗑️ Clear All PDFs", use_container_width=True):
            st.session_state.pdf_uploader_key += 1
            st.session_state.pop("last_results", None)
            st.rerun()

    uploaded_pdfs = st.file_uploader("Select one or more Health Policy PDFs", type=["pdf"], accept_multiple_files=True, key=f"pdf_uploader_{st.session_state.pdf_uploader_key}", label_visibility="collapsed")
    skip_duplicates = st.checkbox("Auto-skip duplicate policies (same Policy Number + Expiry Date)", value=False)
    btn_label = "🚀 Start Policy Entry (Mode 2: Direct Save to Sheet)" if is_mode2 else "🚀 Start Policy Entry (Mode 1: Cloud Portal)"

    if st.button(btn_label, type="primary", use_container_width=True):
        if not uploaded_pdfs:
            st.warning("Please upload at least one Policy PDF.")
        elif is_mode2 and mode2_target_type == "google_sheet" and not st.session_state.fixed_sheet_url:
            st.warning("Please link your Policy Entry Google Sheet via the Left Sidebar first.")
        elif is_mode2 and mode2_target_type == "local_excel" and not st.session_state.local_excel_path:
            st.warning("Please link your Local Excel (.xlsx) file path via the Left Sidebar first.")
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
                if _is_scanned_error(is_ok, err_msg):
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
            _attach_retest_cache(retest_pdfs, extracted_rows)
            st.session_state.pdf_uploader_key += 1
            st.rerun()


def _render_results_and_history(ctx, active_headers):
    is_mode1, is_mode3, is_direct_sheet = ctx["is_mode1"], ctx["is_mode3"], ctx["is_direct_sheet"]

    if "last_results" in st.session_state:
        res = st.session_state["last_results"]
        st.divider()
        if res.get("save_error"):
            st.error(res["save_error"])
        elif res.get("save_msg"):
            st.success(res["save_msg"])
        if res.get("skipped_count", 0) > 0:
            st.info(f"ℹ️ Skipped {res['skipped_count']} duplicate policies already present in the sheet.")

        st.subheader(f"⚡ Latest Batch #{res['round_no']} ({res['time_display']})")
        m1, m2, m3 = st.columns(3)
        m1.metric("Total PDFs", res["total_count"])
        m2.metric("Completed ✅", res["done_count"])
        m3.metric("Errors ❌", res["error_count"])

        if not is_mode3:
            z1, z2 = st.columns(2)
            with z1:
                if res.get("round_excel_bytes") and res.get("batch_rows"):
                    st.download_button(f"📊 Download Batch #{res['round_no']} Excel", data=res["round_excel_bytes"], file_name=f"Batch_{res['round_no']}_Health_Entries_{res['timestamp']}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True, key=f"latest_xlsx_{res['round_no']}_{res['timestamp']}")
            with z2:
                if res["err_zip_bytes"]:
                    st.download_button(f"⚠️ Download Batch #{res['round_no']} Error PDFs (ZIP)", data=res["err_zip_bytes"], file_name=f"Batch_{res['round_no']}_Error_Policies_{res['timestamp']}.zip", mime="application/zip", use_container_width=True, key=f"latest_err_{res['round_no']}_{res['timestamp']}")

        if res["error_details"]:
            st.warning("The following PDFs encountered extraction issues (excluded from Excel & Preview Mode):")
            st.dataframe(pd.DataFrame(res["error_details"]), use_container_width=True, hide_index=True)

        if is_direct_sheet and res.get("batch_rows"):
            if is_admin_user():
                p_hdr1, p_hdr2 = st.columns([3, 1.6])
                with p_hdr1:
                    st.subheader("Preview Mode")
                with p_hdr2:
                    has_cache = bool(res.get("retest_pdfs"))
                    if st.button(
                        "🔄 Re-Test Preview (No Excel Save)",
                        use_container_width=True,
                        disabled=not has_cache,
                        help="Reloads latest GitHub parser fixes on current batch PDFs without saving to Excel — fixed 🔴 cells auto-turn 🟢 Green!",
                        key=f"retest_preview_btn_{res['round_no']}_{res['timestamp']}",
                    ):
                        _run_preview_retest(ctx, res)
                        st.rerun()
                if res.get("retest_count", 0) > 0:
                    st.success(
                        f"🟢 Live Re-Test #{res['retest_count']} complete ({res.get('retest_time', '')}) — "
                        f"Fixed 🔴 cells automatically turned 🟢 Green! (Drive Excel untouched)"
                    )
            else:
                st.subheader("Preview Mode")

            render_preview_table(
                rows=res["batch_rows"],
                columns=res.get("batch_columns") or active_headers,
                batch_id=f"{res['round_no']}_{res['timestamp']}",
                enable_highlighter=is_admin_user(),
                debug_list=res.get("debug_list", []),
                retest_count=int(res.get("retest_count", 0)),
            )

    if not is_mode3 and st.session_state.batch_history:
        with st.expander(f"🗂️ Last {len(st.session_state.batch_history)} Batches Download History (Max {MAX_PDF_ROUNDS})", expanded=(len(st.session_state.batch_history) > 1)):
            st.caption("Download Excel copies or Error PDFs from recent batches.")
            for b in st.session_state.batch_history:
                c_info, c_xlsx, c_err = st.columns([2.5, 1.5, 1.5])
                with c_info:
                    st.markdown(f"**Batch #{b['round_no']}** — `{b['time_display']}`  \nTotal: **{b['total_count']}** | Done: **{b['done_count']} ✅** | Error: **{b['error_count']} ❌**")
                with c_xlsx:
                    if b.get("round_excel_bytes") and b.get("batch_rows"):
                        st.download_button(f"📊 Batch #{b['round_no']} Excel", data=b["round_excel_bytes"], file_name=f"Batch_{b['round_no']}_Health_Entries_{b['timestamp']}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True, key=f"hist_xlsx_{b['round_no']}_{b['timestamp']}")
                with c_err:
                    if b["err_zip_bytes"]:
                        st.download_button(f"⚠️ Batch #{b['round_no']} Errors (ZIP)", data=b["err_zip_bytes"], file_name=f"Batch_{b['round_no']}_Error_Policies_{b['timestamp']}.zip", mime="application/zip", use_container_width=True, key=f"hist_err_{b['round_no']}_{b['timestamp']}")
                    else:
                        st.caption("No Error PDFs ✅")
                st.divider()

    if is_mode1:
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
            st.download_button(f"📥 Download {DEFAULT_HEALTH_EXCEL_NAME} ({len(proj_saved)} Entries)", data=master_excel_bytes, file_name=DEFAULT_HEALTH_EXCEL_NAME, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary", use_container_width=True)
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


def render_workspace(ctx, active_headers, is_custom_cols):
    st.title("🛡️ MS.Soft Policy Mitra")
    st.caption("All-in-One Insurance Advisor Automation Suite")

    if ctx["policy_category"] != "Health Insurance":
        st.info(
            f"**{ctx['policy_category']}** module is under development. Please select **Health Insurance** to continue "
            f"(you can already pre-link Motor/SME Drive Folders, Accounts Masters, and Renewal Lists in the sidebar)."
        )
        st.stop()

    _render_status_bar(ctx, active_headers, is_custom_cols)
    _render_plan_load_warning()

    if ctx["is_mode1"] and st.session_state.saved_health_rows is None:
        with st.spinner("Loading your saved Health Master Sheet..."):
            loaded_rows, load_err = load_saved_health_rows(st.session_state.user_id)
            st.session_state.saved_health_rows = loaded_rows
            if load_err:
                st.warning(f"⚠️ Cloud sheet notice: {load_err}")

    if ctx["is_mode3"]:
        _render_mode3_workspace(ctx, active_headers)
    else:
        _render_upload_workspace(ctx)

    _render_results_and_history(ctx, active_headers)
