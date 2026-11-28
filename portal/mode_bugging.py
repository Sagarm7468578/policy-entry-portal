import base64
from datetime import datetime, timedelta, timezone
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from health_parser import process_health_pdf, project_rows_to_schema
from portal.backend import (
    call_backend,
    apply_renewal_list_lookup,
    apply_share_commission,
    scan_drive_folder_pdfs,
)
from portal.state import (
    get_active_master_df,
    get_active_accounts_df,
)
from portal.retest_engine import get_skip_pdf_reason
from portal.bug_pack_tester import render_bug_pack_tester

IST = timezone(timedelta(hours=5, minutes=30))

_BUG_LIST_LOCK_CSS = """
<style>
[data-testid="stDataFrame"],
[data-testid="stDataFrame"] .dvn-scroller,
.stDataFrameGlideDataEditor,
.dvn-scroller {
    overscroll-behavior: contain !important;
}
</style>
"""

_BUG_LIST_WHEEL_LOCK_JS = """
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


def _on_bug_select_all_change():
    st.session_state.drive_pdf_sel_default = bool(st.session_state.get("bug_select_all_cb", True))
    st.session_state.drive_pdf_sel_ver += 1


def _cancel_bugging_job():
    job = st.session_state.pop("active_entry_job", None)
    done_so_far = job.get("idx", 0) if isinstance(job, dict) else 0
    total_cnt = len(job.get("target_files", [])) if isinstance(job, dict) else 0
    st.session_state["entry_cancel_notice"] = (
        f"🛑 Entry process cancelled ({done_so_far}/{total_cnt} PDFs read)."
    )


def _finalize_bugging_preview(extracted_rows, done_count, error_details, debug_list, retest_pdfs, total_count):
    """Stores extracted rows directly into Preview session state (ZERO Excel save & ZERO Drive status write)."""
    if extracted_rows:
        apply_share_commission(
            extracted_rows,
            st.session_state.health_share_under60,
            st.session_state.health_share_60plus,
        )

    if st.session_state.health_renewal_folder_url and extracted_rows:
        with st.spinner("Matching Renewal List PDFs for PYP Premium & Renewal Status..."):
            apply_renewal_list_lookup(extracted_rows, st.session_state.health_renewal_folder_url)

    proj_rows, proj_schema = project_rows_to_schema(extracted_rows, st.session_state.health_custom_columns)
    now_ist = datetime.now(IST)
    round_no = int(st.session_state.get("batch_round_counter", 0)) + 1
    st.session_state["batch_round_counter"] = round_no

    st.session_state["last_results"] = {
        "round_no": round_no,
        "timestamp": now_ist.strftime("%Y%m%d_%H%M%S"),
        "time_display": now_ist.strftime("%I:%M:%S %p"),
        "total_count": total_count,
        "done_count": done_count,
        "error_count": len(error_details),
        "error_details": error_details,
        "batch_rows": proj_rows,
        "batch_columns": proj_schema["headers"],
        "debug_list": debug_list,
        "retest_pdfs": retest_pdfs,
        "retest_count": 0,
        "retest_time": "",
        "skipped_count": 0,
        "round_excel_bytes": None,
        "err_zip_bytes": None,
        "save_error": "",
        "save_msg": "🐞 Bugging Preview Ready.",
        "mode_tag": "Bugging Mode (Preview Only)",
        "is_bugging_batch": True,
    }


def _step_bugging_job(job):
    """Processes 1 PDF per rerun so the '🛑 Cancel Entry Process' button stops the batch immediately."""
    target_files = job["target_files"]
    total = len(target_files)
    idx = job["idx"]

    c_prog, c_cancel = st.columns([3.4, 1.2])
    with c_prog:
        st.progress(min(idx / max(total, 1), 1.0))
        if idx < total:
            st.info(f"🐞 Bugging Preview ({idx + 1}/{total}): **{target_files[idx]['name']}**")
        else:
            st.info("🐞 Finalizing Bugging Preview...")
    with c_cancel:
        st.button(
            "🛑 Cancel Entry Process",
            use_container_width=True,
            key="btn_cancel_bug_entry",
            on_click=_cancel_bugging_job,
        )

    if idx < total:
        f_meta = target_files[idx]
        fname, fid = f_meta["name"], f_meta["id"]
        dl_res = call_backend({"action": "get_drive_pdf", "file_id": fid})
        if not dl_res.get("success") or not dl_res.get("content_b64"):
            job["error_details"].append({
                "File Name": fname,
                "Reason": dl_res.get("message", "Could not download PDF from Google Drive."),
            })
        else:
            pdf_bytes = base64.b64decode(dl_res["content_b64"])
            row_dict, is_ok, err_msg, debug_info = process_health_pdf(
                fname, pdf_bytes, job["master_df"], accounts_df=job["accounts_df"]
            )
            skip_reason = get_skip_pdf_reason(fname, is_ok, err_msg, debug_info)
            if skip_reason:
                job["error_details"].append({"File Name": fname, "Reason": skip_reason})
            else:
                job["debug_list"].append(debug_info)
                job["extracted_rows"].append(row_dict)
                job["retest_pdfs"].append({"file_name": fname, "pdf_bytes": pdf_bytes})
                if is_ok:
                    job["done_count"] += 1
                else:
                    job["error_details"].append({"File Name": fname, "Reason": err_msg})

        job["idx"] = idx + 1
        st.rerun()
        return

    st.session_state.pop("active_entry_job", None)
    _finalize_bugging_preview(
        job["extracted_rows"],
        job["done_count"],
        job["error_details"],
        job["debug_list"],
        job["retest_pdfs"],
        total,
    )
    st.rerun()


def _render_drive_bugging_tab(ctx):
    active_folder_url = st.session_state.health_folder_url
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
    if curr_job and curr_job.get("mode") != "bugging":
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
        st.subheader(f"🐞 {info.get('active_path') or st.session_state.health_folder_name or 'Linked Drive Folder'}")
    with hdr2:
        if st.button("🔄 Scan Folder", use_container_width=True, disabled=bool(curr_job), key="bug_rescan_drive_folder"):
            st.session_state.drive_scan_info, st.session_state.drive_last_scan_key = None, ""
            st.session_state.pop("last_results", None)
            st.rerun()

    if curr_job:
        _step_bugging_job(curr_job)
        return

    avail_years, avail_months = info.get("available_years", []), info.get("available_months", [])
    if avail_years:
        ym1, ym2 = st.columns(2)
        with ym1:
            yr_idx = avail_years.index(info.get("selected_year")) if info.get("selected_year") in avail_years else 0
            chosen_yr = st.selectbox("📅 Year Folder", avail_years, index=yr_idx, key="bug_sb_drive_year")
        with ym2:
            if avail_months:
                mo_idx = avail_months.index(info.get("selected_month")) if info.get("selected_month") in avail_months else 0
                chosen_mo = st.selectbox("📆 Month Folder", avail_months, index=mo_idx, key="bug_sb_drive_month")
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
    if not all_drive_files:
        st.info("✅ No PDF files found in this folder. Add Health Policy PDFs and click **Scan Folder**.")
        return

    st.success(f"📄 **{len(all_drive_files)} PDFs** loaded Only For Bugging Purpose.")

    list_sig = f"BUG|{info.get('active_folder_id', '')}|{','.join(f['id'] for f in all_drive_files)}"
    if st.session_state.drive_pdf_list_sig != list_sig:
        st.session_state.drive_pdf_list_sig = list_sig
        st.session_state.drive_pdf_sel_default = True
        st.session_state.bug_select_all_cb = True
        st.session_state.drive_pdf_sel_ver += 1

    st.markdown(_BUG_LIST_LOCK_CSS, unsafe_allow_html=True)
    components.html(_BUG_LIST_WHEEL_LOCK_JS, height=0, scrolling=False)

    with st.expander(f"📋 Select Policy PDFs for Bugging ({len(all_drive_files)} available)", expanded=True):
        st.checkbox("☑️ Select All PDFs For Bugging", key="bug_select_all_cb", on_change=_on_bug_select_all_change)
        df_selectable = pd.DataFrame([
            {
                "Select": st.session_state.drive_pdf_sel_default,
                "#": str(i + 1),
                "File Name": f["name"],
                "Status": "✅ Entered" if f.get("last_status") == "DONE" else ("⚠️ Prev Error" if f.get("last_status") == "ERROR" else "🆕 New"),
                "Modified": f.get("updated", ""),
            }
            for i, f in enumerate(all_drive_files)
        ])
        visible_rows = min(len(all_drive_files), 6)
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
            key=f"bug_pdf_editor_{st.session_state.drive_pdf_sel_ver}",
        )
        target_files = [all_drive_files[i] for i in edited_df.index[edited_df["Select"] == True].tolist()]
        st.caption(f"✅ Selected for Bugging: **{len(target_files)} / {len(all_drive_files)} PDFs**")

    if st.button(
        f"🐞 Run Bugging Preview on {len(target_files)} PDFs",
        type="primary",
        use_container_width=True,
        disabled=(len(target_files) == 0),
        key="start_bugging_drive_btn",
    ):
        st.session_state.pop("last_results", None)
        st.session_state["active_entry_job"] = {
            "mode": "bugging",
            "target_files": target_files,
            "idx": 0,
            "master_df": get_active_master_df(ctx["manual_master_file"]),
            "accounts_df": get_active_accounts_df("health", ctx["manual_acc_files"]),
            "extracted_rows": [],
            "error_details": [],
            "debug_list": [],
            "retest_pdfs": [],
            "done_count": 0,
        }
        st.rerun()


def render_bugging_workspace(ctx):
    """Admin-only Bugging Mode: Tab 1 = Drive Folder Bugging, Tab 2 = Zero-PDF User Bug Pack (.txt) Verifier."""
    tab_drive, tab_pack = st.tabs(["📁 Drive Folder Bugging", "🧪 Test User Bug Pack (.txt)"])
    with tab_drive:
        _render_drive_bugging_tab(ctx)
    with tab_pack:
        render_bug_pack_tester(ctx)
