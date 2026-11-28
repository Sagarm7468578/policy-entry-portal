import html as _html
import os
import pandas as pd
import streamlit as st
from health_parser import OUTPUT_COLUMNS
from portal.backend import is_admin_user, load_saved_health_rows
from portal.bug_highlighter import render_preview_table
from portal.bug_pack_tester import render_resolved_bug_banner
from portal.retest_engine import run_preview_retest, parse_retest_row_numbers
from portal.mode3_drive import render_mode3_workspace
from portal.mode_bugging import render_bugging_workspace
from portal.mode12_upload import (
    render_upload_workspace,
    render_batch_history,
    render_mode1_cloud_sheet,
)

_FROZEN_HEADER_CSS = """
<style>
[data-testid="stMainBlockContainer"],
.block-container {
    padding-top: 3.7rem !important;
}
header[data-testid="stHeader"] {
    background: var(--background-color, #ffffff) !important;
}
[data-testid="stElementContainer"]:has(.pm-sticky-header),
.element-container:has(.pm-sticky-header) {
    position: sticky !important;
    top: 3.55rem !important;
    z-index: 990 !important;
    background: transparent !important;
}
.pm-sticky-header {
    position: relative;
    background: var(--background-color, #ffffff);
    padding: 8px 14px 10px 14px;
    margin-bottom: 6px;
    border-bottom: 1px solid #e2e8f0;
    box-shadow: 0 3px 8px -4px rgba(15, 23, 42, 0.14);
}
.pm-sticky-header::before {
    content: "";
    position: absolute;
    left: 0;
    right: 0;
    top: -4rem;
    height: 4rem;
    background: var(--background-color, #ffffff);
    pointer-events: none;
}
.pm-title {
    font-size: 2rem;
    font-weight: 700;
    line-height: 1.2;
    margin: 0 0 2px 0;
    color: var(--text-color, #0f172a);
}
.pm-subtitle {
    font-size: 0.875rem;
    color: #64748b;
    margin: 0 0 6px 0;
}
.pm-status-bar {
    font-size: 0.82rem;
    line-height: 1.65;
    color: #475569;
    margin: 0;
}
.pm-status-bar strong {
    color: var(--text-color, #1e293b);
}
.pm-status-bar code {
    background: var(--secondary-background-color, #f1f5f9);
    color: #0f766e;
    padding: 1px 5px;
    border-radius: 4px;
    font-size: 0.79rem;
}
.pm-sep {
    color: #cbd5e1;
    margin: 0 4px;
}
/* Hidden bridge controls for toolbar Re-Test Preview button (0px visual space) */
[data-testid="stElementContainer"]:has(.pm-hidden-retest-marker),
[data-testid="stElementContainer"]:has(.pm-hidden-retest-marker) + [data-testid="stElementContainer"],
[data-testid="stElementContainer"]:has(.pm-hidden-retest-marker) + [data-testid="stElementContainer"] + [data-testid="stElementContainer"] {
    position: absolute !important;
    width: 1px !important;
    height: 1px !important;
    overflow: hidden !important;
    opacity: 0 !important;
    pointer-events: none !important;
    margin: 0 !important;
    padding: 0 !important;
}
</style>
"""


def _pill(text: str) -> str:
    return f"<code>{_html.escape(str(text))}</code>"


def _build_status_bar_html(ctx, active_headers, is_custom_cols) -> str:
    is_mode2, is_mode3, is_bugging = ctx["is_mode2"], ctx["is_mode3"], ctx.get("is_bugging", False)
    if is_bugging:
        ps_label, ps_status = "Excel Save", "🚫 Disabled (Preview Only)"
    elif is_mode3:
        ps_label = "Drive Excel"
        ps_status = f"✅ {_pill(st.session_state.mode3_excel_name or 'Drive Excel (.xlsx)')}" if st.session_state.mode3_excel_url else "⚠️ Not Linked"
    elif is_mode2:
        ps_label = "Policy Sheet"
        if ctx["mode2_target_type"] == "local_excel":
            ps_status = f"✅ {_pill(os.path.basename(st.session_state.local_excel_path))}" if st.session_state.local_excel_path else "⚠️ Not Linked"
        else:
            ps_status = f"✅ {_pill(st.session_state.fixed_sheet_name or st.session_state.fixed_sheet_tab)}" if st.session_state.fixed_sheet_url else "⚠️ Not Linked"
    else:
        ps_label, ps_status = "Policy Sheet", "☁️ Cloud Master Sheet"

    manual_master = ctx["manual_master_file"]
    cm_status = (
        (f"✅ {ctx['m_count']} Clients" if not st.session_state.linked_master_error else "⚠️ Link Error")
        if st.session_state.client_master_url
        else (f"📄 {_pill(manual_master.name)}" if manual_master else "⚪ Not Linked")
    )
    h_acc_df = st.session_state.health_accounts_df
    h_acc_cnt = len(h_acc_df) if isinstance(h_acc_df, pd.DataFrame) else 0
    manual_h_acc = ctx["manual_acc_files"]["health"]
    acc_status = (
        (f"✅ {h_acc_cnt} Rules" if not st.session_state.health_accounts_error else "⚠️ Error")
        if st.session_state.health_accounts_url
        else (f"📄 {_pill(manual_h_acc.name)}" if manual_h_acc else "⚪ Not Linked")
    )
    rn_status = f"✅ {_pill(st.session_state.health_renewal_folder_name or 'Linked')}" if st.session_state.health_renewal_folder_url else "⚪ Not Linked"
    share_status = f"{st.session_state.health_share_under60 or '12'}% / {st.session_state.health_share_60plus or '8'}%"
    cols_status = f"🛠️ {len(active_headers)} Custom Cols" if is_custom_cols else f"🛠️ {len(OUTPUT_COLUMNS)} Default Cols"
    mode_short = (
        "🐞 Bugging Mode (Preview Only)"
        if is_bugging
        else ("Mode 3 (Drive Excel + Folder)" if is_mode3 else ("Mode 2 (Google Sheet)" if is_mode2 else "Mode 1 (Download)"))
    )

    parts = [f"<strong>Mode:</strong> {_html.escape(mode_short)}"]
    if is_mode3 or is_bugging:
        scan_inf = st.session_state.drive_scan_info or {}
        hf_nm = scan_inf.get("active_path") or st.session_state.health_folder_name or "Health Folder"
        folder_val = f"✅ {_pill(hf_nm)}" if st.session_state.health_folder_url else "⚠️ Not Linked"
        parts.append(f"<strong>PDF Folder:</strong> {folder_val}")

    parts.extend([
        f"<strong>{_html.escape(ps_label)}:</strong> {ps_status}",
        f"<strong>Client Master:</strong> {cm_status}",
        f"<strong>Accounts:</strong> {acc_status}",
        f"<strong>Renewal List:</strong> {rn_status}",
        f"<strong>Share %:</strong> {_pill(share_status)}",
        f"<strong>Format:</strong> {cols_status}",
    ])
    return "<span class='pm-sep'>|</span>".join(parts)


