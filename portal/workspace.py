import os
import pandas as pd
import streamlit as st
from health_parser import OUTPUT_COLUMNS
from portal.backend import is_admin_user, load_saved_health_rows
from portal.bug_highlighter import render_preview_table
from portal.retest_engine import run_preview_retest
from portal.mode3_drive import render_mode3_workspace
from portal.mode_bugging import render_bugging_workspace
from portal.mode12_upload import (
    render_upload_workspace,
    render_batch_history,
    render_mode1_cloud_sheet,
)


def _render_status_bar(ctx, active_headers, is_custom_cols):
    is_mode2, is_mode3, is_bugging = ctx["is_mode2"], ctx["is_mode3"], ctx.get("is_bugging", False)
    if is_bugging:
        ps_label, ps_status = "Excel Save", "🚫 Disabled (Preview Only)"
    elif is_mode3:
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
    mode_short = (
        "🐞 Bugging Mode (Preview Only)"
        if is_bugging
        else ("Mode 3 (Drive Excel + Folder)" if is_mode3 else ("Mode 2 (Google Sheet)" if is_mode2 else "Mode 1 (Download)"))
    )
    folder_part = ""
    if is_mode3 or is_bugging:
        scan_inf = st.session_state.drive_scan_info or {}
        hf_nm = scan_inf.get("active_path") or st.session_state.health_folder_name or "Health Folder"
        folder_part = f"  |  **PDF Folder:** {'✅ `' + hf_nm + '`' if st.session_state.health_folder_url else '⚠️ Not Linked'}"

    st.caption(
        f"**Mode:** {mode_short}{folder_part}  |  **{ps_label}:** {ps_status}  |  "
        f"**Client Master:** {cm_status}  |  **Accounts:** {acc_status}  |  "
        f"**Renewal List:** {rn_status}  |  **Share %:** `{share_status}`  |  **Format:** {cols_status}"
    )


def _render_plan_load_warning():
    """Admin-only safety banner if any file in health_parsers/plans/ failed to load."""
    if not is_admin_user():
        return
    try:
        from health_parsers.plans import PLAN_LOAD_ERRORS
        if PLAN_LOAD_ERRORS:
            details = " | ".join(f"`{m}.py`: {err}" for m, err in PLAN_LOAD_ERRORS.items())
            st.warning(f"⚠️ Plan Parser Load Notice: {details}")
    except Exception:
        pass


def _render_latest_batch(ctx, active_headers):
    if "last_results" not in st.session_state:
        return
    is_mode3 = ctx["is_mode3"]
    is_bugging = ctx.get("is_bugging", False)
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
    m3.metric("Skipped / Errors ❌", res["error_count"])

    if not is_mode3 and not is_bugging:
        z1, z2 = st.columns(2)
        with z1:
            if res.get("round_excel_bytes") and res.get("batch_rows"):
                st.download_button(
                    f"📊 Download Batch #{res['round_no']} Excel",
                    data=res["round_excel_bytes"],
                    file_name=f"Batch_{res['round_no']}_Health_Entries_{res['timestamp']}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    key=f"latest_xlsx_{res['round_no']}_{res['timestamp']}",
                )
        with z2:
            if res["err_zip_bytes"]:
                st.download_button(
                    f"⚠️ Download Batch #{res['round_no']} Error PDFs (ZIP)",
                    data=res["err_zip_bytes"],
                    file_name=f"Batch_{res['round_no']}_Error_Policies_{res['timestamp']}.zip",
                    mime="application/zip",
                    use_container_width=True,
                    key=f"latest_err_{res['round_no']}_{res['timestamp']}",
                )

    if res["error_details"]:
        st.warning("The following PDFs were skipped or had extraction issues (excluded from Excel & Preview Mode):")
        st.dataframe(pd.DataFrame(res["error_details"]), use_container_width=True, hide_index=True)

    # Preview Mode runs across ALL modes (Mode 1, Mode 2, Mode 3 + Admin Bugging Mode)
    if bool(res.get("batch_rows")):
        is_bug_ui = bool(is_admin_user() and (is_bugging or res.get("is_bugging_batch")))
        if is_bug_ui:
            p_hdr1, p_hdr2 = st.columns([3, 1.6])
            with p_hdr1:
                st.subheader("🐞 Bugging Preview Mode")
            with p_hdr2:
                has_cache = bool(res.get("retest_pdfs"))
                if st.button(
                    "🔄 Re-Test Preview",
                    use_container_width=True,
                    disabled=not has_cache,
                    help="Reloads latest GitHub parser fixes on current batch PDFs — fixed 🔴 cells auto-turn 🟢 Green!",
                    key=f"retest_preview_btn_{res['round_no']}_{res['timestamp']}",
                ):
                    run_preview_retest(ctx, res)
                    st.rerun()
            if res.get("retest_count", 0) > 0:
                st.success(
                    f"🟢 Live Re-Test #{res['retest_count']} complete ({res.get('retest_time', '')}) — "
                    f"Fixed 🔴 cells automatically turned 🟢 Green!"
                )
        else:
            st.subheader("Preview Mode")

        mode_label = res.get("mode_tag") or (
            "Mode 3 (Drive Excel)" if is_mode3 else ("Mode 2 (Fixed Sheet)" if ctx["is_mode2"] else "Mode 1 (Cloud Portal)")
        )
        render_preview_table(
            rows=res["batch_rows"],
            columns=res.get("batch_columns") or active_headers,
            batch_id=f"{res['round_no']}_{res['timestamp']}",
            enable_highlighter=is_bug_ui,
            debug_list=res.get("debug_list", []),
            retest_count=int(res.get("retest_count", 0)),
            allow_user_report=not is_bug_ui,
            mode_tag=mode_label,
        )


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

    if ctx.get("is_bugging"):
        render_bugging_workspace(ctx)
    elif ctx["is_mode3"]:
        render_mode3_workspace(ctx)
    else:
        render_upload_workspace(ctx)

    _render_latest_batch(ctx, active_headers)
    if not ctx["is_mode3"] and not ctx.get("is_bugging"):
        render_batch_history()
    if ctx["is_mode1"]:
        render_mode1_cloud_sheet()
