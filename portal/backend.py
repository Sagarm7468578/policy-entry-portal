import base64
import io
import json
import os
import re
from datetime import datetime
import pandas as pd
import requests
import streamlit as st
from health_parsers.common import IST, parse_any_date
from health_parser import (
    MONTH_NAMES_BY_NUM,
    parse_renewal_list_pdf,
    get_renewal_lookup_months,
    match_renewal_record,
    read_excel_headers_from_bytes,
    append_rows_to_excel_bytes,
)

IS_CLOUD = os.path.exists("/mount/src")
LOCAL_CONFIG_FILE = "mode2_local_config.json"

ADMIN_EMAILS = {"mahajansagar746@gmail.com"}
ADMIN_USER_IDS = {"mahajansagar746@gmail.com", "test01"}


def is_admin_user():
    email = str(st.session_state.get("user_email", "") or "").strip().lower()
    uid = str(st.session_state.get("user_id", "") or "").strip().lower()
    return (email in ADMIN_EMAILS) or (uid in ADMIN_USER_IDS)


def call_backend(payload, timeout=120):
    payload["secret"] = st.secrets["SECRET_KEY"]
    try:
        res = requests.post(st.secrets["WEB_APP_URL"], json=payload, timeout=timeout)
        return res.json()
    except Exception as e:
        return {"success": False, "message": f"Connection error: {e}"}


def load_saved_health_rows(user_id):
    res = call_backend({"action": "get_health_entries", "user_id": user_id})
    if res.get("success"):
        return res.get("rows", []), ""
    return [], res.get("message", "Unable to load saved entries.")


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
        "health_share_under60": "12", "health_share_60plus": "8",
    }
    res = call_backend({"action": "get_user_settings", "user_id": user_id})
    if res.get("success"):
        defaults_non_empty = {
            "fixed_sheet_tab": "Policy Entries",
            "health_share_under60": "12",
            "health_share_60plus": "8",
        }
        for k in cfg:
            val = res.get(k, cfg[k])
            if not val and k in defaults_non_empty:
                cfg[k] = defaults_non_empty[k]
            else:
                cfg[k] = val
    return cfg


def save_user_sheet_settings(user_id, **kwargs):
    payload = {"action": "save_user_settings", "user_id": user_id}
    payload.update(kwargs)
    return call_backend(payload)


def _parse_pct_int(val, default_val: int) -> int:
    s = re.sub(r"[^0-9]", "", str(val or ""))
    if s.isdigit():
        n = int(s)
        if 5 <= n <= 25:
            return n
    return default_val


def apply_share_commission(extracted_rows, under60_pct="12", plus60_pct="8"):
    """
    Calculates 'Share %' and 'Share' (commission amount) from DOB + Premium
    using each user's saved Under-60 and 60+ commission rates.
    """
    if not extracted_rows:
        return
    u60 = _parse_pct_int(under60_pct, 12)
    p60 = _parse_pct_int(plus60_pct, 8)
    today_dt = datetime.now(IST).replace(tzinfo=None)

    for row in extracted_rows:
        dob_dt = parse_any_date(row.get("DOB", ""))
        if not dob_dt:
            row["Share %"] = ""
            row["Share"] = ""
            continue

        ref_dt = parse_any_date(row.get("Inception Date", "")) or today_dt
        age = (ref_dt.year - dob_dt.year) - ((ref_dt.month, ref_dt.day) < (dob_dt.month, dob_dt.day))
        rate = p60 if age >= 60 else u60
        row["Share %"] = f"{rate}%"

        prem_raw = str(row.get("Premium", "") or "").replace(",", "").strip()
        try:
            prem_val = float(prem_raw)
            row["Share"] = str(int(round(prem_val * rate / 100.0)))
        except ValueError:
            row["Share"] = ""


