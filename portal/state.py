import io
import zipfile
from datetime import datetime, timedelta, timezone
import pandas as pd
import streamlit as st
from health_parser import (
    project_rows_to_schema,
    build_excel_bytes,
    append_rows_to_local_excel,
)
from portal.backend import (
    call_backend,
    load_user_sheet_settings,
    load_local_excel_path,
    fetch_linked_client_master,
    fetch_linked_accounts_master,
    save_rows_to_drive_target,
)
from portal.auth_wallet import (
    apply_login_session,
    render_portal_login_screen,
    charge_wallet_for_batch,
)

IST = timezone(timedelta(hours=5, minutes=30))
DEFAULT_HEALTH_EXCEL_NAME = "POLICY ENTRY SHEET FOR HEALTH.xlsx"
MAX_PDF_ROUNDS = 1

DEFAULTS = {
    "logged_in": False, "auth_method": "", "user_id": "", "user_email": "", "user_mobile": "", "user_name": "",
    "plan_type": "", "expiry": "", "wallet_balance": 0.0, "billable": False, "trial_expired": False,
    "google_auth_error": "", "pdf_uploader_key": 0, "col_editor_key": 0,
    "saved_health_rows": None, "batch_history": [], "round_counter": 0, "settings_loaded": False,
    "fixed_sheet_url": "", "fixed_sheet_tab": "Policy Entries", "fixed_sheet_name": "",
    "mode3_excel_url": "", "mode3_excel_tab": "", "mode3_excel_name": "",
    "client_master_url": "", "client_master_tab": "", "client_master_sheet_name": "",
    "health_accounts_url": "", "health_accounts_tab": "", "health_accounts_name": "", "health_accounts_df": None, "health_accounts_error": "",
    "motor_accounts_url": "", "motor_accounts_tab": "", "motor_accounts_name": "", "motor_accounts_df": None, "motor_accounts_error": "",
    "sme_accounts_url": "", "sme_accounts_tab": "", "sme_accounts_name": "", "sme_accounts_df": None, "sme_accounts_error": "",
    "health_renewal_folder_url": "", "health_renewal_folder_name": "",
    "motor_renewal_folder_url": "", "motor_renewal_folder_name": "",
    "sme_renewal_folder_url": "", "sme_renewal_folder_name": "",
    "health_share_under60": "12", "health_share_60plus": "8",
    "health_custom_columns": "",
    "health_folder_url": "", "health_folder_name": "",
    "motor_folder_url": "", "motor_folder_name": "",
    "sme_folder_url": "", "sme_folder_name": "",
    "drive_scan_info": None, "drive_scan_error": "", "drive_last_scan_key": "",
    "drive_selected_year": "", "drive_selected_month": "",
    "drive_pdf_sel_ver": 0, "drive_pdf_sel_default": True, "drive_pdf_list_sig": "",
    "quick_pdf_bytes_cache": {},
    "linked_master_df": None, "linked_master_error": "",
    "local_excel_path": "", "local_sheet_name": "Policy Entries",
}


def init_session_state():
    for k, v in DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v.copy() if isinstance(v, (dict, list)) else v


def is_google_auth_configured():
    try:
        return hasattr(st, "login") and "auth" in st.secrets
    except Exception:
        return False


def get_google_user_info():
    try:
        if hasattr(st, "user") and getattr(st.user, "is_logged_in", False):
            return True, str(st.user.get("email", "") or "").strip().lower(), str(st.user.get("name", "") or "").strip()
    except Exception:
        pass
    return False, "", ""


def handle_auto_google_login():
    google_configured = is_google_auth_configured()
    google_logged_in, g_email, g_name = get_google_user_info()
    if google_logged_in and g_email and not st.session_state.logged_in:
        with st.spinner("Verifying Google account..."):
            g_res = call_backend({"action": "google_login", "email": g_email, "name": g_name})
        if g_res.get("success"):
            apply_login_session("google", g_res, fallback_uid=g_email, fallback_email=g_email, fallback_name=g_name)
            st.rerun()
        else:
            st.session_state.google_auth_error = g_res.get("message", "Could not verify Google account.")
    return google_configured, google_logged_in, g_email


