import base64
import io
import json
import os
import zipfile
from datetime import datetime, timedelta, timezone
import pandas as pd
import requests
import streamlit as st
from health_parser import (
    OUTPUT_COLUMNS,
    ALL_SYSTEM_FIELDS,
    MONTH_NAMES_BY_NUM,
    normalize_custom_columns_spec,
    spec_to_multiline,
    get_custom_schema_info,
    project_rows_to_schema,
    process_health_pdf,
    parse_renewal_list_pdf,
    get_renewal_lookup_months,
    match_renewal_record,
    build_excel_bytes,
    build_sample_master_bytes,
    build_sample_accounts_master_bytes,
    read_excel_headers_from_bytes,
    append_rows_to_excel_bytes,
    append_rows_to_local_excel,
)

st.set_page_config(page_title="Policy Entry Portal", page_icon="📄", layout="wide")

WEB_APP_URL = st.secrets["WEB_APP_URL"]
SECRET_KEY = st.secrets["SECRET_KEY"]
IST = timezone(timedelta(hours=5, minutes=30))
DEFAULT_HEALTH_EXCEL_NAME = "POLICY ENTRY SHEET FOR HEALTH.xlsx"
MAX_PDF_ROUNDS = 5
IS_CLOUD = os.path.exists("/mount/src")
LOCAL_CONFIG_FILE = "mode2_local_config.json"

ADMIN_EMAILS = {"mahajansagar746@gmail.com"}
ADMIN_USER_IDS = {"mahajansagar746@gmail.com", "test01"}


def is_admin_user():
    email = str(st.session_state.get("user_email", "") or "").strip().lower()
    uid = str(st.session_state.get("user_id", "") or "").strip().lower()
    return (email in ADMIN_EMAILS) or (uid in ADMIN_USER_IDS)


def call_backend(payload, timeout=120):
    payload["secret"] = SECRET_KEY
    try:
        res = requests.post(WEB_APP_URL, json=payload, timeout=timeout)
        return res.json()
    except Exception as e:
        return {"success": False, "message": f"Connection error: {e}"}


def load_saved_health_rows(user_id):
    res = call_backend({"action": "get_health_entries", "user_id": user_id})
    if res.get("success"):
        return res.get("rows", []), ""
    return [], res.get("message", "Saved data load nahi ho paya.")


def load_user_sheet_settings(user_id):
    cfg = {
        "fixed_sheet_url": "", "fixed_sheet_tab": "Policy Entries",
        "client_master_url": "", "client_master_tab": "",
        "health_custom_columns": "",
        "health_folder_url": "", "motor_folder_url": "", "sme_folder_url": "",
        "mode3_excel_url": "", "mode3_excel_tab": "",
        "health_accounts_url": "", "health_accounts_tab": "",
        "motor_accounts_url": "", "motor_accounts_tab": "",
        "sme_accounts_url": "", "sme_accounts_tab": "",
        "health_renewal_folder_url": "", "motor_renewal_folder_url": "", "sme_renewal_folder_url": "",
    }
    res = call_backend({"action": "get_user_settings", "user_id": user_id})
    if res.get("success"):
        for k in cfg:
            val = res.get(k, cfg[k])
            cfg[k] = val if (val or k != "fixed_sheet_tab") else "Policy Entries"
    return cfg


def save_user_sheet_settings(user_id, **kwargs):
    payload = {"action": "save_user_settings", "user_id": user_id}
    payload.update(kwargs)
    return call_backend(payload)


def fetch_linked_client_master(sheet_url, sheet_tab=""):
    if not sheet_url:
        return None, "", ""
    res = call_backend({"action": "get_client_master", "sheet_url": sheet_url.strip(), "sheet_tab": (sheet_tab or "").strip()})
    if not res.get("success"):
        return None, "", res.get("message", "Client Master Google Sheet load nahi ho payi.")
    headers, rows = res.get("headers", []), res.get("rows", [])
    sheet_name = res.get("sheet_name", "Client Master Sheet")
    return (pd.DataFrame(rows, columns=headers, dtype=str) if headers else pd.DataFrame()), sheet_name, ""


def fetch_linked_accounts_master(sheet_url, sheet_tab=""):
    if not sheet_url:
        return None, "", ""
    res = call_backend({"action": "get_accounts_master", "sheet_url": sheet_url.strip(), "sheet_tab": (sheet_tab or "").strip()})
    if not res.get("success"):
        return None, "", res.get("message", "Accounts Master sheet load nahi ho payi.")

    sheet_name = res.get("sheet_name", "Accounts Master")
    if res.get("is_excel") and res.get("content_b64"):
        try:
            raw = base64.b64decode(res["content_b64"])
            tab_req = (sheet_tab or "").strip()
            df = pd.read_excel(io.BytesIO(raw), sheet_name=tab_req, dtype=str) if tab_req else pd.read_excel(io.BytesIO(raw), dtype=str)
            df = df.dropna(how="all")
            cols_low = {str(c).strip().lower() for c in df.columns}
            ok_cols = (
                any(k in cols_low for k in ("company name", "company", "insurer", "insurance company"))
                and any(k in cols_low for k in ("agency", "agency name", "intermediary", "agent", "broker"))
                and any(k in cols_low for k in ("accounts", "account", "account name"))
            )
            if not ok_cols:
                return None, sheet_name, "Accounts Master me 'Company Name', 'Agency', aur 'Accounts' columns Row 1 me hone chahiye."
            return df, sheet_name, ""
        except Exception as e:
            return None, sheet_name, f"Accounts Master Excel read error: {e}"

    headers, rows = res.get("headers", []), res.get("rows", [])
    return (pd.DataFrame(rows, columns=headers, dtype=str) if headers else pd.DataFrame()), sheet_name, ""


def apply_renewal_list_lookup(extracted_rows, renewal_folder_url):
    clean_url = str(renewal_folder_url or "").strip()
    if not clean_url or not extracted_rows:
        return

    month_cache = {}

    def get_month_records(year_int, month_int):
        cache_key = (year_int, month_int)
        if cache_key in month_cache:
            return month_cache[cache_key]
        m_full, m_short = MONTH_NAMES_BY_NUM.get(month_int, ("", ""))
        if not m_full:
            month_cache[cache_key] = []
            return []
        res = call_backend({
            "action": "get_renewal_list_pdfs",
            "folder_url": clean_url,
            "year": str(year_int),
            "month_name": m_full,
            "month_short": m_short,
        })
        recs = []
        if res.get("success"):
            for f_obj in res.get("files", []):
                b64 = f_obj.get("content_b64", "")
                if b64:
                    try:
                        recs.extend(parse_renewal_list_pdf(base64.b64decode(b64)))
                    except Exception:
                        pass
        month_cache[cache_key] = recs
        return recs

    for row_dict in extracted_rows:
        matched_rec = None
        for yr, mo in get_renewal_lookup_months(row_dict):
            matched_rec = match_renewal_record(row_dict, get_month_records(yr, mo))
            if matched_rec:
                break
        if matched_rec:
            row_dict["PYP premium"] = matched_rec.get("premium", "")
            row_dict["OUR RENEWAL"] = "YES"
        else:
            row_dict["PYP premium"] = ""
            row_dict["OUR RENEWAL"] = "NO"


def scan_drive_folder_pdfs(user_id, folder_url, year_folder="", month_folder=""):
    if not folder_url:
        return None, "Drive folder link nahi hai."
    res = call_backend({
        "action": "list_drive_pdfs", "user_id": user_id,
        "folder_url": folder_url.strip(),
        "year_folder": (year_folder or "").strip(),
        "month_folder": (month_folder or "").strip(),
    })
    if not res.get("success"):
        return None, res.get("message", "Google Drive folder scan nahi ho paya.")
    return {
        "root_folder_name": res.get("root_folder_name", ""),
        "active_folder_id": res.get("active_folder_id", ""),
        "active_folder_name": res.get("active_folder_name", "Drive Folder"),
        "active_path": res.get("active_path", res.get("active_folder_name", "Drive Folder")),
        "available_years": res.get("available_years", []),
        "available_months": res.get("available_months", []),
        "selected_year": res.get("selected_year", ""),
        "selected_month": res.get("selected_month", ""),
        "files": res.get("files", []),
    }, ""


