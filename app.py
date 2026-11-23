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


def load_user_mode2_settings(user_id):
    res = call_backend({"action": "get_user_settings", "user_id": user_id})
    if res.get("success"):
        return res.get("fixed_sheet_url", ""), res.get("fixed_sheet_tab", "Policy Entries")
    return "", "Policy Entries"


def save_user_mode2_settings(user_id, sheet_url, sheet_tab):
    return call_backend({
        "action": "save_user_settings",
        "user_id": user_id,
        "fixed_sheet_url": sheet_url.strip(),
        "fixed_sheet_tab": sheet_tab.strip() or "Policy Entries",
    })


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


if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user_id = ""
    st.session_state.expiry = ""

if "pdf_uploader_key" not in st.session_state:
    st.session_state.pdf_uploader_key = 0

if "saved_health_rows" not in st.session_state:
    st.session_state.saved_health_rows = None

if "batch_history" not in st.session_state:
    st.session_state.batch_history = []

if "round_counter" not in st.session_state:
    st.session_state.round_counter = 0

if "mode2_settings_loaded" not in st.session_state:
    st.session_state.mode2_settings_loaded = False
    st.session_state.fixed_sheet_url = ""
    st.session_state.fixed_sheet_tab = "Policy Entries"
    st.session_state.local_excel_path = ""
    st.session_state.local_sheet_name = "Policy Entries"


# --- LOGIN SCREEN ---
if not st.session_state.logged_in:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.title("🔐 Policy Entry Software Login")
        st.write("Apna User ID aur Password dalkar login karein.")

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
                        st.session_state.user_id = user_id.strip()
                        st.session_state.expiry = result.get("expiry", "")
                        st.session_state.saved_health_rows = None
                        st.session_state.mode2_settings_loaded = False
                        st.session_state.batch_history = []
                        st.session_state.round_counter = 0
                        st.rerun()
                    else:
                        st.error(result.get("message", "Login fail ho gaya."))


