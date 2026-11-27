import base64
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
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

_POLICY_LIST_LOCK_CSS = """
<style>
[data-testid="stDataFrame"],
[data-testid="stDataFrame"] .dvn-scroller,
.stDataFrameGlideDataEditor,
.dvn-scroller {
    overscroll-behavior: contain !important;
}
</style>
"""

_POLICY_LIST_WHEEL_LOCK_JS = """
<script>
(function () {
  try {
    var pDoc = window.parent && window.parent.document;
    if (!pDoc || window.parent.__policyListWheelLocked) return;
    window.parent.__policyListWheelLocked = true;
    pDoc.addEventListener("wheel", function (e) {
      var target = e.target;
      if (!target || !target.closest) return;
      var dfBox = target.closest('[data-testid="stDataFrame"]');
      if (!dfBox) return;
      var scroller = dfBox.querySelector(".dvn-scroller");
      var dy = e.deltaY || 0;
      var dx = e.deltaX || 0;
      if (Math.abs(dy) >= Math.abs(dx) && dy !== 0) {
        if (!scroller || scroller.scrollHeight <= scroller.clientHeight + 1) {
          e.preventDefault();
          return;
        }
        var atTop = scroller.scrollTop <= 0;
        var atBottom = scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 2;
        if ((dy < 0 && atTop) || (dy > 0 && atBottom)) {
          e.preventDefault();
        }
      }
    }, { passive: false, capture: true });
  } catch (err) {}
})();
</script>
"""


def _qp_get(key: str, default: str = "") -> str:
    try:
        val = st.query_params.get(key, default)
        if isinstance(val, list):
            return str(val[0]) if val else default
        return str(val) if val is not None else default
    except Exception:
        return default


def _qp_set(key: str, val: str):
    try:
        if val:
            if _qp_get(key, "") != val:
                st.query_params[key] = val
        else:
            st.query_params.pop(key, None)
    except Exception:
        pass


def _on_select_all_pdfs_change():
    checked = bool(st.session_state.get("m3_select_all_cb", False))
    st.session_state.drive_pdf_sel_default = checked
    st.session_state["drive_pdf_sel_mode"] = "all" if checked else "none"
    st.session_state.drive_pdf_sel_ver += 1


def _is_file_selected_default(f_meta: dict) -> bool:
    sel_mode = st.session_state.get("drive_pdf_sel_mode", "new_only")
    if sel_mode == "all":
        return True
    if sel_mode == "none":
        return False
    # Default daily-entry mode: New & Prev-Error auto-selected, Entered unselected
    return f_meta.get("last_status") != "DONE"


def _cancel_mode3_job():
    job = st.session_state.pop("active_entry_job", None)
    done_so_far = job.get("idx", 0) if isinstance(job, dict) else 0
    total_cnt = len(job.get("target_files", [])) if isinstance(job, dict) else 0
    st.session_state["entry_cancel_notice"] = (
        f"🛑 Entry process cancelled ({done_so_far}/{total_cnt} PDFs read). Nothing was saved to Excel."
    )