def _render_frozen_header(ctx, active_headers, is_custom_cols, show_status_bar=True):
    st.markdown(_FROZEN_HEADER_CSS, unsafe_allow_html=True)
    status_html = (
        f"<div class='pm-status-bar'>{_build_status_bar_html(ctx, active_headers, is_custom_cols)}</div>"
        if show_status_bar
        else ""
    )
    st.markdown(
        "<div class='pm-sticky-header'>"
        "  <div class='pm-title'><span class='pm-title-icon'>🛡️</span><span class='pm-title-text'>MS.Soft Policy Mitra</span></div>"
        "  <div class='pm-subtitle'>All-in-One Insurance Advisor Automation Suite</div>"
        f"  {status_html}"
        "</div>",
        unsafe_allow_html=True,
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
        batch_uid = f"{res['round_no']}_{res['timestamp']}"

        if is_bug_ui:
            st.subheader("🐞 Bugging Preview Mode")
            cached_cnt = len(res.get("retest_pdfs") or [])
            # Hidden bridge controls triggered by the "🔄 Re-Test Preview" button inside the toolbar
            st.markdown("<div class='pm-hidden-retest-marker'></div>", unsafe_allow_html=True)
            raw_row_spec = st.text_input(
                "🎯 Re-Test Rows",
                label_visibility="collapsed",
                key=f"retest_rows_inp_{batch_uid}",
            )
            if st.button(
                "PM_HIDDEN_RETEST_TRIGGER",
                disabled=not bool(res.get("retest_pdfs")),
                key=f"retest_preview_btn_{batch_uid}",
            ):
                target_indices = parse_retest_row_numbers(raw_row_spec, cached_cnt)
                run_preview_retest(ctx, res, target_indices=target_indices or None)
                st.rerun()

            if res.get("retest_count", 0) > 0:
                scope_txt = res.get("last_retest_scope") or ""
                scope_part = f" — {scope_txt}" if scope_txt else ""
                st.success(
                    f"🟢 Live Re-Test #{res['retest_count']} complete ({res.get('retest_time', '')}){scope_part}!"
                )
        else:
            st.subheader("Preview Mode")

        mode_label = res.get("mode_tag") or (
            "Mode 3 (Drive Excel)" if is_mode3 else ("Mode 2 (Fixed Sheet)" if ctx["is_mode2"] else "Mode 1 (Cloud Portal)")
        )
        render_preview_table(
            rows=res["batch_rows"],
            columns=res.get("batch_columns") or active_headers,
            batch_id=batch_uid,
            enable_highlighter=is_bug_ui,
            debug_list=res.get("debug_list", []),
            retest_count=int(res.get("retest_count", 0)),
            allow_user_report=not is_bug_ui,
            mode_tag=mode_label,
        )


def render_workspace(ctx, active_headers, is_custom_cols):
    if ctx["policy_category"] != "Health Insurance":
        _render_frozen_header(ctx, active_headers, is_custom_cols, show_status_bar=False)
        st.info(
            f"**{ctx['policy_category']}** module is under development. Please select **Health Insurance** to continue "
            f"(you can already pre-link Motor/SME Drive Folders, Accounts Masters, and Renewal Lists in the sidebar)."
        )
        st.stop()

    _render_frozen_header(ctx, active_headers, is_custom_cols, show_status_bar=True)
    _render_plan_load_warning()
    if not ctx.get("is_bugging"):
        render_resolved_bug_banner()

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