def render_login_screen(google_configured, google_logged_in, g_email):
    render_portal_login_screen(google_configured, google_logged_in, g_email)


def ensure_settings_loaded():
    if st.session_state.settings_loaded:
        return
    with st.spinner("Loading your linked sheets, masters, renewal lists, and Drive folders..."):
        cfg = load_user_sheet_settings(st.session_state.user_id)
        l_path, l_tab = load_local_excel_path()
        for k, v in cfg.items():
            st.session_state[k] = v
        st.session_state.local_excel_path, st.session_state.local_sheet_name = l_path, l_tab

        if st.session_state.client_master_url:
            m_df, m_name, m_err = fetch_linked_client_master(st.session_state.client_master_url, st.session_state.client_master_tab)
            st.session_state.linked_master_df, st.session_state.client_master_sheet_name, st.session_state.linked_master_error = m_df, m_name, m_err

        for ck in ("health", "motor", "sme"):
            if st.session_state[f"{ck}_accounts_url"]:
                a_df, a_name, a_err = fetch_linked_accounts_master(st.session_state[f"{ck}_accounts_url"], st.session_state[f"{ck}_accounts_tab"])
                st.session_state[f"{ck}_accounts_df"], st.session_state[f"{ck}_accounts_name"], st.session_state[f"{ck}_accounts_error"] = a_df, a_name, a_err

        st.session_state.settings_loaded = True


def get_active_master_df(manual_master_file):
    if st.session_state.client_master_url and isinstance(st.session_state.linked_master_df, pd.DataFrame):
        return st.session_state.linked_master_df
    if manual_master_file is not None:
        try:
            manual_master_file.seek(0)
            return pd.read_csv(manual_master_file, dtype=str) if manual_master_file.name.lower().endswith(".csv") else pd.read_excel(manual_master_file, dtype=str)
        except Exception as e:
            st.warning(f"Could not read Client Master ({e}). Proceeding without Client Master.")
    return None


def get_active_accounts_df(cat_key, manual_acc_files):
    if st.session_state.get(f"{cat_key}_accounts_url") and isinstance(st.session_state.get(f"{cat_key}_accounts_df"), pd.DataFrame):
        return st.session_state[f"{cat_key}_accounts_df"]
    up_file = manual_acc_files.get(cat_key)
    if up_file is not None:
        try:
            up_file.seek(0)
            return pd.read_csv(up_file, dtype=str) if up_file.name.lower().endswith(".csv") else pd.read_excel(up_file, dtype=str)
        except Exception as e:
            st.warning(f"Could not read Accounts Master ({e}). Proceeding without Accounts Master.")
    return None