def fetch_headers_from_drive_target(target_url, target_tab=""):
    g_res = call_backend({"action": "get_drive_excel", "sheet_url": target_url.strip()})
    if not g_res.get("success"):
        return [], g_res.get("message", "File access nahi ho payi.")
    if g_res.get("is_google_sheet"):
        h_res = call_backend({"action": "get_sheet_headers", "sheet_url": target_url.strip(), "sheet_tab": target_tab.strip()})
        if h_res.get("success") and h_res.get("headers"):
            return h_res["headers"], ""
        return [], h_res.get("message", "Sheet ki Row 1 khali hai.")
    hdrs, _, err = read_excel_headers_from_bytes(base64.b64decode(g_res["content_b64"]), target_tab)
    if err:
        return [], err
    return (hdrs, "") if hdrs else ([], "Excel file ki Row 1 abhi khali hai.")


def save_rows_to_drive_target(target_url, target_tab, projected_rows, used_schema, skip_duplicates, mode_tag):
    probe = call_backend({"action": "get_drive_excel", "sheet_url": target_url.strip()})
    if not probe.get("success"):
        return False, "", f"❌ Target file open nahi hui: {probe.get('message', 'Unknown error')}", 0, ""

    if probe.get("is_google_sheet"):
        g_res = call_backend({
            "action": "append_to_fixed_sheet", "user_id": st.session_state.user_id,
            "sheet_url": target_url.strip(), "sheet_tab": target_tab.strip() or "Policy Entries",
            "skip_duplicates": skip_duplicates, "custom_columns": used_schema["headers"],
            "col_types": used_schema["col_types"], "policy_col": used_schema["policy_col"],
            "expiry_col": used_schema["expiry_col"], "rows": projected_rows,
        })
        if g_res.get("success"):
            skipped_cnt, added_cnt = g_res.get("skipped", 0), g_res.get("added", 0)
            s_name, t_name = g_res.get("sheet_name", "Google Sheet"), g_res.get("tab_name", target_tab or "Policy Entries")
            msg = "ENTRY DONE PLS RECHECK NOW" if mode_tag.startswith("Mode 3") else f"✅ {mode_tag} Direct Save: {added_cnt} nayi entries seedha '{s_name} → {t_name}' me save ho gayi! (Total Entries: {g_res.get('total_rows', '')})"
            return True, msg, "", skipped_cnt, s_name
        return False, "", f"❌ Google Sheet save fail: {g_res.get('message', 'Unknown error')}", 0, ""

    file_name = probe.get("file_name", "Excel File.xlsx")
    file_id = probe.get("file_id", "")
    mime_type = probe.get("mime_type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    ok, err_msg, updated_bytes, added_cnt, skipped_cnt, total_cnt, used_tab = append_rows_to_excel_bytes(
        excel_bytes=base64.b64decode(probe["content_b64"]),
        rows=projected_rows, sheet_name=target_tab.strip(), skip_duplicates=skip_duplicates,
        custom_columns=used_schema["headers"], col_types=used_schema["col_types"],
        policy_col=used_schema["policy_col"], expiry_col=used_schema["expiry_col"],
        keep_vba=file_name.lower().endswith(".xlsm"),
    )
    if not ok:
        return False, "", f"❌ {err_msg}", skipped_cnt, file_name
    if added_cnt == 0:
        msg = "ENTRY DONE PLS RECHECK NOW" if mode_tag.startswith("Mode 3") else f"✅ {mode_tag}: Koi nayi entry add nahi hui ({skipped_cnt} duplicates pehle se '{file_name}' me saved the)."
        return True, msg, "", skipped_cnt, file_name

    up_res = call_backend({
        "action": "update_drive_excel", "file_id": file_id,
        "mime_type": mime_type, "content_b64": base64.b64encode(updated_bytes).decode("ascii"),
    }, timeout=120)
    if up_res.get("success"):
        msg = "ENTRY DONE PLS RECHECK NOW" if mode_tag.startswith("Mode 3") else f"✅ {mode_tag} Direct Excel Save: **{added_cnt}** nayi entries seedha `{file_name}` (Tab: `{used_tab}`) me save ho gayi! (Total Entries: **{total_cnt}**)"
        return True, msg, "", skipped_cnt, file_name
    return False, "", f"❌ Google Drive Excel update fail: {up_res.get('message', 'Unknown error')}", skipped_cnt, file_name


def load_local_excel_path():
    if IS_CLOUD or not os.path.exists(LOCAL_CONFIG_FILE):
        return "", "Policy Entries"
    try:
        with open(LOCAL_CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("local_excel_path", ""), cfg.get("local_sheet_name", "Policy Entries")
    except Exception:
        return "", "Policy Entries"


def save_local_excel_path(path_str, sheet_name):
    if IS_CLOUD:
        return
    try:
        with open(LOCAL_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"local_excel_path": path_str.strip(), "local_sheet_name": sheet_name.strip() or "Policy Entries"}, f, indent=2)
    except Exception:
        pass


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


def get_active_master_df(manual_master_file):
    if st.session_state.client_master_url and isinstance(st.session_state.linked_master_df, pd.DataFrame):
        return st.session_state.linked_master_df
    if manual_master_file is not None:
        try:
            manual_master_file.seek(0)
            return pd.read_csv(manual_master_file, dtype=str) if manual_master_file.name.lower().endswith(".csv") else pd.read_excel(manual_master_file, dtype=str)
        except Exception as e:
            st.warning(f"Client Master read nahi ho payi ({e}). Bina master ke entry kar rahe hain.")
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
            st.warning(f"Accounts Master read nahi ho payi ({e}). Bina Accounts Master ke entry kar rahe hain.")
    return None