# --- MAIN POLICY ENTRY DASHBOARD ---
else:
    with st.sidebar:
        st.success(f"👤 User: **{st.session_state.user_id}**")
        st.info(f"📅 Plan Valid Till: **{st.session_state.expiry}**")
        st.divider()

        working_mode = st.radio(
            "⚙️ Working Mode Chunein",
            [
                "Mode 1: Cloud Portal (Excel Download)",
                "Mode 2: Fixed Excel / Sheet Auto-Entry (No Download)",
            ],
            index=0,
        )
        is_mode2 = working_mode.startswith("Mode 2")

        st.divider()
        policy_category = st.selectbox(
            "Policy Type Chunein",
            ["Health Insurance", "Motor Insurance (Coming Soon)", "SME Insurance (Coming Soon)"]
        )
        st.divider()
        st.download_button(
            "📋 Sample Client Master Download",
            data=build_sample_master_bytes(),
            file_name="Sample_Client_Master.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
        if st.button("Logout", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.user_id = ""
            st.session_state.saved_health_rows = None
            st.session_state.mode2_settings_loaded = False
            st.session_state.batch_history = []
            st.session_state.round_counter = 0
            st.session_state.pop("last_results", None)
            st.rerun()

    st.title("📄 Automatic Policy Entry Portal (24x7)")

    if policy_category != "Health Insurance":
        st.info(f"**{policy_category}** abhi setup ho raha hai. Filhaal **Health Insurance** chunein.")
        st.stop()

    # Load Mode 1 saved rows once
    if st.session_state.saved_health_rows is None:
        with st.spinner("Aapki purani saved Health Sheet load ho rahi hai..."):
            loaded_rows, load_err = load_saved_health_rows(st.session_state.user_id)
            st.session_state.saved_health_rows = loaded_rows
            if load_err:
                st.warning(f"⚠️ Cloud sheet load notice: {load_err}")

    # Load Mode 2 saved settings once
    if not st.session_state.mode2_settings_loaded:
        s_url, s_tab = load_user_mode2_settings(st.session_state.user_id)
        l_path, l_tab = load_local_excel_path()
        st.session_state.fixed_sheet_url = s_url
        st.session_state.fixed_sheet_tab = s_tab
        st.session_state.local_excel_path = l_path
        st.session_state.local_sheet_name = l_tab
        st.session_state.mode2_settings_loaded = True

    # --- MODE 2 CONFIGURATION PANEL ---
    mode2_target_type = "google_sheet"
    if is_mode2:
        with st.container(border=True):
            st.subheader("🎯 Mode 2 Setup — Fixed Location Auto-Entry (Zero Download)")

            target_options = ["☁️ Fixed Google Sheet (Online Website par 24x7 chalega)"]
            if not IS_CLOUD:
                target_options.insert(0, "💻 Direct Local PC Excel (.xlsx) — Seedha PC File me Entry")

            chosen_target = st.radio(
                "Entry kahan directly save karni hai?",
                target_options,
                horizontal=True,
            )

            if chosen_target.startswith("💻"):
                mode2_target_type = "local_excel"
                c_p1, c_p2, c_p3 = st.columns([3, 1.2, 1])
                with c_p1:
                    local_path_input = st.text_input(
                        "Fixed Excel File Path (.xlsx)",
                        value=st.session_state.local_excel_path,
                        placeholder=r"e.g. I:\My Drive\POLICY ENTRY EXCEL\POLICY ENTRY SHEET FOR HEALTH.xlsx",
                    )
                with c_p2:
                    local_tab_input = st.text_input(
                        "Sheet Tab Name",
                        value=st.session_state.local_sheet_name,
                        placeholder="Policy Entries",
                    )
                with c_p3:
                    st.write("")
                    st.write("")
                    if st.button("💾 Save Path", use_container_width=True):
                        st.session_state.local_excel_path = local_path_input.strip().strip('"')
                        st.session_state.local_sheet_name = local_tab_input.strip() or "Policy Entries"
                        save_local_excel_path(st.session_state.local_excel_path, st.session_state.local_sheet_name)
                        st.success("Fixed Excel path save ho gaya!")

                st.session_state.local_excel_path = local_path_input.strip().strip('"')
                st.session_state.local_sheet_name = local_tab_input.strip() or "Policy Entries"

                if st.session_state.local_excel_path and os.path.exists(st.session_state.local_excel_path):
                    st.caption(f"✅ File mil gayi: `{st.session_state.local_excel_path}` — Nayi entries purani entry ke turant neeche judengi (Excel band rakhna zaroori hai).")
                elif st.session_state.local_excel_path:
                    st.caption(f"🆕 Nayi file is path par pehli entry ke saath apne aap ban jayegi: `{st.session_state.local_excel_path}`")
            else:
                mode2_target_type = "google_sheet"
                c_g1, c_g2, c_g3 = st.columns([3, 1.2, 1])
                with c_g1:
                    sheet_url_input = st.text_input(
                        "Apni Fixed Google Sheet ka URL ya Sheet ID dalein",
                        value=st.session_state.fixed_sheet_url,
                        placeholder="https://docs.google.com/spreadsheets/d/xxxxx/edit",
                    )
                with c_g2:
                    sheet_tab_input = st.text_input(
                        "Sheet Tab Name",
                        value=st.session_state.fixed_sheet_tab,
                        placeholder="Policy Entries",
                    )
                with c_g3:
                    st.write("")
                    st.write("")
                    if st.button("💾 Save Sheet Link", use_container_width=True):
                        st.session_state.fixed_sheet_url = sheet_url_input.strip()
                        st.session_state.fixed_sheet_tab = sheet_tab_input.strip() or "Policy Entries"
                        s_res = save_user_mode2_settings(
                            st.session_state.user_id,
                            st.session_state.fixed_sheet_url,
                            st.session_state.fixed_sheet_tab,
                        )
                        if s_res.get("success"):
                            st.success("Fixed Sheet link save ho gaya!")
                        else:
                            st.error(s_res.get("message", "Save nahi ho paya."))

                st.session_state.fixed_sheet_url = sheet_url_input.strip()
                st.session_state.fixed_sheet_tab = sheet_tab_input.strip() or "Policy Entries"

                if st.session_state.fixed_sheet_url:
                    st.link_button("🔗 Apni Fixed Google Sheet Kholen", st.session_state.fixed_sheet_url)
                if IS_CLOUD:
                    st.caption("💡 Online website se seedha Google Sheet me bina download ke live entry hoti hai. PC ki local `.xlsx` file me direct entry ke liye isi app ko local PC par `.bat` se chalayein.")

    # --- UPLOAD SECTION ---
    col_left, col_right = st.columns([1, 2])

    with col_left:
        st.subheader("1️⃣ Client Master (Optional)")
        master_file = st.file_uploader(
            "Apni Client Master Excel/CSV upload karein (Client Code, Mobile, Mail Id, Sub agent, Family code ke liye)",
            type=["xlsx", "csv"],
            key="client_master_uploader"
        )

    with col_right:
        hdr1, hdr2 = st.columns([3, 1])
        with hdr1:
            st.subheader("2️⃣ Policy PDFs Upload Karein")
        with hdr2:
            if st.button("🗑️ Clear All PDFs", use_container_width=True):
                st.session_state.pdf_uploader_key += 1
                st.rerun()

        uploaded_pdfs = st.file_uploader(
            "Ek ya ek se zyada Health Policy PDF select karein",
            type=["pdf"],
            accept_multiple_files=True,
            key=f"pdf_uploader_{st.session_state.pdf_uploader_key}"
        )

    skip_duplicates = st.checkbox(
        "Duplicate Policy auto-skip karein (Agar same Policy Number + Expiry Date pehle se sheet me saved ho)",
        value=True
    )

    btn_label = (
        "🚀 Start Policy Entry (Mode 2: Direct Fixed Excel/Sheet me Save Karein)"
        if is_mode2
        else "🚀 Start Policy Entry (Mode 1: Cloud Portal)"
    )

    if st.button(btn_label, type="primary", use_container_width=True):
        if not uploaded_pdfs:
            st.warning("Pehle kam se kam ek Policy PDF upload karein.")
        elif is_mode2 and mode2_target_type == "google_sheet" and not st.session_state.fixed_sheet_url:
            st.warning("Mode 2 ke liye pehle upar apni Fixed Google Sheet ka URL ya Sheet ID dalein.")
        elif is_mode2 and mode2_target_type == "local_excel" and not st.session_state.local_excel_path:
            st.warning("Mode 2 ke liye pehle upar apni Fixed Local Excel (.xlsx) file ka path dalein.")
        else:
            master_df = None
            if master_file is not None:
                try:
                    master_file.seek(0)
                    if master_file.name.lower().endswith(".csv"):
                        master_df = pd.read_csv(master_file, dtype=str)
                    else:
                        master_df = pd.read_excel(master_file, dtype=str)
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

            save_msg = ""
            save_error = ""
            skipped_count = 0

            # --- SAVE LOGIC: MODE 2 vs MODE 1 ---
            if is_mode2:
                if mode2_target_type == "local_excel":
                    save_local_excel_path(st.session_state.local_excel_path, st.session_state.local_sheet_name)
                    with st.spinner("Fixed Local Excel (.xlsx) me purani entry ke neeche save ho raha hai..."):
                        ok, msg, added, skipped, total_cnt = append_rows_to_local_excel(
                            st.session_state.local_excel_path,
                            extracted_rows,
                            sheet_name=st.session_state.local_sheet_name,
                            skip_duplicates=skip_duplicates,
                        )
                    skipped_count = skipped
                    if ok:
                        save_msg = f"✅ Mode 2 Direct Save: {msg} (Total Entries in Excel: {total_cnt}) — Download ki zaroorat nahi!"
                    else:
                        save_error = f"❌ {msg}"
                else:
                    save_user_mode2_settings(
                        st.session_state.user_id,
                        st.session_state.fixed_sheet_url,
                        st.session_state.fixed_sheet_tab,
                    )
                    with st.spinner("Aapki Fixed Google Sheet me purani entry ke neeche direct save ho raha hai..."):
                        g_res = call_backend({
                            "action": "append_to_fixed_sheet",
                            "user_id": st.session_state.user_id,
                            "sheet_url": st.session_state.fixed_sheet_url,
                            "sheet_tab": st.session_state.fixed_sheet_tab,
                            "skip_duplicates": skip_duplicates,
                            "rows": extracted_rows,
                        })
                    if g_res.get("success"):
                        skipped_count = g_res.get("skipped", 0)
                        added_cnt = g_res.get("added", 0)
                        s_name = g_res.get("sheet_name", "Fixed Sheet")
                        t_name = g_res.get("tab_name", st.session_state.fixed_sheet_tab)
                        tot_cnt = g_res.get("total_rows", "")
                        save_msg = f"✅ Mode 2 Direct Save: {added_cnt} nayi entries seedha '{s_name} → {t_name}' me save ho gayi! (Total Entries: {tot_cnt}) — Download ki zaroorat nahi!"
                    else:
                        save_error = f"❌ Fixed Google Sheet save fail: {g_res.get('message', 'Unknown error')}"
            else:
                # MODE 1 (Original Cloud Save + Download Excel)
                existing_keys = set()
                for r in (st.session_state.saved_health_rows or []):
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
                "batch_rows": extracted_rows,
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
            st.subheader("📋 Is Round me Add Hui Entries (Preview)")
            st.dataframe(pd.DataFrame(res["batch_rows"], columns=OUTPUT_COLUMNS), use_container_width=True, hide_index=True)

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
            master_excel_bytes = build_excel_bytes(saved_rows)
            st.download_button(
                f"📥 Download {DEFAULT_HEALTH_EXCEL_NAME} ({len(saved_rows)} Entries)",
                data=master_excel_bytes,
                file_name=DEFAULT_HEALTH_EXCEL_NAME,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                use_container_width=True
            )
            st.dataframe(pd.DataFrame(saved_rows, columns=OUTPUT_COLUMNS), use_container_width=True, hide_index=True)

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
