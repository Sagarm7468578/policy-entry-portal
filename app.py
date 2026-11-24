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
    normalize_custom_columns_spec,
    spec_to_multiline,
    get_custom_schema_info,
    project_rows_to_schema,
    process_health_pdf,
    build_excel_bytes,
    build_sample_master_bytes,
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


def call_backend(payload):
    payload["secret"] = SECRET_KEY
    try:
        res = requests.post(WEB_APP_URL, json=payload, timeout=60)
        return res.json()
    except Exception as e:
        return {"success": False, "message": f"Connection error: {e}"}


def load_saved_health_rows(user_id):
    res = call_backend({"action": "get_health_entries", "user_id": user_id})
    if res.get("success"):
        return res.get("rows", []), ""
    return [], res.get("message", "Saved data load nahi ho paya.")


def load_user_sheet_settings(user_id):
    res = call_backend({"action": "get_user_settings", "user_id": user_id})
    if res.get("success"):
        return {
            "fixed_sheet_url": res.get("fixed_sheet_url", ""),
            "fixed_sheet_tab": res.get("fixed_sheet_tab", "Policy Entries") or "Policy Entries",
            "client_master_url": res.get("client_master_url", ""),
            "client_master_tab": res.get("client_master_tab", ""),
            "health_custom_columns": res.get("health_custom_columns", ""),
        }
    return {
        "fixed_sheet_url": "",
        "fixed_sheet_tab": "Policy Entries",
        "client_master_url": "",
        "client_master_tab": "",
        "health_custom_columns": "",
    }


def save_user_sheet_settings(user_id, **kwargs):
    payload = {"action": "save_user_settings", "user_id": user_id}
    payload.update(kwargs)
    return call_backend(payload)


def fetch_linked_client_master(sheet_url, sheet_tab=""):
    if not sheet_url:
        return None, "", ""
    res = call_backend({
        "action": "get_client_master",
        "sheet_url": sheet_url.strip(),
        "sheet_tab": (sheet_tab or "").strip(),
    })
    if not res.get("success"):
        return None, "", res.get("message", "Client Master Google Sheet load nahi ho payi.")
    headers = res.get("headers", [])
    rows = res.get("rows", [])
    sheet_name = res.get("sheet_name", "Client Master Sheet")
    if not headers:
        return pd.DataFrame(), sheet_name, ""
    df = pd.DataFrame(rows, columns=headers, dtype=str)
    return df, sheet_name, ""


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
            json.dump(
                {"local_excel_path": path_str.strip(), "local_sheet_name": sheet_name.strip() or "Policy Entries"},
                f,
                indent=2,
            )
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
            email = str(st.user.get("email", "") or "").strip().lower()
            name = str(st.user.get("name", "") or "").strip()
            return True, email, name
    except Exception:
        pass
    return False, "", ""