def fetch_linked_client_master(sheet_url, sheet_tab=""):
    if not sheet_url:
        return None, "", ""
    res = call_backend({
        "action": "get_client_master",
        "sheet_url": sheet_url.strip(),
        "sheet_tab": (sheet_tab or "").strip(),
    })
    if not res.get("success"):
        return None, "", res.get("message", "Unable to load Client Master sheet.")
    headers, rows = res.get("headers", []), res.get("rows", [])
    sheet_name = res.get("sheet_name", "Client Master Sheet")
    return (pd.DataFrame(rows, columns=headers, dtype=str) if headers else pd.DataFrame()), sheet_name, ""


def fetch_linked_accounts_master(sheet_url, sheet_tab=""):
    if not sheet_url:
        return None, "", ""
    res = call_backend({
        "action": "get_accounts_master",
        "sheet_url": sheet_url.strip(),
        "sheet_tab": (sheet_tab or "").strip(),
    })
    if not res.get("success"):
        return None, "", res.get("message", "Unable to load Accounts Master sheet.")

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
                return None, sheet_name, "Row 1 must include 'Company Name', 'Agency', and 'Accounts' columns."
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
        return None, "Google Drive folder is not linked."
    res = call_backend({
        "action": "list_drive_pdfs", "user_id": user_id,
        "folder_url": folder_url.strip(),
        "year_folder": (year_folder or "").strip(),
        "month_folder": (month_folder or "").strip(),
    })
    if not res.get("success"):
        return None, res.get("message", "Unable to scan Google Drive folder.")
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
        return [], g_res.get("message", "Unable to access target file.")
    if g_res.get("is_google_sheet"):
        h_res = call_backend({"action": "get_sheet_headers", "sheet_url": target_url.strip(), "sheet_tab": target_tab.strip()})
        if h_res.get("success") and h_res.get("headers"):
            return h_res["headers"], ""
        return [], h_res.get("message", "Row 1 of the sheet is currently empty.")
    hdrs, _, err = read_excel_headers_from_bytes(base64.b64decode(g_res["content_b64"]), target_tab)
    if err:
        return [], err
    return (hdrs, "") if hdrs else ([], "Row 1 of the Excel file is currently empty.")


def save_rows_to_drive_target(target_url, target_tab, projected_rows, used_schema, skip_duplicates, mode_tag):
    probe = call_backend({"action": "get_drive_excel", "sheet_url": target_url.strip()})
    if not probe.get("success"):
        return False, "", f"❌ Could not open target file: {probe.get('message', 'Unknown error')}", 0, ""

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
            msg = "ENTRY DONE PLS RECHECK NOW" if mode_tag.startswith("Mode 3") else f"✅ {mode_tag}: Saved {added_cnt} new entries to '{s_name} → {t_name}' (Total Entries: {g_res.get('total_rows', '')})"
            return True, msg, "", skipped_cnt, s_name
        return False, "", f"❌ Google Sheet save failed: {g_res.get('message', 'Unknown error')}", 0, ""

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
        msg = "ENTRY DONE PLS RECHECK NOW" if mode_tag.startswith("Mode 3") else f"✅ {mode_tag}: No new entries added ({skipped_cnt} duplicates already existed in '{file_name}')."
        return True, msg, "", skipped_cnt, file_name

    up_res = call_backend({
        "action": "update_drive_excel", "file_id": file_id,
        "mime_type": mime_type, "content_b64": base64.b64encode(updated_bytes).decode("ascii"),
    }, timeout=120)
    if up_res.get("success"):
        msg = "ENTRY DONE PLS RECHECK NOW" if mode_tag.startswith("Mode 3") else f"✅ {mode_tag}: Saved **{added_cnt}** new entries directly to `{file_name}` (Tab: `{used_tab}` | Total Entries: **{total_cnt}**)"
        return True, msg, "", skipped_cnt, file_name
    return False, "", f"❌ Google Drive Excel update failed: {up_res.get('message', 'Unknown error')}", skipped_cnt, file_name


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
