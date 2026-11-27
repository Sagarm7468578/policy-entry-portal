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


def _on_bug_select_all_change():
    st.session_state.drive_pdf_sel_default = bool(st.session_state.get("bug_select_all_cb", True))
    st.session_state.drive_pdf_sel_ver += 1


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
        "save_msg": f"🐞 Bugging Preview Ready ({len(proj_rows)} rows) — No Excel Save & No Drive Status Modified!",
        "mode_tag": "Bugging Mode (Preview Only)",
        "is_bugging_batch": True,
    }


def _render_drive_bugging_tab(ctx):
    active_folder_url = st.session_state.health_folder_url
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
        st.subheader(f"🐞 {info.get('active_path') or st.session_state.health_folder_name or 'Linked Drive Folder'}")
    with hdr2:
        if st.button("🔄 Scan Folder", use_container_width=True, key="bug_rescan_drive_folder"):
            st.session_state.drive_scan_info, st.session_state.drive_last_scan_key = None, ""
            st.session_state.pop("last_results", None)
            st.rerun()

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
    if not all_drive_files:
        st.info("✅ No PDF files found in this folder. Add Health Policy PDFs and click **Scan Folder**.")
        return

    st.success(f"📄 **{len(all_drive_files)} PDFs** loaded for fast Preview-Only Bugging (Excel & Drive status will NOT be touched).")

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
        f"🐞 Run Bugging Preview on {len(target_files)} PDFs (No Excel Save)",
        type="primary",
        use_container_width=True,
        disabled=(len(target_files) == 0),
        key="start_bugging_drive_btn",
    ):
        st.session_state.pop("last_results", None)
        master_df = get_active_master_df(ctx["manual_master_file"])
        accounts_df = get_active_accounts_df("health", ctx["manual_acc_files"])
        extracted_rows, error_details, debug_list, retest_pdfs = [], [], [], []
        done_count = 0

        progress, status_text = st.progress(0), st.empty()
        for idx, f_meta in enumerate(target_files):
            fname, fid = f_meta["name"], f_meta["id"]
            status_text.text(f"Bugging Preview ({idx + 1}/{len(target_files)}): {fname}")
            dl_res = call_backend({"action": "get_drive_pdf", "file_id": fid})
            if not dl_res.get("success") or not dl_res.get("content_b64"):
                error_details.append({"File Name": fname, "Reason": dl_res.get("message", "Could not download PDF from Google Drive.")})
                progress.progress((idx + 1) / len(target_files))
                continue

            pdf_bytes = base64.b64decode(dl_res["content_b64"])
            row_dict, is_ok, err_msg, debug_info = process_health_pdf(fname, pdf_bytes, master_df, accounts_df=accounts_df)

            skip_reason = get_skip_pdf_reason(fname, is_ok, err_msg, debug_info)
            if skip_reason:
                error_details.append({"File Name": fname, "Reason": skip_reason})
            else:
                debug_list.append(debug_info)
                extracted_rows.append(row_dict)
                retest_pdfs.append({"file_name": fname, "pdf_bytes": pdf_bytes})
                if is_ok:
                    done_count += 1
                else:
                    error_details.append({"File Name": fname, "Reason": err_msg})
            progress.progress((idx + 1) / len(target_files))

        status_text.empty()
        progress.empty()

        _finalize_bugging_preview(extracted_rows, done_count, error_details, debug_list, retest_pdfs, len(target_files))
        st.rerun()


def _render_upload_bugging_tab(ctx):
    uploaded_pdfs = st.file_uploader(
        "Upload Policy PDFs directly for instant Preview-Only Bugging (No Excel Save)",
        type=["pdf"],
        accept_multiple_files=True,
        key="bugging_quick_uploader",
    )
    if uploaded_pdfs:
        if st.button(
            f"🐞 Run Bugging Preview on {len(uploaded_pdfs)} Uploaded PDFs (No Excel Save)",
            type="primary",
            use_container_width=True,
            key="start_bugging_upload_btn",
        ):
            st.session_state.pop("last_results", None)
            master_df = get_active_master_df(ctx["manual_master_file"])
            accounts_df = get_active_accounts_df("health", ctx["manual_acc_files"])
            extracted_rows, error_details, debug_list, retest_pdfs = [], [], [], []
            done_count = 0

            progress, status_text = st.progress(0), st.empty()
            for idx, f_obj in enumerate(uploaded_pdfs):
                fname = f_obj.name
                status_text.text(f"Bugging Preview ({idx + 1}/{len(uploaded_pdfs)}): {fname}")
                pdf_bytes = f_obj.getvalue()
                row_dict, is_ok, err_msg, debug_info = process_health_pdf(fname, pdf_bytes, master_df, accounts_df=accounts_df)

                skip_reason = get_skip_pdf_reason(fname, is_ok, err_msg, debug_info)
                if skip_reason:
                    error_details.append({"File Name": fname, "Reason": skip_reason})
                else:
                    debug_list.append(debug_info)
                    extracted_rows.append(row_dict)
                    retest_pdfs.append({"file_name": fname, "pdf_bytes": pdf_bytes})
                    if is_ok:
                        done_count += 1
                    else:
                        error_details.append({"File Name": fname, "Reason": err_msg})
                progress.progress((idx + 1) / len(uploaded_pdfs))

            status_text.empty()
            progress.empty()

            _finalize_bugging_preview(extracted_rows, done_count, error_details, debug_list, retest_pdfs, len(uploaded_pdfs))
            st.rerun()


def render_bugging_workspace(ctx):
    """Admin-only fast Bugging Mode: Preview-only testing with ZERO Excel save and ZERO Drive status updates."""
    st.info("🐞 **Bugging Mode (Admin Only):** Fast Preview-Only testing — entries are **NOT** saved to Excel and Drive file statuses stay untouched.")
    tab_drive, tab_upload = st.tabs(["📁 Drive Folder Bugging", "📤 Quick Upload Bugging"])
    with tab_drive:
        _render_drive_bugging_tab(ctx)
    with tab_upload:
        _render_upload_bugging_tab(ctx)