def save_and_record_batch(
    extracted_rows, done_files, error_files, error_details, debug_list,
    mode_tag, is_direct_sheet, mode2_target_type, skip_duplicates,
    drive_target_url="", drive_target_tab="", is_mode3_excel_slot=False, move_msg="",
):
    projected_rows, used_schema = project_rows_to_schema(extracted_rows, st.session_state.health_custom_columns)
    save_msg, save_error, skipped_count = "", "", 0

    if is_direct_sheet:
        if mode2_target_type == "local_excel":
            with st.spinner("Fixed Local Excel (.xlsx) me save ho raha hai..."):
                ok, msg, added, skipped, total_cnt = append_rows_to_local_excel(
                    st.session_state.local_excel_path, projected_rows,
                    sheet_name=st.session_state.local_sheet_name, skip_duplicates=skip_duplicates,
                    custom_columns=used_schema["headers"], col_types=used_schema["col_types"],
                    policy_col=used_schema["policy_col"], expiry_col=used_schema["expiry_col"],
                )
            skipped_count = skipped
            save_msg, save_error = (f"✅ {mode_tag} Direct Save: {msg} (Total Entries: {total_cnt})", "") if ok else ("", f"❌ {msg}")
        else:
            with st.spinner("Aapki Linked Google Drive Excel / Sheet me save ho raha hai..."):
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
            with st.spinner("Nayi entries aapki Mode 1 master sheet me save ho rahi hain..."):
                save_res = call_backend({"action": "save_health_entries", "user_id": st.session_state.user_id, "rows": new_rows_to_save})
            st.session_state.saved_health_rows.extend(new_rows_to_save)
            save_msg = (
                f"✅ {len(new_rows_to_save)} nayi entries '{DEFAULT_HEALTH_EXCEL_NAME}' me save ho gayi!"
                if save_res.get("success")
                else f"⚠️ Cloud save notice ({save_res.get('message', '')}), entries session me add ho gayi hain."
            )

    if not mode_tag.startswith("Mode 3"):
        if move_msg and save_msg:
            save_msg = f"{save_msg}  \n{move_msg}"
        elif move_msg and not save_error:
            save_msg = move_msg

    all_zip_buf = io.BytesIO()
    with zipfile.ZipFile(all_zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, fbytes in done_files:
            zf.writestr(f"Done/{fname}", fbytes)
        for fname, fbytes in error_files:
            zf.writestr(f"Error/{fname}", fbytes)

    err_zip_bytes = None
    if error_files:
        err_zip_buf = io.BytesIO()
        with zipfile.ZipFile(err_zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname, fbytes in error_files:
                zf.writestr(fname, fbytes)
        err_zip_bytes = err_zip_buf.getvalue()

    now_ist = datetime.now(IST)
    st.session_state.round_counter += 1
    batch_record = {
        "round_no": st.session_state.round_counter,
        "mode_used": mode_tag,
        "timestamp": now_ist.strftime("%Y%m%d_%H%M%S"),
        "time_display": now_ist.strftime("%d-%m-%Y %I:%M:%S %p"),
        "total_count": len(done_files) + len(error_files),
        "done_count": len(done_files),
        "error_count": len(error_files),
        "skipped_count": skipped_count,
        "save_msg": save_msg,
        "save_error": save_error,
        "batch_rows": projected_rows,
        "batch_columns": used_schema["headers"],
        "round_excel_bytes": build_excel_bytes(projected_rows, columns=used_schema["headers"], col_types=used_schema["col_types"]),
        "error_details": error_details,
        "debug_list": debug_list,
        "all_zip_bytes": all_zip_buf.getvalue(),
        "err_zip_bytes": err_zip_bytes,
    }
    st.session_state.batch_history.insert(0, batch_record)
    st.session_state.batch_history = st.session_state.batch_history[:MAX_PDF_ROUNDS]
    st.session_state["last_results"] = batch_record


def _on_select_all_pdfs_change():
    st.session_state.drive_pdf_sel_default = bool(st.session_state.get("m3_select_all_cb", True))
    st.session_state.drive_pdf_sel_ver += 1


def render_category_folder_panel(title, caption, folder_specs, expanded=False, reset_health_scan=False, footer_tip=""):
    linked_cnt = sum(bool(st.session_state[u_key]) for _, u_key, _ in folder_specs)
    badge = f"✅ {linked_cnt}/3 Linked" if linked_cnt > 0 else "⚪ Not Linked"
    with st.expander(f"{title} ({badge})", expanded=expanded):
        st.caption(caption)
        tabs = st.tabs(["🏥 Health", "🚗 Motor", "🏢 SME"])
        for tab_ui, (cat_label, url_key, name_key) in zip(tabs, folder_specs):
            with tab_ui:
                curr_url, curr_name = st.session_state[url_key], st.session_state[name_key]
                if curr_url:
                    disp_nm = f"**{curr_name}**  \n" if curr_name else ""
                    st.success(f"{disp_nm}✅ {cat_label} Folder Linked")
                    if curr_url.startswith("http"):
                        st.link_button(f"🔗 Open {cat_label} Folder", curr_url, use_container_width=True)
                    if st.button(f"🔓 Unlink {cat_label}", use_container_width=True, key=f"unlink_{url_key}"):
                        with st.spinner("Unlink ho raha hai..."):
                            u_res = save_user_sheet_settings(st.session_state.user_id, **{url_key: ""})
                        if u_res.get("success"):
                            st.session_state[url_key] = st.session_state[name_key] = ""
                            if reset_health_scan and url_key == "health_folder_url":
                                st.session_state.update({"drive_scan_info": None, "drive_last_scan_key": "", "drive_selected_year": "", "drive_selected_month": ""})
                            st.rerun()
                        else:
                            st.error(u_res.get("message", "Unlink nahi ho paya."))
                else:
                    f_inp = st.text_input(f"{cat_label} Drive Folder Link", placeholder="https://drive.google.com/drive/folders/...", key=f"inp_{url_key}")
                    if st.button(f"🔗 Link {cat_label} Folder", type="primary", use_container_width=True, key=f"btn_{url_key}"):
                        clean_f = f_inp.strip()
                        if not clean_f:
                            st.warning("Google Drive Folder link dalein.")
                        else:
                            with st.spinner("Folder verify & link ho raha hai..."):
                                v_res = call_backend({"action": "verify_drive_folder", "folder_url": clean_f})
                                if not v_res.get("success"):
                                    st.error(v_res.get("message", "Folder access nahi ho paya. Folder ko Viewer/Editor share karein."))
                                else:
                                    s_res = save_user_sheet_settings(st.session_state.user_id, **{url_key: clean_f})
                                    if s_res.get("success"):
                                        st.session_state[url_key], st.session_state[name_key] = clean_f, v_res.get("folder_name", "")
                                        if reset_health_scan and url_key == "health_folder_url":
                                            st.session_state.update({"drive_scan_info": None, "drive_last_scan_key": "", "drive_selected_year": "", "drive_selected_month": ""})
                                        st.rerun()
                                    else:
                                        st.error(s_res.get("message", "Save nahi ho paya."))
                    if footer_tip:
                        st.caption(footer_tip)


# --- SESSION STATE INITIALIZATION ---
defaults = {
    "logged_in": False, "auth_method": "", "user_id": "", "user_email": "", "user_name": "",
    "expiry": "", "google_auth_error": "", "pdf_uploader_key": 0, "col_editor_key": 0,
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
    "health_custom_columns": "",
    "health_folder_url": "", "health_folder_name": "",
    "motor_folder_url": "", "motor_folder_name": "",
    "sme_folder_url": "", "sme_folder_name": "",
    "drive_scan_info": None, "drive_scan_error": "", "drive_last_scan_key": "",
    "drive_selected_year": "", "drive_selected_month": "",
    "drive_pdf_sel_ver": 0, "drive_pdf_sel_default": True, "drive_pdf_list_sig": "",
    "linked_master_df": None, "linked_master_error": "",
    "local_excel_path": "", "local_sheet_name": "Policy Entries",
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# --- AUTO-RESTORE GOOGLE LOGIN ---
google_configured = is_google_auth_configured()
google_logged_in, g_email, g_name = get_google_user_info()

if google_logged_in and g_email and not st.session_state.logged_in:
    with st.spinner("Google account verify ho raha hai..."):
        g_res = call_backend({"action": "google_login", "email": g_email})
    if g_res.get("success"):
        st.session_state.update({
            "logged_in": True, "auth_method": "google",
            "user_id": g_res.get("user_id", g_email), "user_email": g_email, "user_name": g_name,
            "expiry": g_res.get("expiry", ""), "google_auth_error": "",
            "saved_health_rows": None, "settings_loaded": False,
            "linked_master_df": None, "linked_master_error": "",
            "health_accounts_df": None, "motor_accounts_df": None, "sme_accounts_df": None,
            "drive_scan_info": None, "drive_last_scan_key": "", "batch_history": [], "round_counter": 0,
        })
        st.rerun()
    else:
        st.session_state.google_auth_error = g_res.get("message", "Yeh Gmail account registered/active nahi hai.")


# --- LOGIN SCREEN ---
if not st.session_state.logged_in:
    _, col2, _ = st.columns([1, 2, 1])
    with col2:
        st.title("🔐 Policy Entry Software Login")
        if google_logged_in and st.session_state.google_auth_error:
            st.error(f"❌ **{g_email}**: {st.session_state.google_auth_error}")
            st.info("Agar aapne apna plan activate karwa liya hai, to Admin se is Gmail ko `Users` sheet me add karwayein ya dusre Gmail se login karein.")
            if st.button("🔄 Dusre Google Account se Login Karein", type="primary", use_container_width=True):
                st.session_state.google_auth_error = ""
                st.logout()
        elif google_configured:
            st.write("Ek baar Google se login karein — jab tak aap Logout nahi karenge, portal hamesha logged in rahega.")
            if st.button("🔵 Continue with Google", type="primary", use_container_width=True):
                st.login()
        else:
            st.warning("⚠️ Google Login abhi Streamlit Secrets (`[auth]`) me configure nahi hua hai. Neeche Password se login kar sakte hain.")

        st.divider()
        with st.expander("🔑 User ID & Password se Login (Backup Option)", expanded=not google_configured):
            with st.form("login_form"):
                user_id = st.text_input("User ID")
                password = st.text_input("Password", type="password")
                if st.form_submit_button("Login", use_container_width=True):
                    if not user_id or not password:
                        st.warning("User ID aur Password dono bharein.")
                    else:
                        with st.spinner("Check kar rahe hain..."):
                            result = call_backend({"action": "login", "user_id": user_id, "password": password})
                        if result.get("success"):
                            st.session_state.update({
                                "logged_in": True, "auth_method": "password",
                                "user_id": user_id.strip(), "user_email": "", "user_name": "",
                                "expiry": result.get("expiry", ""), "saved_health_rows": None,
                                "settings_loaded": False, "linked_master_df": None, "linked_master_error": "",
                                "health_accounts_df": None, "motor_accounts_df": None, "sme_accounts_df": None,
                                "drive_scan_info": None, "drive_last_scan_key": "", "batch_history": [], "round_counter": 0,
                            })
                            st.rerun()
                        else:
                            st.error(result.get("message", "Login fail ho gaya."))


# --- MAIN POLICY ENTRY DASHBOARD ---
else:
    if not st.session_state.settings_loaded:
        with st.spinner("Aapki linked sheets, Accounts Masters, Renewal Lists aur folders load ho rahe hain..."):
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

    active_schema = get_custom_schema_info(st.session_state.health_custom_columns)
    active_headers = active_schema["headers"]
    is_custom_cols = bool(st.session_state.health_custom_columns.strip())

    mode2_target_type = "google_sheet"
    manual_master_file = None
    manual_acc_files = {"health": None, "motor": None, "sme": None}

    # --- SIDEBAR ---
    with st.sidebar:
        display_user = st.session_state.user_name or st.session_state.user_id
        email_line = f"  \n📧 `{st.session_state.user_email}`" if st.session_state.user_email else ""
        st.success(f"👤 **{display_user}**{email_line}  \n📅 Valid Till: **{st.session_state.expiry}**")

        default_mode_idx = 2 if (st.session_state.health_folder_url or st.session_state.mode3_excel_url) else (1 if (st.session_state.fixed_sheet_url or st.session_state.local_excel_path) else 0)
        working_mode = st.radio(
            "⚙️ Working Mode",
            ["Mode 1: Cloud Portal (Excel Download)", "Mode 2: Fixed Google Sheet (Upload)", "Mode 3: Drive Folder + Drive Excel (.xlsx)"],
            index=default_mode_idx,
        )
        is_mode1, is_mode2, is_mode3 = working_mode.startswith("Mode 1"), working_mode.startswith("Mode 2"), working_mode.startswith("Mode 3")
        is_direct_sheet = is_mode2 or is_mode3
        policy_category = st.selectbox("📂 Policy Type", ["Health Insurance", "Motor Insurance (Coming Soon)", "SME Insurance (Coming Soon)"])
        st.divider()

        # 1. MODE 3: DRIVE EXCEL + AUTO-FOLDERS
        if is_mode3:
            is_m3_excel_linked = bool(st.session_state.mode3_excel_url)
            with st.expander(f"📊 Mode 3 Drive Excel ({'✅ Linked' if is_m3_excel_linked else '⚪ Not Linked'})", expanded=not is_m3_excel_linked):
                if is_m3_excel_linked:
                    ex_title = f"**{st.session_state.mode3_excel_name}**  \n" if st.session_state.mode3_excel_name else ""
                    st.success(f"{ex_title}📑 Tab: `{st.session_state.mode3_excel_tab or '1st Tab (Auto)'}`  \nDirect in-place `.xlsx` auto-save active!")
                    if st.session_state.mode3_excel_url.startswith("http"):
                        st.link_button("🔗 Open Drive Excel File", st.session_state.mode3_excel_url, use_container_width=True)
                    if st.button("🔓 Unlink Drive Excel", use_container_width=True, key="unlink_m3_excel"):
                        with st.spinner("Unlink ho raha hai..."):
                            u_res = save_user_sheet_settings(st.session_state.user_id, mode3_excel_url="", mode3_excel_tab="")
                        if u_res.get("success"):
                            st.session_state.mode3_excel_url = st.session_state.mode3_excel_tab = st.session_state.mode3_excel_name = ""
                            st.rerun()
                        else:
                            st.error(u_res.get("message", "Unlink nahi ho paya."))
                else:
                    m3_url_inp = st.text_input("Google Drive Excel (.xlsx) Link", placeholder="https://drive.google.com/file/d/.../view", key="m3_excel_url_input")
                    m3_tab_inp = st.text_input("Excel Sheet Tab (Blank = 1st Tab)", value="", key="m3_excel_tab_input")
                    if st.button("🔗 Link Drive Excel Permanently", type="primary", use_container_width=True, key="btn_link_m3_excel"):
                        clean_u, clean_t = m3_url_inp.strip(), m3_tab_inp.strip()
                        if not clean_u:
                            st.warning("Apni Google Drive `.xlsx` Excel file ka Share Link dalein.")
                        else:
                            with st.spinner("Google Drive Excel verify & link ho rahi hai..."):
                                v_res = call_backend({"action": "verify_sheet", "sheet_url": clean_u})
                                if not v_res.get("success"):
                                    st.error(v_res.get("message", "Excel file access nahi ho payi."))
                                else:
                                    s_res = save_user_sheet_settings(st.session_state.user_id, mode3_excel_url=clean_u, mode3_excel_tab=clean_t)
                                    if s_res.get("success"):
                                        st.session_state.mode3_excel_url, st.session_state.mode3_excel_tab, st.session_state.mode3_excel_name = clean_u, clean_t, v_res.get("sheet_name", "")
                                        st.rerun()
                                    else:
                                        st.error(s_res.get("message", "Save nahi ho paya."))
                    st.caption("💡 Google Drive me `.xlsx` file par Right-click → Share (Editor) → Copy link yahan paste karein.")

            render_category_folder_panel(
                title="📁 Drive Auto-Folders",
                caption="Main parent folder (`MEDICLAIM` / `MOTOR` / `SME`) ya direct month folder (`NOVEMBER 2026`) ka link 1 baar dalein.",
                folder_specs=[
                    ("Health", "health_folder_url", "health_folder_name"),
                    ("Motor", "motor_folder_url", "motor_folder_name"),
                    ("SME", "sme_folder_url", "sme_folder_name"),
                ],
                expanded=not bool(st.session_state.health_folder_url),
                reset_health_scan=True,
            )

        # 2. MODE 2: POLICY ENTRY SHEET
        if is_mode2:
            is_policy_linked = bool(st.session_state.fixed_sheet_url or (not IS_CLOUD and st.session_state.local_excel_path))
            with st.expander(f"🎯 Policy Entry Sheet ({'✅ Linked' if is_policy_linked else '⚪ Not Linked'})", expanded=not is_policy_linked):
                target_options = ["☁️ Google Sheet / Drive Excel"] if IS_CLOUD else ["💻 Local PC Excel (.xlsx)", "☁️ Google Sheet / Drive Excel"]
                chosen_target = st.radio("Save Destination", target_options, key="sidebar_mode2_target")
                if chosen_target.startswith("💻"):
                    mode2_target_type = "local_excel"
                    if st.session_state.local_excel_path:
                        st.success(f"**Local Excel Linked**  \n`{os.path.basename(st.session_state.local_excel_path)}`  \n📑 Tab: `{st.session_state.local_sheet_name}`")
                        if st.button("🔓 Unlink Excel", use_container_width=True, key="unlink_local_excel"):
                            st.session_state.local_excel_path = ""
                            save_local_excel_path("", "Policy Entries")
                            st.rerun()
                    else:
                        l_path_inp = st.text_input("Fixed Excel Path (.xlsx)", placeholder=r"I:\My Drive\POLICY ENTRY EXCEL\HEALTH.xlsx", key="sb_local_path_input")
                        l_tab_inp = st.text_input("Sheet Tab Name", value="Policy Entries", key="sb_local_tab_input")
                        if st.button("🔗 Link Path", type="primary", use_container_width=True):
                            clean_p = l_path_inp.strip().strip('"')
                            if not clean_p:
                                st.warning("Path dalein.")
                            else:
                                st.session_state.local_excel_path = clean_p
                                st.session_state.local_sheet_name = l_tab_inp.strip() or "Policy Entries"
                                save_local_excel_path(clean_p, st.session_state.local_sheet_name)
                                st.rerun()
                else:
                    mode2_target_type = "google_sheet"
                    if st.session_state.fixed_sheet_url:
                        title_txt = f"**{st.session_state.fixed_sheet_name}**  \n" if st.session_state.fixed_sheet_name else ""
                        st.success(f"{title_txt}📑 Tab: `{st.session_state.fixed_sheet_tab}`  \nAuto-save active (Zero download)")
                        if st.session_state.fixed_sheet_url.startswith("http"):
                            st.link_button("🔗 Open Policy Sheet", st.session_state.fixed_sheet_url, use_container_width=True)
                        if st.button("🔓 Unlink Policy Sheet", use_container_width=True, key="unlink_policy_gsheet"):
                            with st.spinner("Unlink kar rahe hain..."):
                                u_res = save_user_sheet_settings(st.session_state.user_id, fixed_sheet_url="", fixed_sheet_tab="Policy Entries")
                            if u_res.get("success"):
                                st.session_state.fixed_sheet_url, st.session_state.fixed_sheet_tab, st.session_state.fixed_sheet_name = "", "Policy Entries", ""
                                st.rerun()
                            else:
                                st.error(u_res.get("message", "Unlink nahi ho paya."))
                    else:
                        s_url_inp = st.text_input("Policy Sheet / Drive Excel URL", placeholder="https://docs.google.com/spreadsheets/d/...", key="policy_sheet_url_input")
                        s_tab_inp = st.text_input("Sheet Tab Name", value=st.session_state.fixed_sheet_tab or "Policy Entries", key="policy_sheet_tab_input")
                        if st.button("🔗 Link Policy Sheet", type="primary", use_container_width=True):
                            clean_url, clean_tab = s_url_inp.strip(), s_tab_inp.strip() or "Policy Entries"
                            if not clean_url:
                                st.warning("Google Sheet ya Drive Excel URL dalein.")
                            else:
                                with st.spinner("Verify & link ho raha hai..."):
                                    v_res = call_backend({"action": "verify_sheet", "sheet_url": clean_url})
                                    if not v_res.get("success"):
                                        st.error(v_res.get("message", "File access nahi ho payi."))
                                    else:
                                        s_res = save_user_sheet_settings(st.session_state.user_id, fixed_sheet_url=clean_url, fixed_sheet_tab=clean_tab)
                                        if s_res.get("success"):
                                            st.session_state.fixed_sheet_url, st.session_state.fixed_sheet_tab, st.session_state.fixed_sheet_name = clean_url, clean_tab, v_res.get("sheet_name", "")
                                            st.rerun()
                                        else:
                                            st.error(s_res.get("message", "Save nahi ho paya."))
                        st.caption("💡 File ko Editor permission ke saath share karein.")

        # 3. CLIENT MASTER PANEL
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
                        with st.spinner("Refresh ho raha hai..."):
                            m_df, m_name, m_err = fetch_linked_client_master(st.session_state.client_master_url, st.session_state.client_master_tab)
                            st.session_state.linked_master_df, st.session_state.client_master_sheet_name, st.session_state.linked_master_error = m_df, m_name, m_err
                        st.rerun()
                with mc2:
                    if st.button("🔓 Unlink", use_container_width=True, key="unlink_client_master"):
                        with st.spinner("Unlink ho raha hai..."):
                            u_res = save_user_sheet_settings(st.session_state.user_id, client_master_url="", client_master_tab="")
                        if u_res.get("success"):
                            st.session_state.client_master_url = st.session_state.client_master_tab = st.session_state.client_master_sheet_name = st.session_state.linked_master_error = ""
                            st.session_state.linked_master_df = None
                            st.rerun()
                        else:
                            st.error(u_res.get("message", "Unlink nahi ho paya."))
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
                            st.warning("Client Master link dalein.")
                        else:
                            with st.spinner("Verify & link ho raha hai..."):
                                m_df, m_name, m_err = fetch_linked_client_master(clean_cm_url, clean_cm_tab)
                                if m_err:
                                    st.error(m_err)
                                else:
                                    s_res = save_user_sheet_settings(st.session_state.user_id, client_master_url=clean_cm_url, client_master_tab=clean_cm_tab)
                                    if s_res.get("success"):
                                        st.session_state.client_master_url, st.session_state.client_master_tab, st.session_state.client_master_sheet_name, st.session_state.linked_master_df, st.session_state.linked_master_error = clean_cm_url, clean_cm_tab, m_name, m_df, ""
                                        st.rerun()
                                    else:
                                        st.error(s_res.get("message", "Save nahi ho paya."))
                with cm_tab2:
                    manual_master_file = st.file_uploader("Upload Master (.xlsx / .csv)", type=["xlsx", "csv"], key="client_master_uploader")

        # 4. ACCOUNTS MASTER PANEL (HEALTH / MOTOR / SME)
        acc_linked_cnt = sum(bool(st.session_state[f"{ck}_accounts_url"]) for ck in ("health", "motor", "sme"))
        with st.expander(f"🏦 Accounts Master ({f'✅ {acc_linked_cnt}/3 Linked' if acc_linked_cnt else '⚪ Not Linked'})", expanded=False):
            st.caption("Health, Motor aur SME teeno ke liye alag-alag Accounts Master sheet (`Company Name`, `Agency`, `Accounts`) link karein.")
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
                                with st.spinner(f"{cat_label} Accounts refresh ho raha hai..."):
                                    a_df, a_name, a_err = fetch_linked_accounts_master(curr_url, st.session_state[t_key])
                                    st.session_state[d_key], st.session_state[n_key], st.session_state[e_key] = a_df, a_name, a_err
                                st.rerun()
                        with ac2:
                            if st.button("🔓 Unlink", use_container_width=True, key=f"unlink_acc_{ck}"):
                                with st.spinner("Unlink ho raha hai..."):
                                    u_res = save_user_sheet_settings(st.session_state.user_id, **{u_key: "", t_key: ""})
                                if u_res.get("success"):
                                    st.session_state[u_key] = st.session_state[t_key] = st.session_state[n_key] = st.session_state[e_key] = ""
                                    st.session_state[d_key] = None
                                    st.rerun()
                                else:
                                    st.error(u_res.get("message", "Unlink nahi ho paya."))
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
                                    st.warning(f"{cat_label} Accounts Master link dalein.")
                                else:
                                    with st.spinner(f"{cat_label} Accounts Master verify & link ho raha hai..."):
                                        a_df, a_name, a_err = fetch_linked_accounts_master(clean_au, clean_at)
                                        if a_err:
                                            st.error(a_err)
                                        else:
                                            s_res = save_user_sheet_settings(st.session_state.user_id, **{u_key: clean_au, t_key: clean_at})
                                            if s_res.get("success"):
                                                st.session_state[u_key], st.session_state[t_key], st.session_state[n_key], st.session_state[d_key], st.session_state[e_key] = clean_au, clean_at, a_name, a_df, ""
                                                st.rerun()
                                            else:
                                                st.error(s_res.get("message", "Save nahi ho paya."))
                        with src_t2:
                            manual_acc_files[ck] = st.file_uploader(f"Upload {cat_label} Accounts (.xlsx / .csv)", type=["xlsx", "csv"], key=f"upload_acc_{ck}")

        # 5. RENEWAL LIST PANEL (HEALTH / MOTOR / SME)
        render_category_folder_panel(
            title="🔄 Renewal List",
            caption="Health, Motor aur SME ka Renewal List PDF folder (`GIC RENEWALS/HEALTH` ya `2026`) link karein.  \nMatch hone par `PYP premium` auto-fill hoga aur `OUR RENEWAL` = `YES` (warna `NO`).",
            folder_specs=[
                ("Health", "health_renewal_folder_url", "health_renewal_folder_name"),
                ("Motor", "motor_renewal_folder_url", "motor_renewal_folder_name"),
                ("SME", "sme_renewal_folder_url", "sme_renewal_folder_name"),
            ],
            expanded=False,
            footer_tip="💡 Main category folder (`HEALTH`) link karne par har saal (`2026`, `2027`...) auto-detect hoga.",
        )

        # 6. CUSTOM SHEET COLUMNS PANEL
        col_badge = f"Custom: {len(active_headers)}" if is_custom_cols else f"Default: {len(OUTPUT_COLUMNS)}"
        with st.expander(f"🛠️ Sheet Columns ({col_badge})", expanded=False):
            st.caption(
                "Har line me 1 column likhein (exact order me).  \n"
                "• Auto-fill fields: Client Name, Policy Number, Occupation, Accounts, PYP premium, etc.  \n"
                "• Manual/Blank column: Bas naam likh dein (e.g. `Mail`, `Print`, `Folder`)  \n"
                "• Header rename: `Client Name => Insured Name`"
            )
            import_src_url = st.session_state.mode3_excel_url if is_mode3 else st.session_state.fixed_sheet_url
            import_src_tab = st.session_state.mode3_excel_tab if is_mode3 else st.session_state.fixed_sheet_tab
            if is_direct_sheet and mode2_target_type == "google_sheet" and import_src_url:
                if st.button("📥 Linked Sheet/Excel se Headers Import Karein", use_container_width=True, key="import_sheet_hdrs"):
                    with st.spinner("Row 1 headers padh rahe hain..."):
                        imp_hdrs, imp_err = fetch_headers_from_drive_target(import_src_url, import_src_tab)
                    if imp_hdrs:
                        imported_spec = normalize_custom_columns_spec("\n".join(imp_hdrs))
                        s_res = save_user_sheet_settings(st.session_state.user_id, health_custom_columns=imported_spec)
                        if s_res.get("success"):
                            st.session_state.health_custom_columns = imported_spec
                            st.session_state.col_editor_key += 1
                            st.rerun()
                        else:
                            st.error(s_res.get("message", "Save nahi ho paya."))
                    else:
                        st.warning(imp_err or "Row 1 khali hai — neeche manually columns paste karke Save karein.")

            cols_text = st.text_area("Apne Columns (1 per line)", value=spec_to_multiline(st.session_state.health_custom_columns), height=240, key=f"custom_cols_textarea_{st.session_state.col_editor_key}")
            cc1, cc2 = st.columns(2)
            with cc1:
                if st.button("💾 Save", type="primary", use_container_width=True, key="save_custom_cols"):
                    norm_spec = normalize_custom_columns_spec(cols_text)
                    with st.spinner("Columns save ho rahe hain..."):
                        s_res = save_user_sheet_settings(st.session_state.user_id, health_custom_columns=norm_spec)
                    if s_res.get("success"):
                        st.session_state.health_custom_columns = norm_spec
                        st.session_state.col_editor_key += 1
                        st.rerun()
                    else:
                        st.error(s_res.get("message", "Save nahi ho paya."))
            with cc2:
                if st.button("🔄 Reset", use_container_width=True, key="reset_custom_cols"):
                    with st.spinner("Default columns reset ho rahe hain..."):
                        s_res = save_user_sheet_settings(st.session_state.user_id, health_custom_columns="")
                    if s_res.get("success"):
                        st.session_state.health_custom_columns = ""
                        st.session_state.col_editor_key += 1
                        st.rerun()
                    else:
                        st.error(s_res.get("message", "Reset nahi ho paya."))
            with st.popover("📋 Available Auto-Fill Fields", use_container_width=True):
                st.write(", ".join(ALL_SYSTEM_FIELDS))

        st.divider()
        st.download_button("📋 Sample Client Master", data=build_sample_master_bytes(), file_name="Sample_Client_Master.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        st.download_button("🏦 Sample Accounts Master", data=build_sample_accounts_master_bytes(), file_name="Sample_Accounts_Master.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        if st.button("🚪 Logout", use_container_width=True):
            was_google = st.session_state.auth_method == "google"
            for k, v in defaults.items():
                st.session_state[k] = v
            st.session_state.pop("last_results", None)
            if was_google and google_configured:
                st.logout()
            else:
                st.rerun()

    # --- CLEAN MAIN WORKSPACE ---
    st.title("📄 Automatic Policy Entry Portal")

    if policy_category != "Health Insurance":
        st.info(f"**{policy_category}** abhi setup ho raha hai. Filhaal **Health Insurance** chunein (aap abhi se sidebar me Motor/SME Drive Folder, Accounts Master aur Renewal List link karke rakh sakte hain).")
        st.stop()

    # 1-Line Compact Status Bar
    if is_mode3:
        ps_label = "Drive Excel"
        ps_status = f"✅ `{st.session_state.mode3_excel_name or 'Drive Excel (.xlsx)'}`" if st.session_state.mode3_excel_url else "⚠️ Not Linked"
    elif is_mode2:
        ps_label = "Policy Sheet"
        if mode2_target_type == "local_excel":
            ps_status = f"✅ `{os.path.basename(st.session_state.local_excel_path)}`" if st.session_state.local_excel_path else "⚠️ Not Linked"
        else:
            ps_status = f"✅ `{st.session_state.fixed_sheet_name or st.session_state.fixed_sheet_tab}`" if st.session_state.fixed_sheet_url else "⚠️ Not Linked"
    else:
        ps_label, ps_status = "Policy Sheet", "☁️ Mode 1 Cloud Sheet"

    cm_status = (f"✅ {m_count} Clients" if not st.session_state.linked_master_error else "⚠️ Link Error") if st.session_state.client_master_url else (f"📄 `{manual_master_file.name}`" if manual_master_file else "⚪ Not Linked")
    h_acc_df = st.session_state.health_accounts_df
    h_acc_cnt = len(h_acc_df) if isinstance(h_acc_df, pd.DataFrame) else 0
    acc_status = (f"✅ {h_acc_cnt} Rules" if not st.session_state.health_accounts_error else "⚠️ Error") if st.session_state.health_accounts_url else (f"📄 `{manual_acc_files['health'].name}`" if manual_acc_files["health"] else "⚪ Not Linked")
    rn_status = f"✅ `{st.session_state.health_renewal_folder_name or 'Linked'}`" if st.session_state.health_renewal_folder_url else "⚪ Not Linked"
    cols_status = f"🛠️ {len(active_headers)} Custom Cols" if is_custom_cols else f"🛠️ {len(OUTPUT_COLUMNS)} Default Cols"
    mode_short = "Mode 3 (Drive Excel + Folder)" if is_mode3 else ("Mode 2 (Google Sheet)" if is_mode2 else "Mode 1 (Download)")
    folder_part = ""
    if is_mode3:
        scan_inf = st.session_state.drive_scan_info or {}
        hf_nm = scan_inf.get("active_path") or st.session_state.health_folder_name or "Health Folder"
        folder_part = f"  |  **PDF Folder:** {'✅ `' + hf_nm + '`' if st.session_state.health_folder_url else '⚠️ Not Linked'}"

    st.caption(f"**Mode:** {mode_short}{folder_part}  |  **{ps_label}:** {ps_status}  |  **Client Master:** {cm_status}  |  **Accounts:** {acc_status}  |  **Renewal List:** {rn_status}  |  **Format:** {cols_status}")

    if is_mode1 and st.session_state.saved_health_rows is None:
        with st.spinner("Aapki purani saved Health Sheet load ho rahi hai..."):
            loaded_rows, load_err = load_saved_health_rows(st.session_state.user_id)
            st.session_state.saved_health_rows = loaded_rows
            if load_err:
                st.warning(f"⚠️ Cloud sheet load notice: {load_err}")

    # ==========================================================
    # MODE 3 WORKSPACE: GOOGLE DRIVE FOLDER + DRIVE EXCEL (.xlsx)
    # ==========================================================
    if is_mode3:
        active_folder_url = st.session_state.health_folder_url
        active_m3_excel_url = st.session_state.mode3_excel_url

        if not active_m3_excel_url:
            st.warning("📊 Pehle Left Sidebar → **📊 Mode 3 Drive Excel** me apni Google Drive wali `.xlsx` Excel file ka Share Link 1 baar save karein.")

        if not active_folder_url:
            st.warning("📁 PDF auto-scan ke liye Left Sidebar → **📁 Drive Auto-Folders → 🏥 Health** me apna **`MEDICLAIM`** main folder (ya direct `NOVEMBER 2026` folder) link karein.")
        else:
            desired_scan_key = f"{active_folder_url}||{st.session_state.drive_selected_year}||{st.session_state.drive_selected_month}"
            if st.session_state.drive_scan_info is None or st.session_state.drive_last_scan_key != desired_scan_key:
                with st.spinner("Google Drive folder scan ho raha hai..."):
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
                        st.caption("Is year folder me koi month subfolder nahi mila.")

                if chosen_yr != info.get("selected_year", ""):
                    st.session_state.drive_selected_year, st.session_state.drive_selected_month, st.session_state.drive_scan_info = chosen_yr, "", None
                    st.rerun()
                elif avail_months and chosen_mo != info.get("selected_month", ""):
                    st.session_state.drive_selected_month, st.session_state.drive_scan_info = chosen_mo, None
                    st.rerun()

            if st.session_state.drive_scan_error:
                st.error(f"⚠️ {st.session_state.drive_scan_error}")
            else:
                all_drive_files = info.get("files", [])
                new_or_retry_files = [f for f in all_drive_files if f.get("last_status") != "DONE"]
                already_done_files = [f for f in all_drive_files if f.get("last_status") == "DONE"]

                if not all_drive_files:
                    st.info("✅ Is folder me abhi koi PDF file nahi hai. Nayi Health PDFs folder me dalein aur **🔄 Scan Folder** dabayein.")
                else:
                    include_done = True
                    if already_done_files:
                        st.success(f"📄 Total Folder PDFs: **{len(all_drive_files)}**  |  🆕 New / Pending: **{len(new_or_retry_files)}**  |  ✅ Already Entered (Safe in Folder): **{len(already_done_files)}**")
                        include_done = st.checkbox(f"Already-entered ({len(already_done_files)}) PDFs ko bhi dobara process karein", value=True, key="include_done_m3")
                    else:
                        st.success(f"📄 **{len(new_or_retry_files)} Pending PDFs** ready hain (Original PDFs apni jagah safe rahengi!)")

                    candidate_files = all_drive_files if include_done else new_or_retry_files
                    if not candidate_files:
                        st.info("🎉 Is folder ki saari PDFs pehle hi enter ho chuki hain! Nayi PDF aane par bas **🔄 Scan Folder** dabayein.")
                    else:
                        list_sig = f"{info.get('active_folder_id', '')}|{include_done}|{','.join(f['id'] for f in candidate_files)}"
                        if st.session_state.drive_pdf_list_sig != list_sig:
                            st.session_state.drive_pdf_list_sig = list_sig
                            st.session_state.drive_pdf_sel_default = True
                            st.session_state.m3_select_all_cb = True
                            st.session_state.drive_pdf_sel_ver += 1

                        with st.expander(f"📋 Folder ki PDFs Select Karein ({len(candidate_files)} available)", expanded=True):
                            st.checkbox("☑️ Select All PDFs (Tick = Sab Select | Untick = Sab Unselect)", key="m3_select_all_cb", on_change=_on_select_all_pdfs_change)
                            df_selectable = pd.DataFrame([
                                {
                                    "Select": st.session_state.drive_pdf_sel_default, "#": i + 1, "File Name": f["name"],
                                    "Status": "✅ Entered" if f.get("last_status") == "DONE" else ("⚠️ Prev Error" if f.get("last_status") == "ERROR" else "🆕 New"),
                                    "Size (KB)": f.get("size_kb", ""), "Modified": f.get("updated", ""),
                                }
                                for i, f in enumerate(candidate_files)
                            ])
                            edited_df = st.data_editor(
                                df_selectable, use_container_width=True, hide_index=True,
                                disabled=["#", "File Name", "Status", "Size (KB)", "Modified"],
                                column_config={"Select": st.column_config.CheckboxColumn("Select", default=True, width="small"), "#": st.column_config.NumberColumn("#", width="small")},
                                key=f"m3_pdf_editor_{st.session_state.drive_pdf_sel_ver}",
                            )
                            target_files = [candidate_files[i] for i in edited_df.index[edited_df["Select"] == True].tolist()]
                            st.caption(f"✅ Selected for Entry: **{len(target_files)} / {len(candidate_files)} PDFs**")

                        opt1, opt2 = st.columns(2)
                        with opt1:
                            skip_duplicates_m3 = st.checkbox("Duplicate Policy auto-skip karein", value=False, key="skip_dup_m3")
                        with opt2:
                            copy_errors_drive = st.checkbox("Error PDFs ki COPY `Error/` folder me bhejein (Original wahi rahegi, Done move nahi hogi)", value=True, key="copy_err_m3")

                        if st.button(f"🚀 Process {len(target_files)} Selected PDFs & Direct Save in Drive Excel (.xlsx)", type="primary", use_container_width=True, disabled=(len(target_files) == 0), key="start_mode3_btn"):
                            if not active_m3_excel_url:
                                st.warning("Mode 3 ke liye pehle Left Sidebar → **📊 Mode 3 Drive Excel** me apni Google Drive `.xlsx` file link karein.")
                            elif not target_files:
                                st.warning("Kam se kam ek PDF par tick lagayein.")
                            else:
                                master_df = get_active_master_df(manual_master_file)
                                accounts_df = get_active_accounts_df("health", manual_acc_files)
                                extracted_rows, done_files, error_files, error_details, debug_list = [], [], [], [], []
                                done_track_items, error_track_items = [], []

                                progress, status_text = st.progress(0), st.empty()
                                for idx, f_meta in enumerate(target_files):
                                    fname, fid = f_meta["name"], f_meta["id"]
                                    status_text.text(f"Drive se read ho raha hai ({idx + 1}/{len(target_files)}): {fname}")
                                    dl_res = call_backend({"action": "get_drive_pdf", "file_id": fid})
                                    if not dl_res.get("success") or not dl_res.get("content_b64"):
                                        err_reason = dl_res.get("message", "Drive se PDF download nahi ho payi")
                                        error_details.append({"File Name": fname, "Reason": err_reason})
                                        error_track_items.append({"id": fid, "name": fname})
                                        debug_list.append({"file_name": fname, "client_name": fname, "detected_company": "", "company_scores": {}, "raw_text": "", "error_reason": err_reason})
                                        progress.progress((idx + 1) / len(target_files))
                                        continue

                                    pdf_bytes = base64.b64decode(dl_res["content_b64"])
                                    row_dict, is_ok, err_msg, debug_info = process_health_pdf(fname, pdf_bytes, master_df, accounts_df=accounts_df)
                                    debug_list.append(debug_info)
                                    extracted_rows.append(row_dict)
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

                                if st.session_state.health_renewal_folder_url and extracted_rows:
                                    with st.spinner("Renewal List PDFs se PYP premium & OUR RENEWAL check ho raha hai..."):
                                        apply_renewal_list_lookup(extracted_rows, st.session_state.health_renewal_folder_url)

                                with st.spinner("Drive status update & Error PDFs ki copy bana rahe hain..."):
                                    call_backend({
                                        "action": "finalize_drive_batch", "user_id": st.session_state.user_id,
                                        "target_folder_id": info.get("active_folder_id", ""), "folder_url": active_folder_url,
                                        "done_items": done_track_items, "error_items": error_track_items,
                                        "copy_errors_to_folder": copy_errors_drive,
                                    })

                                save_and_record_batch(
                                    extracted_rows, done_files, error_files, error_details, debug_list,
                                    mode_tag="Mode 3 (Drive Excel)", is_direct_sheet=True, mode2_target_type="google_sheet",
                                    skip_duplicates=skip_duplicates_m3, drive_target_url=active_m3_excel_url,
                                    drive_target_tab=st.session_state.mode3_excel_tab, is_mode3_excel_slot=True,
                                )
                                st.session_state.drive_scan_info, st.session_state.drive_last_scan_key = None, ""
                                st.rerun()

    # ==========================================================
    # MODE 1 & MODE 2 WORKSPACE: MANUAL PDF UPLOAD
    # ==========================================================
    else:
        hdr1, hdr2 = st.columns([4, 1])
        with hdr1:
            st.subheader("📤 Policy PDFs Upload Karein")
        with hdr2:
            if st.button("🗑️ Clear All PDFs", use_container_width=True):
                st.session_state.pdf_uploader_key += 1
                st.rerun()

        uploaded_pdfs = st.file_uploader("Ek ya ek se zyada Health Policy PDF select karein", type=["pdf"], accept_multiple_files=True, key=f"pdf_uploader_{st.session_state.pdf_uploader_key}", label_visibility="collapsed")
        skip_duplicates = st.checkbox("Duplicate Policy auto-skip karein (Agar same Policy Number + Expiry Date pehle se sheet me saved ho)", value=False)
        btn_label = "🚀 Start Policy Entry (Mode 2: Direct Fixed Sheet me Save Karein)" if is_mode2 else "🚀 Start Policy Entry (Mode 1: Cloud Portal)"

        if st.button(btn_label, type="primary", use_container_width=True):
            if not uploaded_pdfs:
                st.warning("Pehle kam se kam ek Policy PDF upload karein.")
            elif is_mode2 and mode2_target_type == "google_sheet" and not st.session_state.fixed_sheet_url:
                st.warning("Mode 2 ke liye pehle Left Sidebar se apni Policy Entry Google Sheet link karein.")
            elif is_mode2 and mode2_target_type == "local_excel" and not st.session_state.local_excel_path:
                st.warning("Mode 2 ke liye pehle Left Sidebar se apni Fixed Local Excel (.xlsx) file ka path link karein.")
            else:
                master_df = get_active_master_df(manual_master_file)
                accounts_df = get_active_accounts_df("health", manual_acc_files)
                extracted_rows, done_files, error_files, error_details, debug_list = [], [], [], [], []

                progress, status_text = st.progress(0), st.empty()
                for idx, pdf in enumerate(uploaded_pdfs):
                    status_text.text(f"Processing ({idx + 1}/{len(uploaded_pdfs)}): {pdf.name}")
                    pdf_bytes = pdf.read()
                    row_dict, is_ok, err_msg, debug_info = process_health_pdf(pdf.name, pdf_bytes, master_df, accounts_df=accounts_df)
                    debug_list.append(debug_info)
                    extracted_rows.append(row_dict)
                    if is_ok:
                        done_files.append((pdf.name, pdf_bytes))
                    else:
                        error_files.append((pdf.name, pdf_bytes))
                        error_details.append({"File Name": pdf.name, "Reason": err_msg})
                    progress.progress((idx + 1) / len(uploaded_pdfs))

                status_text.empty()
                progress.empty()

                if st.session_state.health_renewal_folder_url and extracted_rows:
                    with st.spinner("Renewal List PDFs se PYP premium & OUR RENEWAL check ho raha hai..."):
                        apply_renewal_list_lookup(extracted_rows, st.session_state.health_renewal_folder_url)

                save_and_record_batch(
                    extracted_rows, done_files, error_files, error_details, debug_list,
                    mode_tag="Mode 2" if is_mode2 else "Mode 1", is_direct_sheet=is_mode2,
                    mode2_target_type=mode2_target_type, skip_duplicates=skip_duplicates,
                    drive_target_url=st.session_state.fixed_sheet_url, drive_target_tab=st.session_state.fixed_sheet_tab,
                )
                st.session_state.pdf_uploader_key += 1
                st.rerun()

    # --- LAST BATCH SUMMARY ---
    if "last_results" in st.session_state:
        res = st.session_state["last_results"]
        st.divider()
        if res.get("save_error"):
            st.error(res["save_error"])
        elif res.get("save_msg"):
            st.success(res["save_msg"])
        if res.get("skipped_count", 0) > 0:
            st.info(f"ℹ️ {res['skipped_count']} duplicate policy pehle se saved thi, isliye dobara add nahi ki gayi.")

        st.subheader(f"⚡ Latest Round #{res['round_no']} [{res.get('mode_used', 'Mode 1')}] ({res['time_display']})")
        m1, m2, m3 = st.columns(3)
        m1.metric("Is Round ki PDFs", res["total_count"])
        m2.metric("Done (YES) ✅", res["done_count"])
        m3.metric("Error (Check Karein) ❌", res["error_count"])

        if not is_mode3:
            z1, z2 = st.columns(2)
            with z1:
                if res.get("round_excel_bytes"):
                    st.download_button(f"📊 Round #{res['round_no']} Excel Copy", data=res["round_excel_bytes"], file_name=f"Round_{res['round_no']}_Health_Entries_{res['timestamp']}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True, key=f"latest_xlsx_{res['round_no']}_{res['timestamp']}")
            with z2:
                if res["err_zip_bytes"]:
                    st.download_button(f"⚠️ Round #{res['round_no']} Only Error PDFs (ZIP)", data=res["err_zip_bytes"], file_name=f"Round_{res['round_no']}_Error_Policies_{res['timestamp']}.zip", mime="application/zip", use_container_width=True, key=f"latest_err_{res['round_no']}_{res['timestamp']}")

        if res["error_details"]:
            st.warning("Neeche di gayi PDFs me problem aayi — inki copy `Error` folder me save kar di gayi hai (original files safe hain):")
            st.dataframe(pd.DataFrame(res["error_details"]), use_container_width=True, hide_index=True)

        if is_direct_sheet and res.get("batch_rows"):
            st.subheader("Preview Mode")
            st.dataframe(pd.DataFrame(res["batch_rows"], columns=res.get("batch_columns") or active_headers), use_container_width=True, hide_index=True)

    # --- LAST 5 ROUNDS DOWNLOAD HISTORY (MODE 1 & MODE 2 ONLY) ---
    if not is_mode3 and st.session_state.batch_history:
        with st.expander(f"🗂️ Last {len(st.session_state.batch_history)} Rounds Download History (Max {MAX_PDF_ROUNDS} Rounds)", expanded=(len(st.session_state.batch_history) > 1)):
            st.caption("Purane rounds ki Error PDFs ya Excel copy yahan se kabhi bhi download kar sakte hain.")
            for b in st.session_state.batch_history:
                c_info, c_xlsx, c_err = st.columns([2.5, 1.5, 1.5])
                with c_info:
                    st.markdown(f"**Round #{b['round_no']} ({b.get('mode_used', 'Mode 1')})** — `{b['time_display']}`  \nTotal: **{b['total_count']}** | Done: **{b['done_count']} ✅** | Error: **{b['error_count']} ❌**")
                with c_xlsx:
                    if b.get("round_excel_bytes"):
                        st.download_button(f"📊 Round #{b['round_no']} Excel", data=b["round_excel_bytes"], file_name=f"Round_{b['round_no']}_Health_Entries_{b['timestamp']}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True, key=f"hist_xlsx_{b['round_no']}_{b['timestamp']}")
                with c_err:
                    if b["err_zip_bytes"]:
                        st.download_button(f"⚠️ Round #{b['round_no']} Error (ZIP)", data=b["err_zip_bytes"], file_name=f"Round_{b['round_no']}_Error_Policies_{b['timestamp']}.zip", mime="application/zip", use_container_width=True, key=f"hist_err_{b['round_no']}_{b['timestamp']}")
                    else:
                        st.caption("No Error PDFs ✅")
                st.divider()

    # --- MODE 1 PERMANENT MASTER SHEET SECTION ---
    if is_mode1:
        st.divider()
        saved_rows = st.session_state.saved_health_rows or []
        sh1, sh2 = st.columns([3, 1])
        with sh1:
            st.subheader(f"📊 POLICY ENTRY SHEET FOR HEALTH (Total Saved: {len(saved_rows)})")
        with sh2:
            if st.button("🔄 Refresh Saved Sheet", use_container_width=True):
                with st.spinner("Refresh ho raha hai..."):
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

            with st.expander("🗑️ Nayi Sheet Shuru Karein (Purani Saved Entries Clear Karein)"):
                st.warning("Dhyan dein: Clear karne se pehle upar se apni Excel download karke save kar lein.")
                confirm_clear = st.checkbox("Haan, mujhe apni saari saved Health entries clear karni hain.")
                if st.button("Clear Saved Health Sheet", disabled=not confirm_clear):
                    with st.spinner("Clear ho raha hai..."):
                        clr_res = call_backend({"action": "clear_health_entries", "user_id": st.session_state.user_id})
                    if clr_res.get("success"):
                        st.session_state.saved_health_rows = []
                        st.session_state.pop("last_results", None)
                        st.success("Sheet clear ho gayi! Ab aap fresh entries shuru kar sakte hain.")
                        st.rerun()
                    else:
                        st.error(clr_res.get("message", "Clear karne me error aaya."))
        else:
            st.info("Abhi aapki saved Health sheet khali hai. Pehli baar PDF upload karte hi saari entries yahan save hone lagengi.")

    # --- ADMIN-ONLY DEBUG MODE ---
    if is_admin_user() and st.session_state.batch_history:
        with st.expander("click for bugging"):
            round_options = [f"Round #{b['round_no']} ({b['time_display']}) - {b['total_count']} PDFs" for b in st.session_state.batch_history]
            selected_round_idx = st.selectbox("Round chunein:", options=range(len(round_options)), format_func=lambda i: round_options[i], key="debug_round_selector")
            chosen_batch = st.session_state.batch_history[selected_round_idx]
            debug_list = chosen_batch.get("debug_list", [])

            if debug_list:
                pdf_labels = [f"{idx + 1}. {d.get('client_name') or d['file_name']}  —  [{d['file_name']}]" for idx, d in enumerate(debug_list)]
                selected_pdf_idx = st.selectbox("pls select pdf for bugging", options=range(len(pdf_labels)), format_func=lambda i: pdf_labels[i], key=f"debug_pdf_selector_{chosen_batch['round_no']}")
                selected_debug = debug_list[selected_pdf_idx]

                st.write("**File Name:**", selected_debug["file_name"])
                st.write("**Detected Company:**", selected_debug["detected_company"] or "None")
                st.write("**Company Keyword Count:**", selected_debug["company_scores"] or "No match")
                if selected_debug["error_reason"]:
                    st.error(f"Error Reason: {selected_debug['error_reason']}")

                raw_txt = selected_debug["raw_text"] or ""
                st.download_button("📄 Download Full Raw Text (.txt)", data=raw_txt.encode("utf-8"), file_name=f"DEBUG_{selected_debug['file_name']}.txt", mime="text/plain", key=f"debug_dl_{chosen_batch['round_no']}_{selected_pdf_idx}")
                st.text_area(f"Full Extracted PDF Text ({len(raw_txt)} characters) — Ctrl+A, Ctrl+C se copy karein:", value=raw_txt, height=380, key=f"debug_textarea_{chosen_batch['round_no']}_{selected_pdf_idx}_{selected_debug['file_name']}")
                with st.expander("click for copy of pdf text"):
                    st.code(raw_txt, language=None)