# --- SESSION STATE INITIALIZATION ---
defaults = {
    "logged_in": False,
    "auth_method": "",
    "user_id": "",
    "user_email": "",
    "user_name": "",
    "expiry": "",
    "google_auth_error": "",
    "pdf_uploader_key": 0,
    "col_editor_key": 0,
    "saved_health_rows": None,
    "batch_history": [],
    "round_counter": 0,
    "settings_loaded": False,
    "fixed_sheet_url": "",
    "fixed_sheet_tab": "Policy Entries",
    "fixed_sheet_name": "",
    "client_master_url": "",
    "client_master_tab": "",
    "client_master_sheet_name": "",
    "health_custom_columns": "",
    "linked_master_df": None,
    "linked_master_error": "",
    "local_excel_path": "",
    "local_sheet_name": "Policy Entries",
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# --- AUTO-RESTORE GOOGLE LOGIN (PERSISTENT ACROSS REFRESH & BROWSER RESTART) ---
google_configured = is_google_auth_configured()
google_logged_in, g_email, g_name = get_google_user_info()

if google_logged_in and g_email and not st.session_state.logged_in:
    with st.spinner("Google account verify ho raha hai..."):
        g_res = call_backend({
            "action": "google_login",
            "email": g_email,
        })
    if g_res.get("success"):
        st.session_state.logged_in = True
        st.session_state.auth_method = "google"
        st.session_state.user_id = g_res.get("user_id", g_email)
        st.session_state.user_email = g_email
        st.session_state.user_name = g_name
        st.session_state.expiry = g_res.get("expiry", "")
        st.session_state.google_auth_error = ""
        st.session_state.saved_health_rows = None
        st.session_state.settings_loaded = False
        st.session_state.linked_master_df = None
        st.session_state.linked_master_error = ""
        st.session_state.batch_history = []
        st.session_state.round_counter = 0
        st.rerun()
    else:
        st.session_state.google_auth_error = g_res.get("message", "Yeh Gmail account registered/active nahi hai.")


# --- LOGIN SCREEN ---
if not st.session_state.logged_in:
    col1, col2, col3 = st.columns([1, 2, 1])
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
                submit = st.form_submit_button("Login", use_container_width=True)

                if submit:
                    if not user_id or not password:
                        st.warning("User ID aur Password dono bharein.")
                    else:
                        with st.spinner("Check kar rahe hain..."):
                            result = call_backend({
                                "action": "login",
                                "user_id": user_id,
                                "password": password
                            })
                        if result.get("success"):
                            st.session_state.logged_in = True
                            st.session_state.auth_method = "password"
                            st.session_state.user_id = user_id.strip()
                            st.session_state.user_email = ""
                            st.session_state.user_name = ""
                            st.session_state.expiry = result.get("expiry", "")
                            st.session_state.saved_health_rows = None
                            st.session_state.settings_loaded = False
                            st.session_state.linked_master_df = None
                            st.session_state.linked_master_error = ""
                            st.session_state.batch_history = []
                            st.session_state.round_counter = 0
                            st.rerun()
                        else:
                            st.error(result.get("message", "Login fail ho gaya."))


# --- MAIN POLICY ENTRY DASHBOARD ---
else:
    # Load permanent linked sheets & custom columns once after login
    if not st.session_state.settings_loaded:
        with st.spinner("Aapki linked sheets aur custom columns load ho rahe hain..."):
            cfg = load_user_sheet_settings(st.session_state.user_id)
            l_path, l_tab = load_local_excel_path()
            st.session_state.fixed_sheet_url = cfg["fixed_sheet_url"]
            st.session_state.fixed_sheet_tab = cfg["fixed_sheet_tab"]
            st.session_state.client_master_url = cfg["client_master_url"]
            st.session_state.client_master_tab = cfg["client_master_tab"]
            st.session_state.health_custom_columns = cfg["health_custom_columns"]
            st.session_state.local_excel_path = l_path
            st.session_state.local_sheet_name = l_tab

            if st.session_state.client_master_url:
                m_df, m_name, m_err = fetch_linked_client_master(
                    st.session_state.client_master_url,
                    st.session_state.client_master_tab,
                )
                st.session_state.linked_master_df = m_df
                st.session_state.client_master_sheet_name = m_name
                st.session_state.linked_master_error = m_err

            st.session_state.settings_loaded = True

    active_schema = get_custom_schema_info(st.session_state.health_custom_columns)
    active_headers = active_schema["headers"]
    is_custom_cols = bool(st.session_state.health_custom_columns.strip())

    mode2_target_type = "google_sheet"
    manual_master_file = None

    # --- SIDEBAR (SETTINGS + POLICY SHEET + CLIENT MASTER + CUSTOM COLUMNS) ---
    with st.sidebar:
        display_user = st.session_state.user_name or st.session_state.user_id
        email_line = f"  \n📧 `{st.session_state.user_email}`" if st.session_state.user_email else ""
        st.success(f"👤 **{display_user}**{email_line}  \n📅 Valid Till: **{st.session_state.expiry}**")

        default_mode_idx = 1 if (st.session_state.fixed_sheet_url or st.session_state.local_excel_path) else 0
        working_mode = st.radio(
            "⚙️ Working Mode",
            [
                "Mode 1: Cloud Portal (Excel Download)",
                "Mode 2: Fixed Sheet Auto-Entry (No Download)",
            ],
            index=default_mode_idx,
        )
        is_mode2 = working_mode.startswith("Mode 2")

        policy_category = st.selectbox(
            "📂 Policy Type",
            ["Health Insurance", "Motor Insurance (Coming Soon)", "SME Insurance (Coming Soon)"]
        )

        st.divider()

        # 1. POLICY ENTRY SHEET PANEL (SIDEBAR)
        if is_mode2:
            is_policy_linked = bool(st.session_state.fixed_sheet_url or (not IS_CLOUD and st.session_state.local_excel_path))
            ps_badge = "✅ Linked" if is_policy_linked else "⚪ Not Linked"

            with st.expander(f"🎯 Policy Entry Sheet ({ps_badge})", expanded=not is_policy_linked):
                target_options = ["☁️ Google Sheet (24x7 Online)"]
                if not IS_CLOUD:
                    target_options.insert(0, "💻 Local PC Excel (.xlsx)")

                chosen_target = st.radio(
                    "Save Destination",
                    target_options,
                    key="sidebar_mode2_target",
                )

                if chosen_target.startswith("💻"):
                    mode2_target_type = "local_excel"
                    if st.session_state.local_excel_path:
                        st.success(
                            f"**Local Excel Linked**  \n"
                            f"`{os.path.basename(st.session_state.local_excel_path)}`  \n"
                            f"📑 Tab: `{st.session_state.local_sheet_name}`"
                        )
                        if st.button("🔓 Unlink Excel", use_container_width=True, key="unlink_local_excel"):
                            st.session_state.local_excel_path = ""
                            save_local_excel_path("", "Policy Entries")
                            st.rerun()
                    else:
                        local_path_input = st.text_input(
                            "Fixed Excel Path (.xlsx)",
                            placeholder=r"I:\My Drive\POLICY ENTRY EXCEL\HEALTH.xlsx",
                            key="sb_local_path_input",
                        )
                        local_tab_input = st.text_input(
                            "Sheet Tab Name",
                            value="Policy Entries",
                            key="sb_local_tab_input",
                        )
                        if st.button("🔗 Link Path", type="primary", use_container_width=True):
                            clean_p = local_path_input.strip().strip('"')
                            if not clean_p:
                                st.warning("Path dalein.")
                            else:
                                st.session_state.local_excel_path = clean_p
                                st.session_state.local_sheet_name = local_tab_input.strip() or "Policy Entries"
                                save_local_excel_path(clean_p, st.session_state.local_sheet_name)
                                st.rerun()
                else:
                    mode2_target_type = "google_sheet"
                    if st.session_state.fixed_sheet_url:
                        title_txt = (
                            f"**{st.session_state.fixed_sheet_name}**  \n"
                            if st.session_state.fixed_sheet_name
                            else ""
                        )
                        st.success(
                            f"{title_txt}📑 Tab: `{st.session_state.fixed_sheet_tab}`  \n"
                            f"Auto-save active (Zero download)"
                        )
                        if st.session_state.fixed_sheet_url.startswith("http"):
                            st.link_button(
                                "🔗 Open Policy Sheet",
                                st.session_state.fixed_sheet_url,
                                use_container_width=True,
                            )
                        if st.button("🔓 Unlink Policy Sheet", use_container_width=True, key="unlink_policy_gsheet"):
                            with st.spinner("Unlink kar rahe hain..."):
                                u_res = save_user_sheet_settings(
                                    st.session_state.user_id,
                                    fixed_sheet_url="",
                                    fixed_sheet_tab="Policy Entries",
                                )
                            if u_res.get("success"):
                                st.session_state.fixed_sheet_url = ""
                                st.session_state.fixed_sheet_tab = "Policy Entries"
                                st.session_state.fixed_sheet_name = ""
                                st.rerun()
                            else:
                                st.error(u_res.get("message", "Unlink nahi ho paya."))
                    else:
                        sheet_url_input = st.text_input(
                            "Policy Sheet URL / ID",
                            placeholder="https://docs.google.com/spreadsheets/d/...",
                            key="policy_sheet_url_input",
                        )
                        sheet_tab_input = st.text_input(
                            "Sheet Tab Name",
                            value=st.session_state.fixed_sheet_tab or "Policy Entries",
                            key="policy_sheet_tab_input",
                        )
                        if st.button("🔗 Link Policy Sheet", type="primary", use_container_width=True):
                            clean_url = sheet_url_input.strip()
                            clean_tab = sheet_tab_input.strip() or "Policy Entries"
                            if not clean_url:
                                st.warning("Google Sheet URL dalein.")
                            else:
                                with st.spinner("Verify & link ho raha hai..."):
                                    v_res = call_backend({
                                        "action": "verify_sheet",
                                        "sheet_url": clean_url,
                                    })
                                    if not v_res.get("success"):
                                        st.error(v_res.get("message", "Sheet access nahi ho payi."))
                                    else:
                                        s_res = save_user_sheet_settings(
                                            st.session_state.user_id,
                                            fixed_sheet_url=clean_url,
                                            fixed_sheet_tab=clean_tab,
                                        )
                                        if s_res.get("success"):
                                            st.session_state.fixed_sheet_url = clean_url
                                            st.session_state.fixed_sheet_tab = clean_tab
                                            st.session_state.fixed_sheet_name = v_res.get("sheet_name", "")
                                            st.rerun()
                                        else:
                                            st.error(s_res.get("message", "Save nahi ho paya."))
                        st.caption("💡 Sheet ko `Anyone with the link → Editor` share karein.")

        # 2. CLIENT MASTER PANEL (SIDEBAR)
        m_df = st.session_state.linked_master_df
        m_count = len(m_df) if isinstance(m_df, pd.DataFrame) else 0
        is_cm_linked = bool(st.session_state.client_master_url)
        cm_badge = f"✅ {m_count} Clients" if (is_cm_linked and not st.session_state.linked_master_error) else (
            "⚠️ Error" if is_cm_linked else "⚪ Not Linked"
        )

        with st.expander(f"👥 Client Master ({cm_badge})", expanded=not is_cm_linked):
            if is_cm_linked:
                m_title = st.session_state.client_master_sheet_name or "Client Master Sheet"
                if st.session_state.linked_master_error:
                    st.error(f"⚠️ {st.session_state.linked_master_error}")
                else:
                    st.success(f"**{m_title}**  \n👥 **{m_count} Clients Loaded**")

                mc1, mc2 = st.columns(2)
                with mc1:
                    if st.button("🔄 Refresh", use_container_width=True, key="refresh_linked_master"):
                        with st.spinner("Refresh ho raha hai..."):
                            m_df, m_name, m_err = fetch_linked_client_master(
                                st.session_state.client_master_url,
                                st.session_state.client_master_tab,
                            )
                            st.session_state.linked_master_df = m_df
                            st.session_state.client_master_sheet_name = m_name
                            st.session_state.linked_master_error = m_err
                        st.rerun()
                with mc2:
                    if st.button("🔓 Unlink", use_container_width=True, key="unlink_client_master"):
                        with st.spinner("Unlink ho raha hai..."):
                            u_res = save_user_sheet_settings(
                                st.session_state.user_id,
                                client_master_url="",
                                client_master_tab="",
                            )
                        if u_res.get("success"):
                            st.session_state.client_master_url = ""
                            st.session_state.client_master_tab = ""
                            st.session_state.client_master_sheet_name = ""
                            st.session_state.linked_master_df = None
                            st.session_state.linked_master_error = ""
                            st.rerun()
                        else:
                            st.error(u_res.get("message", "Unlink nahi ho paya."))

                if st.session_state.client_master_url.startswith("http"):
                    st.link_button(
                        "🔗 Open Client Master",
                        st.session_state.client_master_url,
                        use_container_width=True,
                    )
            else:
                cm_tab1, cm_tab2 = st.tabs(["🔗 Google Sheet", "📤 File"])
                with cm_tab1:
                    cm_url_input = st.text_input(
                        "Client Master Sheet URL",
                        placeholder="https://docs.google.com/spreadsheets/d/...",
                        key="cm_url_input",
                    )
                    cm_tab_input = st.text_input(
                        "Tab Name (Blank = 1st Tab)",
                        value="",
                        key="cm_tab_input",
                    )
                    if st.button("🔗 Link Master Sheet", type="primary", use_container_width=True):
                        clean_cm_url = cm_url_input.strip()
                        clean_cm_tab = cm_tab_input.strip()
                        if not clean_cm_url:
                            st.warning("Client Master link dalein.")
                        else:
                            with st.spinner("Verify & link ho raha hai..."):
                                m_df, m_name, m_err = fetch_linked_client_master(clean_cm_url, clean_cm_tab)
                                if m_err:
                                    st.error(m_err)
                                else:
                                    s_res = save_user_sheet_settings(
                                        st.session_state.user_id,
                                        client_master_url=clean_cm_url,
                                        client_master_tab=clean_cm_tab,
                                    )
                                    if s_res.get("success"):
                                        st.session_state.client_master_url = clean_cm_url
                                        st.session_state.client_master_tab = clean_cm_tab
                                        st.session_state.client_master_sheet_name = m_name
                                        st.session_state.linked_master_df = m_df
                                        st.session_state.linked_master_error = ""
                                        st.rerun()
                                    else:
                                        st.error(s_res.get("message", "Save nahi ho paya."))
                with cm_tab2:
                    manual_master_file = st.file_uploader(
                        "Upload Master (.xlsx / .csv)",
                        type=["xlsx", "csv"],
                        key="client_master_uploader",
                    )

        # 3. CUSTOM SHEET COLUMNS PANEL (USER + ADMIN HYBRID CONTROL)
        col_badge = f"Custom: {len(active_headers)}" if is_custom_cols else f"Default: {len(OUTPUT_COLUMNS)}"
        with st.expander(f"🛠️ Sheet Columns ({col_badge})", expanded=False):
            st.caption(
                "Har line me 1 column likhein (exact order me).  \n"
                "• Auto-fill fields: Client Name, Policy Number, Occupation, etc.  \n"
                "• Manual/Blank column: Bas naam likh dein (e.g. `Accounts`, `Mail`, `Print`)  \n"
                "• Header rename: `Client Name => Insured Name`"
            )

            if is_mode2 and mode2_target_type == "google_sheet" and st.session_state.fixed_sheet_url:
                if st.button("📥 Linked Sheet se Headers Import Karein", use_container_width=True, key="import_sheet_hdrs"):
                    with st.spinner("Sheet ke Row 1 headers padh rahe hain..."):
                        h_res = call_backend({
                            "action": "get_sheet_headers",
                            "sheet_url": st.session_state.fixed_sheet_url,
                            "sheet_tab": st.session_state.fixed_sheet_tab,
                        })
                    if h_res.get("success") and h_res.get("headers"):
                        imported_spec = normalize_custom_columns_spec("\n".join(h_res["headers"]))
                        s_res = save_user_sheet_settings(
                            st.session_state.user_id,
                            health_custom_columns=imported_spec,
                        )
                        if s_res.get("success"):
                            st.session_state.health_custom_columns = imported_spec
                            st.session_state.col_editor_key += 1
                            st.rerun()
                        else:
                            st.error(s_res.get("message", "Save nahi ho paya."))
                    else:
                        st.warning(h_res.get("message", "Sheet ki Row 1 khali hai — neeche manually columns paste karke Save karein."))

            cols_text = st.text_area(
                "Apne Columns (1 per line)",
                value=spec_to_multiline(st.session_state.health_custom_columns),
                height=240,
                key=f"custom_cols_textarea_{st.session_state.col_editor_key}",
            )

            cc1, cc2 = st.columns(2)
            with cc1:
                if st.button("💾 Save", type="primary", use_container_width=True, key="save_custom_cols"):
                    norm_spec = normalize_custom_columns_spec(cols_text)
                    with st.spinner("Columns save ho rahe hain..."):
                        s_res = save_user_sheet_settings(
                            st.session_state.user_id,
                            health_custom_columns=norm_spec,
                        )
                    if s_res.get("success"):
                        st.session_state.health_custom_columns = norm_spec
                        st.session_state.col_editor_key += 1
                        st.rerun()
                    else:
                        st.error(s_res.get("message", "Save nahi ho paya."))
            with cc2:
                if st.button("🔄 Reset", use_container_width=True, key="reset_custom_cols"):
                    with st.spinner("Default columns reset ho rahe hain..."):
                        s_res = save_user_sheet_settings(
                            st.session_state.user_id,
                            health_custom_columns="",
                        )
                    if s_res.get("success"):
                        st.session_state.health_custom_columns = ""
                        st.session_state.col_editor_key += 1
                        st.rerun()
                    else:
                        st.error(s_res.get("message", "Reset nahi ho paya."))

            with st.popover("📋 Available Auto-Fill Fields", use_container_width=True):
                st.write(", ".join(ALL_SYSTEM_FIELDS))

        st.divider()
        st.download_button(
            "📋 Sample Client Master",
            data=build_sample_master_bytes(),
            file_name="Sample_Client_Master.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
        if st.button("🚪 Logout", use_container_width=True):
            was_google = st.session_state.auth_method == "google"
            for k, v in defaults.items():
                st.session_state[k] = v
            st.session_state.pop("last_results", None)
            if was_google and google_configured:
                st.logout()
            else:
                st.rerun()

    # --- CLEAN MAIN WORKSPACE (MINIMUM SCROLLING) ---
    st.title("📄 Automatic Policy Entry Portal")

    if policy_category != "Health Insurance":
        st.info(f"**{policy_category}** abhi setup ho raha hai. Filhaal **Health Insurance** chunein.")
        st.stop()

    # 1-Line Compact Status Bar
    if is_mode2:
        if mode2_target_type == "local_excel":
            ps_status = f"✅ `{os.path.basename(st.session_state.local_excel_path)}`" if st.session_state.local_excel_path else "⚠️ Not Linked (Sidebar se link karein)"
        else:
            ps_name = st.session_state.fixed_sheet_name or st.session_state.fixed_sheet_tab
            ps_status = f"✅ `{ps_name}`" if st.session_state.fixed_sheet_url else "⚠️ Not Linked (Sidebar se link karein)"
    else:
        ps_status = "☁️ Mode 1 Cloud Sheet"

    if st.session_state.client_master_url:
        cm_status = f"✅ {m_count} Clients Linked" if not st.session_state.linked_master_error else "⚠️ Link Error"
    elif manual_master_file is not None:
        cm_status = f"📄 `{manual_master_file.name}`"
    else:
        cm_status = "⚪ Not Linked"

    cols_status = f"🛠️ {len(active_headers)} Custom Cols" if is_custom_cols else f"🛠️ {len(OUTPUT_COLUMNS)} Default Cols"
    st.caption(
        f"**Mode:** {'Mode 2 (Auto-Save)' if is_mode2 else 'Mode 1 (Download)'}  |  "
        f"**Policy Sheet:** {ps_status}  |  **Client Master:** {cm_status}  |  **Format:** {cols_status}"
    )

    # Load Mode 1 saved rows once if needed
    if not is_mode2 and st.session_state.saved_health_rows is None:
        with st.spinner("Aapki purani saved Health Sheet load ho rahi hai..."):
            loaded_rows, load_err = load_saved_health_rows(st.session_state.user_id)
            st.session_state.saved_health_rows = loaded_rows
            if load_err:
                st.warning(f"⚠️ Cloud sheet load notice: {load_err}")

    # --- PDF UPLOAD AREA RIGHT AT THE TOP ---
    hdr1, hdr2 = st.columns([4, 1])
    with hdr1:
        st.subheader("📤 Policy PDFs Upload Karein")
    with hdr2:
        if st.button("🗑️ Clear All PDFs", use_container_width=True):
            st.session_state.pdf_uploader_key += 1
            st.rerun()

    uploaded_pdfs = st.file_uploader(
        "Ek ya ek se zyada Health Policy PDF select karein",
        type=["pdf"],
        accept_multiple_files=True,
        key=f"pdf_uploader_{st.session_state.pdf_uploader_key}",
        label_visibility="collapsed",
    )

    skip_duplicates = st.checkbox(
        "Duplicate Policy auto-skip karein (Agar same Policy Number + Expiry Date pehle se sheet me saved ho)",
        value=True
    )

    btn_label = (
        "🚀 Start Policy Entry (Mode 2: Direct Fixed Sheet me Save Karein)"
        if is_mode2
        else "🚀 Start Policy Entry (Mode 1: Cloud Portal)"
    )

    if st.button(btn_label, type="primary", use_container_width=True):
        if not uploaded_pdfs:
            st.warning("Pehle kam se kam ek Policy PDF upload karein.")
        elif is_mode2 and mode2_target_type == "google_sheet" and not st.session_state.fixed_sheet_url:
            st.warning("Mode 2 ke liye pehle Left Sidebar se apni Policy Entry Google Sheet link karein.")
        elif is_mode2 and mode2_target_type == "local_excel" and not st.session_state.local_excel_path:
            st.warning("Mode 2 ke liye pehle Left Sidebar se apni Fixed Local Excel (.xlsx) file ka path link karein.")
        else:
            master_df = None
            if st.session_state.client_master_url and isinstance(st.session_state.linked_master_df, pd.DataFrame):
                master_df = st.session_state.linked_master_df
            elif manual_master_file is not None:
                try:
                    manual_master_file.seek(0)
                    if manual_master_file.name.lower().endswith(".csv"):
                        master_df = pd.read_csv(manual_master_file, dtype=str)
                    else:
                        master_df = pd.read_excel(manual_master_file, dtype=str)
                except Exception as e:
                    st.warning(f"Client Master read nahi ho payi ({e}). Bina master ke entry kar rahe hain.")

            extracted_rows = []
            done_files = []
            error_files = []
            error_details = []
            debug_list = []

            progress = st.progress(0)
            status_text = st.empty()

            for idx, pdf in enumerate(uploaded_pdfs):
                status_text.text(f"Processing ({idx + 1}/{len(uploaded_pdfs)}): {pdf.name}")
                pdf_bytes = pdf.read()
                row_dict, is_ok, err_msg, debug_info = process_health_pdf(pdf.name, pdf_bytes, master_df)
                debug_list.append(debug_info)
                extracted_rows.append(row_dict)

                if is_ok:
                    comp = row_dict["Company Name"].replace(" ", "_")
                    done_files.append((f"{comp}_{pdf.name}", pdf_bytes))
                else:
                    error_files.append((pdf.name, pdf_bytes))
                    error_details.append({"File Name": pdf.name, "Reason": err_msg})

                progress.progress((idx + 1) / len(uploaded_pdfs))

            status_text.empty()
            progress.empty()

            # Project rows to user's custom columns (or default 26)
            projected_rows, used_schema = project_rows_to_schema(
                extracted_rows,
                st.session_state.health_custom_columns,
            )

            save_msg = ""
            save_error = ""
            skipped_count = 0

            # --- SAVE LOGIC: MODE 2 vs MODE 1 ---
            if is_mode2:
                if mode2_target_type == "local_excel":
                    with st.spinner("Fixed Local Excel (.xlsx) me purani entry ke neeche save ho raha hai..."):
                        ok, msg, added, skipped, total_cnt = append_rows_to_local_excel(
                            st.session_state.local_excel_path,
                            projected_rows,
                            sheet_name=st.session_state.local_sheet_name,
                            skip_duplicates=skip_duplicates,
                            custom_columns=used_schema["headers"],
                            col_types=used_schema["col_types"],
                            policy_col=used_schema["policy_col"],
                            expiry_col=used_schema["expiry_col"],
                        )
                    skipped_count = skipped
                    if ok:
                        save_msg = f"✅ Mode 2 Direct Save: {msg} (Total Entries in Excel: {total_cnt}) — Download ki zaroorat nahi!"
                    else:
                        save_error = f"❌ {msg}"
                else:
                    with st.spinner("Aapki Linked Policy Entry Google Sheet me purani entry ke neeche direct save ho raha hai..."):
                        g_res = call_backend({
                            "action": "append_to_fixed_sheet",
                            "user_id": st.session_state.user_id,
                            "sheet_url": st.session_state.fixed_sheet_url,
                            "sheet_tab": st.session_state.fixed_sheet_tab,
                            "skip_duplicates": skip_duplicates,
                            "custom_columns": used_schema["headers"],
                            "col_types": used_schema["col_types"],
                            "policy_col": used_schema["policy_col"],
                            "expiry_col": used_schema["expiry_col"],
                            "rows": projected_rows,
                        })
                    if g_res.get("success"):
                        skipped_count = g_res.get("skipped", 0)
                        added_cnt = g_res.get("added", 0)
                        s_name = g_res.get("sheet_name", "Fixed Sheet")
                        t_name = g_res.get("tab_name", st.session_state.fixed_sheet_tab)
                        tot_cnt = g_res.get("total_rows", "")
                        st.session_state.fixed_sheet_name = s_name
                        save_msg = f"✅ Mode 2 Direct Save: {added_cnt} nayi entries seedha '{s_name} → {t_name}' me save ho gayi! (Total Entries: {tot_cnt}) — Download ki zaroorat nahi!"
                    else:
                        save_error = f"❌ Fixed Google Sheet save fail: {g_res.get('message', 'Unknown error')}"
            else:
                if st.session_state.saved_health_rows is None:
                    st.session_state.saved_health_rows = []
                existing_keys = set()
                for r in st.session_state.saved_health_rows:
                    pno = str(r.get("Policy Number", "")).strip().lstrip(",")
                    exp = str(r.get("Expiry Date", "")).strip()
                    if pno:
                        existing_keys.add((pno, exp))

                new_rows_to_save = []
                for row_dict in extracted_rows:
                    pno = str(row_dict.get("Policy Number", "")).strip().lstrip(",")
                    exp = str(row_dict.get("Expiry Date", "")).strip()
                    key = (pno, exp)
                    if skip_duplicates and pno and key in existing_keys:
                        skipped_count += 1
                    else:
                        new_rows_to_save.append(row_dict)
                        if pno:
                            existing_keys.add(key)

                if new_rows_to_save:
                    with st.spinner("Nayi entries aapki Mode 1 master sheet me save ho rahi hain..."):
                        save_res = call_backend({
                            "action": "save_health_entries",
                            "user_id": st.session_state.user_id,
                            "rows": new_rows_to_save,
                        })
                    if save_res.get("success"):
                        st.session_state.saved_health_rows.extend(new_rows_to_save)
                        save_msg = f"✅ {len(new_rows_to_save)} nayi entries '{DEFAULT_HEALTH_EXCEL_NAME}' me purani entries ke neeche save ho gayi!"
                    else:
                        st.session_state.saved_health_rows.extend(new_rows_to_save)
                        save_msg = f"⚠️ Cloud save me dikkat aayi ({save_res.get('message', '')}), par entries is session ki sheet me add ho gayi hain."

            all_zip_buf = io.BytesIO()
            with zipfile.ZipFile(all_zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for fname, fbytes in done_files:
                    zf.writestr(f"Done/{fname}", fbytes)
                for fname, fbytes in error_files:
                    zf.writestr(f"Error/{fname}", fbytes)
            all_zip_bytes = all_zip_buf.getvalue()

            err_zip_bytes = None
            if error_files:
                err_zip_buf = io.BytesIO()
                with zipfile.ZipFile(err_zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    for fname, fbytes in error_files:
                        zf.writestr(fname, fbytes)
                err_zip_bytes = err_zip_buf.getvalue()

            now_ist = datetime.now(IST)
            st.session_state.round_counter += 1
            round_no = st.session_state.round_counter
            ts_file = now_ist.strftime("%Y%m%d_%H%M%S")
            ts_display = now_ist.strftime("%d-%m-%Y %I:%M:%S %p")

            batch_record = {
                "round_no": round_no,
                "mode_used": "Mode 2" if is_mode2 else "Mode 1",
                "timestamp": ts_file,
                "time_display": ts_display,
                "total_count": len(done_files) + len(error_files),
                "done_count": len(done_files),
                "error_count": len(error_files),
                "skipped_count": skipped_count,
                "save_msg": save_msg,
                "save_error": save_error,
                "batch_rows": projected_rows,
                "batch_columns": used_schema["headers"],
                "error_details": error_details,
                "debug_list": debug_list,
                "all_zip_bytes": all_zip_bytes,
                "err_zip_bytes": err_zip_bytes,
            }

            st.session_state.batch_history.insert(0, batch_record)
            st.session_state.batch_history = st.session_state.batch_history[:MAX_PDF_ROUNDS]
            st.session_state["last_results"] = batch_record

            st.session_state.pdf_uploader_key += 1
            st.rerun()

    # --- LAST BATCH SUMMARY (CURRENT ROUND) ---
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

        z1, z2 = st.columns(2)
        with z1:
            st.download_button(
                f"📦 Download Round #{res['round_no']} Sorted PDFs (Done + Error ZIP)",
                data=res["all_zip_bytes"],
                file_name=f"Round_{res['round_no']}_Sorted_Policies_{res['timestamp']}.zip",
                mime="application/zip",
                use_container_width=True,
                key=f"latest_all_{res['round_no']}_{res['timestamp']}"
            )
        with z2:
            if res["err_zip_bytes"]:
                st.download_button(
                    f"⚠️ Download Round #{res['round_no']} Only Error PDFs (ZIP)",
                    data=res["err_zip_bytes"],
                    file_name=f"Round_{res['round_no']}_Error_Policies_{res['timestamp']}.zip",
                    mime="application/zip",
                    use_container_width=True,
                    key=f"latest_err_{res['round_no']}_{res['timestamp']}"
                )

        if res["error_details"]:
            st.warning("Neeche di gayi PDFs me problem aayi — ye `Error` folder me alag kar di gayi hain:")
            st.dataframe(pd.DataFrame(res["error_details"]), use_container_width=True, hide_index=True)

        if is_mode2 and res.get("batch_rows"):
            preview_cols = res.get("batch_columns") or active_headers
            st.subheader("📋 Is Round me Add Hui Entries (Preview)")
            st.dataframe(pd.DataFrame(res["batch_rows"], columns=preview_cols), use_container_width=True, hide_index=True)

    # --- LAST 5 ROUNDS PDF DOWNLOAD HISTORY ---
    if st.session_state.batch_history:
        with st.expander(
            f"🗂️ Last {len(st.session_state.batch_history)} Rounds PDF Download History (Max {MAX_PDF_ROUNDS} Rounds)",
            expanded=(len(st.session_state.batch_history) > 1)
        ):
            st.caption("Purane rounds ki Done / Error PDFs yahan se kabhi bhi download kar sakte hain.")
            for b in st.session_state.batch_history:
                c_info, c_all, c_err = st.columns([2.5, 1.5, 1.5])
                with c_info:
                    st.markdown(
                        f"**Round #{b['round_no']} ({b.get('mode_used', 'Mode 1')})** — `{b['time_display']}`  \n"
                        f"Total: **{b['total_count']}** | Done: **{b['done_count']} ✅** | Error: **{b['error_count']} ❌**"
                    )
                with c_all:
                    st.download_button(
                        f"📦 Round #{b['round_no']} All (ZIP)",
                        data=b["all_zip_bytes"],
                        file_name=f"Round_{b['round_no']}_Sorted_Policies_{b['timestamp']}.zip",
                        mime="application/zip",
                        use_container_width=True,
                        key=f"hist_all_{b['round_no']}_{b['timestamp']}"
                    )
                with c_err:
                    if b["err_zip_bytes"]:
                        st.download_button(
                            f"⚠️ Round #{b['round_no']} Error (ZIP)",
                            data=b["err_zip_bytes"],
                            file_name=f"Round_{b['round_no']}_Error_Policies_{b['timestamp']}.zip",
                            mime="application/zip",
                            use_container_width=True,
                            key=f"hist_err_{b['round_no']}_{b['timestamp']}"
                        )
                    else:
                        st.caption("No Error PDFs ✅")
                st.divider()

    # --- MODE 1 PERMANENT MASTER SHEET SECTION ---
    if not is_mode2:
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
            proj_saved, saved_schema = project_rows_to_schema(
                saved_rows,
                st.session_state.health_custom_columns,
            )
            master_excel_bytes = build_excel_bytes(
                proj_saved,
                columns=saved_schema["headers"],
                col_types=saved_schema["col_types"],
            )
            st.download_button(
                f"📥 Download {DEFAULT_HEALTH_EXCEL_NAME} ({len(proj_saved)} Entries)",
                data=master_excel_bytes,
                file_name=DEFAULT_HEALTH_EXCEL_NAME,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                use_container_width=True
            )
            st.dataframe(pd.DataFrame(proj_saved, columns=saved_schema["headers"]), use_container_width=True, hide_index=True)

            with st.expander("🗑️ Nayi Sheet Shuru Karein (Purani Saved Entries Clear Karein)"):
                st.warning("Dhyan dein: Clear karne se pehle upar se apni Excel download karke save kar lein.")
                confirm_clear = st.checkbox("Haan, mujhe apni saari saved Health entries clear karni hain.")
                if st.button("Clear Saved Health Sheet", disabled=not confirm_clear):
                    with st.spinner("Clear ho raha hai..."):
                        clr_res = call_backend({
                            "action": "clear_health_entries",
                            "user_id": st.session_state.user_id,
                        })
                    if clr_res.get("success"):
                        st.session_state.saved_health_rows = []
                        st.session_state.pop("last_results", None)
                        st.success("Sheet clear ho gayi! Ab aap fresh entries shuru kar sakte hain.")
                        st.rerun()
                    else:
                        st.error(clr_res.get("message", "Clear karne me error aaya."))
        else:
            st.info("Abhi aapki saved Health sheet khali hai. Pehli baar PDF upload karte hi saari entries yahan save hone lagengi.")

    # --- DEBUG MODE ---
    if st.session_state.batch_history:
        with st.expander("🐞 Debug Mode — Kisi bhi PDF ka Full Raw Text & Company Score Dekhein"):
            round_options = [
                f"Round #{b['round_no']} ({b['time_display']}) - {b['total_count']} PDFs"
                for b in st.session_state.batch_history
            ]
            selected_round_idx = st.selectbox(
                "Round chunein:",
                options=range(len(round_options)),
                format_func=lambda i: round_options[i],
                key="debug_round_selector"
            )
            chosen_batch = st.session_state.batch_history[selected_round_idx]
            debug_list = chosen_batch.get("debug_list", [])

            if debug_list:
                pdf_labels = [
                    f"{idx + 1}. {d.get('client_name') or d['file_name']}  —  [{d['file_name']}]"
                    for idx, d in enumerate(debug_list)
                ]
                selected_pdf_idx = st.selectbox(
                    "Debug karne ke liye Policy / Name chunein:",
                    options=range(len(pdf_labels)),
                    format_func=lambda i: pdf_labels[i],
                    key=f"debug_pdf_selector_{chosen_batch['round_no']}"
                )
                selected_debug = debug_list[selected_pdf_idx]

                st.write("**File Name:**", selected_debug["file_name"])
                st.write("**Detected Company:**", selected_debug["detected_company"] or "None")
                st.write("**Company Keyword Count:**", selected_debug["company_scores"] or "No match")
                if selected_debug["error_reason"]:
                    st.error(f"Error Reason: {selected_debug['error_reason']}")

                raw_txt = selected_debug["raw_text"] or ""
                st.download_button(
                    "📄 Download Full Raw Text (.txt)",
                    data=raw_txt.encode("utf-8"),
                    file_name=f"DEBUG_{selected_debug['file_name']}.txt",
                    mime="text/plain",
                    key=f"debug_dl_{chosen_batch['round_no']}_{selected_pdf_idx}"
                )

                st.text_area(
                    f"Full Extracted PDF Text ({len(raw_txt)} characters) — Ctrl+A, Ctrl+C se copy karein:",
                    value=raw_txt,
                    height=380,
                    key=f"debug_textarea_{chosen_batch['round_no']}_{selected_pdf_idx}_{selected_debug['file_name']}"
                )

                with st.expander("📋 1-Click Copy Box (Upar right corner me Copy icon milega)"):
                    st.code(raw_txt, language=None)