def _step_mode3_job(job):
    """Processes 1 PDF per rerun so the '🛑 Cancel Entry Process' button responds instantly mid-batch."""
    target_files = job["target_files"]
    total = len(target_files)
    idx = job["idx"]

    c_prog, c_cancel = st.columns([3.4, 1.2])
    with c_prog:
        st.progress(min(idx / max(total, 1), 1.0))
        if idx < total:
            st.info(f"⏳ Reading from Drive ({idx + 1}/{total}): **{target_files[idx]['name']}**")
        else:
            st.info("💾 Saving batch to Google Drive Excel (.xlsx)...")
    with c_cancel:
        st.button(
            "🛑 Cancel Entry Process",
            use_container_width=True,
            key="btn_cancel_m3_entry",
            on_click=_cancel_mode3_job,
        )

    if idx < total:
        f_meta = target_files[idx]
        fname, fid = f_meta["name"], f_meta["id"]
        dl_res = call_backend({"action": "get_drive_pdf", "file_id": fid})
        if not dl_res.get("success") or not dl_res.get("content_b64"):
            err_reason = dl_res.get("message", "Could not download PDF from Google Drive.")
            job["error_files"].append((fname, b""))
            job["error_details"].append({"File Name": fname, "Reason": err_reason})
            job["error_track_items"].append({"id": fid, "name": fname})
        else:
            pdf_bytes = base64.b64decode(dl_res["content_b64"])
            row_dict, is_ok, err_msg, debug_info = process_health_pdf(
                fname, pdf_bytes, job["master_df"], accounts_df=job["accounts_df"]
            )
            skip_reason = get_skip_pdf_reason(fname, is_ok, err_msg, debug_info)
            if skip_reason:
                job["error_files"].append((fname, pdf_bytes))
                job["error_details"].append({"File Name": fname, "Reason": skip_reason})
                job["error_track_items"].append({"id": fid, "name": fname})
            else:
                job["debug_list"].append(debug_info)
                job["extracted_rows"].append(row_dict)
                job["retest_pdfs"].append({"file_name": fname, "pdf_bytes": pdf_bytes})
                if is_ok:
                    job["done_files"].append((fname, pdf_bytes))
                    job["done_track_items"].append({"id": fid, "name": fname})
                else:
                    job["error_files"].append((fname, pdf_bytes))
                    job["error_details"].append({"File Name": fname, "Reason": err_msg})
                    job["error_track_items"].append({"id": fid, "name": fname})

        job["idx"] = idx + 1
        st.rerun()
        return

    # All PDFs read — finalize and save to Drive Excel
    st.session_state.pop("active_entry_job", None)
    extracted_rows = job["extracted_rows"]
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
            "target_folder_id": job["active_folder_id"],
            "folder_url": job["active_folder_url"],
            "done_items": job["done_track_items"],
            "error_items": job["error_track_items"],
            "copy_errors_to_folder": False,
        })

    save_and_record_batch(
        extracted_rows, job["done_files"], job["error_files"], job["error_details"], job["debug_list"],
        mode_tag="Mode 3 (Drive Excel)", is_direct_sheet=True, mode2_target_type="google_sheet",
        skip_duplicates=job["skip_duplicates"], drive_target_url=job["active_m3_excel_url"],
        drive_target_tab=st.session_state.mode3_excel_tab, is_mode3_excel_slot=True,
    )
    attach_retest_cache(job["retest_pdfs"], extracted_rows)
    st.session_state.drive_scan_info, st.session_state.drive_last_scan_key = None, ""
    st.rerun()