def save_and_record_batch(
    extracted_rows, done_files, error_files, error_details, debug_list,
    mode_tag, is_direct_sheet, mode2_target_type, skip_duplicates,
    drive_target_url="", drive_target_tab="", is_mode3_excel_slot=False, move_msg="",
):
    projected_rows, used_schema = project_rows_to_schema(extracted_rows, st.session_state.health_custom_columns)
    save_msg, save_error, skipped_count = "", "", 0

    if not extracted_rows:
        save_msg = "No readable entries to save in this round (all selected PDFs were skipped as Scanned / Error)."
    elif is_direct_sheet:
        if mode2_target_type == "local_excel":
            with st.spinner("Saving entries to linked Local Excel (.xlsx)..."):
                ok, msg, added, skipped, total_cnt = append_rows_to_local_excel(
                    st.session_state.local_excel_path, projected_rows,
                    sheet_name=st.session_state.local_sheet_name, skip_duplicates=skip_duplicates,
                    custom_columns=used_schema["headers"], col_types=used_schema["col_types"],
                    policy_col=used_schema["policy_col"], expiry_col=used_schema["expiry_col"],
                )
            skipped_count = skipped
            save_msg, save_error = (f"✅ {mode_tag} Direct Save: {msg} (Total Entries: {total_cnt})", "") if ok else ("", f"❌ {msg}")
        else:
            with st.spinner("Saving entries directly to linked Google Drive Excel / Sheet..."):
                ok, s_msg, s_err, skipped_cnt, resolved_name = save_rows_to_drive_target(
                    drive_target_url, drive_target_tab, projected_rows, used_schema, skip_duplicates, mode_tag
                )
            skipped_count = skipped_cnt
            if resolved_name:
                st.session_state["mode3_excel_name" if is_mode3_excel_slot else "fixed_sheet_name"] = resolved_name
            save_msg, save_error = (s_msg, "") if ok else ("", s_err)
    else:
        if st.session_state.saved_health_rows is None:
            st.session_state.saved_health_rows = []
        existing_keys = {
            (str(r.get("Policy Number", "")).strip().lstrip(","), str(r.get("Expiry Date", "")).strip())
            for r in st.session_state.saved_health_rows if str(r.get("Policy Number", "")).strip()
        }
        new_rows_to_save = []
        for row_dict in extracted_rows:
            pno = str(row_dict.get("Policy Number", "")).strip().lstrip(",")
            key = (pno, str(row_dict.get("Expiry Date", "")).strip())
            if skip_duplicates and pno and key in existing_keys:
                skipped_count += 1
            else:
                new_rows_to_save.append(row_dict)
                if pno:
                    existing_keys.add(key)

        if new_rows_to_save:
            with st.spinner("Saving new entries to your Cloud Master Sheet..."):
                save_res = call_backend({"action": "save_health_entries", "user_id": st.session_state.user_id, "rows": new_rows_to_save})
            st.session_state.saved_health_rows.extend(new_rows_to_save)
            save_msg = (
                f"✅ Saved {len(new_rows_to_save)} new entries to '{DEFAULT_HEALTH_EXCEL_NAME}'."
                if save_res.get("success")
                else f"⚠️ Cloud sync notice ({save_res.get('message', '')}). Entries have been added to your current session."
            )

    if not mode_tag.startswith("Mode 3"):
        if move_msg and save_msg:
            save_msg = f"{save_msg}  \n{move_msg}"
        elif move_msg and not save_error:
            save_msg = move_msg

    now_ist = datetime.now(IST)
    st.session_state.round_counter += 1
    batch_ts = now_ist.strftime("%Y%m%d_%H%M%S")
    batch_uid = f"{st.session_state.round_counter}_{batch_ts}"

    # Charge ₹0.50 ONLY per successfully extracted, non-duplicate entry for Paid Wallet users
    billable_entries = max(0, len(done_files) - skipped_count)
    wallet_note = charge_wallet_for_batch(billable_entries, batch_uid) if not save_error else ""
    if wallet_note:
        save_msg = f"{save_msg}  \n{wallet_note}" if save_msg else wallet_note

    all_zip_buf = io.BytesIO()
    with zipfile.ZipFile(all_zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, fbytes in done_files:
            zf.writestr(f"Done/{fname}", fbytes)
        for fname, fbytes in error_files:
            if fbytes:
                zf.writestr(f"Error/{fname}", fbytes)

    err_zip_bytes = None
    valid_err_files = [(fn, fb) for fn, fb in error_files if fb]
    if valid_err_files:
        err_zip_buf = io.BytesIO()
        with zipfile.ZipFile(err_zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname, fbytes in valid_err_files:
                zf.writestr(fname, fbytes)
        err_zip_bytes = err_zip_buf.getvalue()

    batch_record = {
        "round_no": st.session_state.round_counter,
        "mode_used": mode_tag,
        "timestamp": batch_ts,
        "time_display": now_ist.strftime("%d-%m-%Y %I:%M:%S %p"),
        "total_count": len(done_files) + len(error_files),
        "done_count": len(done_files),
        "error_count": len(error_files),
        "skipped_count": skipped_count,
        "save_msg": save_msg,
        "save_error": save_error,
        "batch_rows": projected_rows,
        "batch_columns": used_schema["headers"],
        "round_excel_bytes": build_excel_bytes(projected_rows, columns=used_schema["headers"], col_types=used_schema["col_types"]) if projected_rows else b"",
        "error_details": error_details,
        "debug_list": debug_list,
        "all_zip_bytes": all_zip_buf.getvalue(),
        "err_zip_bytes": err_zip_bytes,
    }
    st.session_state.batch_history = [batch_record]
    st.session_state["last_results"] = batch_record