def render_mode3_workspace(ctx):
    """Renders Mode 3 (Google Drive Folder Scanner + Direct Drive Excel .xlsx entry)."""
    active_folder_url = st.session_state.health_folder_url
    active_m3_excel_url = st.session_state.mode3_excel_url

    if not active_m3_excel_url:
        st.warning("📊 Please link your Google Drive `.xlsx` Excel file first via **Left Sidebar → Mode 3 Drive Excel**.")
    if not active_folder_url:
        st.warning("📁 Please link your **`MEDICLAIM`** parent folder (or direct month folder) via **Left Sidebar → Drive Auto-Folders → Health**.")
        return

    # Restore last selected Year & Month from URL query params across browser F5 refresh
    if not st.session_state.drive_selected_year:
        qp_yr = _qp_get("yr", "").strip()
        qp_mo = _qp_get("mo", "").strip()
        if qp_yr:
            st.session_state.drive_selected_year = qp_yr
            if qp_mo:
                st.session_state.drive_selected_month = qp_mo

    curr_job = st.session_state.get("active_entry_job")
    if curr_job and curr_job.get("mode") != "mode3":
        st.session_state.pop("active_entry_job", None)
        curr_job = None

    desired_scan_key = f"{active_folder_url}||{st.session_state.drive_selected_year}||{st.session_state.drive_selected_month}"
    if not curr_job and (st.session_state.drive_scan_info is None or st.session_state.drive_last_scan_key != desired_scan_key):
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
                _qp_set("yr", st.session_state.drive_selected_year)
                _qp_set("mo", st.session_state.drive_selected_month)
                st.session_state.drive_last_scan_key = f"{active_folder_url}||{st.session_state.drive_selected_year}||{st.session_state.drive_selected_month}"
            else:
                st.session_state.drive_last_scan_key = desired_scan_key

    cancel_msg = st.session_state.pop("entry_cancel_notice", "")
    if cancel_msg:
        st.warning(cancel_msg)

    info = st.session_state.drive_scan_info or {}
    hdr1, hdr2 = st.columns([4, 1])
    with hdr1:
        st.subheader(f"📁 {info.get('active_path') or st.session_state.health_folder_name or 'Linked Drive Folder'}")
    with hdr2:
        if st.button("🔄 Scan Folder", use_container_width=True, disabled=bool(curr_job), key="rescan_drive_folder"):
            st.session_state.drive_scan_info, st.session_state.drive_last_scan_key = None, ""
            st.session_state.pop("last_results", None)
            st.rerun()

    if curr_job:
        _step_mode3_job(curr_job)
        return

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
            _qp_set("yr", chosen_yr)
            _qp_set("mo", "")
            st.session_state.pop("last_results", None)
            st.rerun()
        elif avail_months and chosen_mo != info.get("selected_month", ""):
            st.session_state.drive_selected_month, st.session_state.drive_scan_info = chosen_mo, None
            _qp_set("yr", chosen_yr)
            _qp_set("mo", chosen_mo)
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
        include_done = st.checkbox(f"Include previously entered PDFs ({len(already_done_files)}) in list", value=True, key="include_done_m3")
    else:
        st.success(f"📄 **{len(new_or_retry_files)} Pending PDFs** ready for processing...")

    candidate_files = all_drive_files if include_done else new_or_retry_files
    if not candidate_files:
        st.info("🎉 All PDFs in this folder have already been entered. Add new PDFs and click **Scan Folder**.")
        return

    # Smart daily-entry default: New/Error = Selected, Entered = Unselected
    list_sig = (
        f"M3|{info.get('active_folder_id', '')}|{include_done}|"
        + ",".join(f"{f['id']}:{f.get('last_status', '')}" for f in candidate_files)
    )
    if st.session_state.drive_pdf_list_sig != list_sig:
        st.session_state.drive_pdf_list_sig = list_sig
        st.session_state["drive_pdf_sel_mode"] = "new_only"
        all_are_pending = all(f.get("last_status") != "DONE" for f in candidate_files)
        st.session_state.drive_pdf_sel_default = all_are_pending
        st.session_state.m3_select_all_cb = all_are_pending
        st.session_state.drive_pdf_sel_ver += 1

    st.markdown(_POLICY_LIST_LOCK_CSS, unsafe_allow_html=True)
    components.html(_POLICY_LIST_WHEEL_LOCK_JS, height=0, scrolling=False)

    with st.expander(f"📋 Select Policy PDFs ({len(candidate_files)} available)", expanded=True):
        st.checkbox("☑️ Select All PDFs For Entry", key="m3_select_all_cb", on_change=_on_select_all_pdfs_change)
        df_selectable = pd.DataFrame([
            {
                "Select": _is_file_selected_default(f),
                "#": str(i + 1),
                "File Name": f["name"],
                "Status": "✅ Entered" if f.get("last_status") == "DONE" else ("⚠️ Prev Error" if f.get("last_status") == "ERROR" else "🆕 New"),
                "Modified": f.get("updated", ""),
            }
            for i, f in enumerate(candidate_files)
        ])
        visible_rows = min(len(candidate_files), 6)
        list_height = 38 + visible_rows * 35
        edited_df = st.data_editor(
            df_selectable,
            use_container_width=True,
            hide_index=True,
            height=list_height,
            disabled=["#", "File Name", "Status", "Modified"],
            column_config={
                "Select": st.column_config.CheckboxColumn("Select", default=False, width="small"),
                "#": st.column_config.TextColumn("#", width="small"),
                "File Name": st.column_config.TextColumn("File Name", width="large"),
                "Status": st.column_config.TextColumn("Status", width="small"),
                "Modified": st.column_config.TextColumn("Modified", width="medium"),
            },
            key=f"m3_pdf_editor_{st.session_state.drive_pdf_sel_ver}",
        )
        target_files = [candidate_files[i] for i in edited_df.index[edited_df["Select"] == True].tolist()]
        st.caption(
            f"✅ Selected for Entry: **{len(target_files)} / {len(candidate_files)} PDFs** "
            f"(🆕 New auto-selected; ✅ Entered unselected by default — tick manually anytime)"
        )

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
        st.session_state["active_entry_job"] = {
            "mode": "mode3",
            "target_files": target_files,
            "idx": 0,
            "master_df": get_active_master_df(ctx["manual_master_file"]),
            "accounts_df": get_active_accounts_df("health", ctx["manual_acc_files"]),
            "extracted_rows": [],
            "done_files": [],
            "error_files": [],
            "error_details": [],
            "debug_list": [],
            "done_track_items": [],
            "error_track_items": [],
            "retest_pdfs": [],
            "skip_duplicates": skip_duplicates_m3,
            "active_folder_id": info.get("active_folder_id", ""),
            "active_folder_url": active_folder_url,
            "active_m3_excel_url": active_m3_excel_url,
        }
        st.rerun()
