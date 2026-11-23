import io
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
)

st.set_page_config(page_title="Policy Entry Portal", page_icon="📄", layout="wide")

WEB_APP_URL = st.secrets["WEB_APP_URL"]
SECRET_KEY = st.secrets["SECRET_KEY"]
IST = timezone(timedelta(hours=5, minutes=30))
DEFAULT_HEALTH_EXCEL_NAME = "POLICY ENTRY SHEET FOR HEALTH.xlsx"
MAX_PDF_ROUNDS = 5


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
            st.session_state.batch_history = []
            st.session_state.round_counter = 0
            st.session_state.pop("last_results", None)
            st.rerun()

    st.title("📄 Automatic Policy Entry Portal (24x7)")

    if policy_category != "Health Insurance":
        st.info(f"**{policy_category}** abhi setup ho raha hai. Filhaal **Health Insurance** chunein.")
        st.stop()

    # Login ke baad pehli baar user ki purani saved entries cloud se load karein
    if st.session_state.saved_health_rows is None:
        with st.spinner("Aapki purani saved Health Sheet load ho rahi hai..."):
            loaded_rows, load_err = load_saved_health_rows(st.session_state.user_id)
            st.session_state.saved_health_rows = loaded_rows
            if load_err:
                st.warning(f"⚠️ Cloud sheet load notice: {load_err}")

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

    if st.button("🚀 Start Policy Entry", type="primary", use_container_width=True):
        if not uploaded_pdfs:
            st.warning("Pehle kam se kam ek Policy PDF upload karein.")
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

            existing_keys = set()
            for r in (st.session_state.saved_health_rows or []):
                pno = str(r.get("Policy Number", "")).strip()
                exp = str(r.get("Expiry Date", "")).strip()
                if pno:
                    existing_keys.add((pno, exp))

            new_rows_to_save = []
            batch_rows = []
            done_files = []
            error_files = []
            error_details = []
            debug_list = []
            skipped_count = 0

            progress = st.progress(0)
            status_text = st.empty()

            for idx, pdf in enumerate(uploaded_pdfs):
                status_text.text(f"Processing ({idx + 1}/{len(uploaded_pdfs)}): {pdf.name}")
                pdf_bytes = pdf.read()
                row_dict, is_ok, err_msg, debug_info = process_health_pdf(pdf.name, pdf_bytes, master_df)
                debug_list.append(debug_info)

                pno = str(row_dict.get("Policy Number", "")).strip()
                exp = str(row_dict.get("Expiry Date", "")).strip()
                key = (pno, exp)

                if skip_duplicates and pno and key in existing_keys:
                    skipped_count += 1
                else:
                    batch_rows.append(row_dict)
                    new_rows_to_save.append(row_dict)
                    if pno:
                        existing_keys.add(key)

                if is_ok:
                    comp = row_dict["Company Name"].replace(" ", "_")
                    done_files.append((f"{comp}_{pdf.name}", pdf_bytes))
                else:
                    error_files.append((pdf.name, pdf_bytes))
                    error_details.append({"File Name": pdf.name, "Reason": err_msg})

                progress.progress((idx + 1) / len(uploaded_pdfs))

            status_text.empty()
            progress.empty()

            # Nayi entries ko purani saved entries ke neeche cloud me permanently save karein
            save_msg = ""
            if new_rows_to_save:
                with st.spinner("Nayi entries aapki master sheet me save ho rahi hain..."):
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
                "timestamp": ts_file,
                "time_display": ts_display,
                "total_count": len(done_files) + len(error_files),
                "done_count": len(done_files),
                "error_count": len(error_files),
                "skipped_count": skipped_count,
                "save_msg": save_msg,
                "error_details": error_details,
                "all_zip_bytes": all_zip_bytes,
                "err_zip_bytes": err_zip_bytes,
            }

            # Last 5 rounds ki history rakhein (sabse naya sabse upar)
            st.session_state.batch_history.insert(0, batch_record)
            st.session_state.batch_history = st.session_state.batch_history[:MAX_PDF_ROUNDS]

            st.session_state["last_results"] = {
                **batch_record,
                "debug_list": debug_list,
            }

            # Entry complete hote hi PDF box auto-clear (Client Master wahi rahega)
            st.session_state.pdf_uploader_key += 1
            st.rerun()

    # --- LAST BATCH SUMMARY (CURRENT ROUND) ---
    if "last_results" in st.session_state:
        res = st.session_state["last_results"]
        st.divider()
        if res.get("save_msg"):
            st.success(res["save_msg"])
        if res.get("skipped_count", 0) > 0:
            st.info(f"ℹ️ {res['skipped_count']} duplicate policy pehle se saved thi, isliye dobara add nahi ki gayi.")

        st.subheader(f"⚡ Latest Round #{res['round_no']} ({res['time_display']})")
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

    # --- LAST 5 ROUNDS PDF DOWNLOAD HISTORY ---
    if st.session_state.batch_history:
        with st.expander(
            f"🗂️ Last {len(st.session_state.batch_history)} Rounds PDF Download History (Max {MAX_PDF_ROUNDS} Rounds)",
            expanded=(len(st.session_state.batch_history) > 1)
        ):
            st.caption("Purane rounds ki Done / Error PDFs yahan se kabhi bhi download kar sakte hain (jab tak browser tab khula hai / logout nahi karte).")
            for b in st.session_state.batch_history:
                c_info, c_all, c_err = st.columns([2.5, 1.5, 1.5])
                with c_info:
                    st.markdown(
                        f"**Round #{b['round_no']}** — `{b['time_display']}`  \n"
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

    # --- PERMANENT MASTER SHEET SECTION (OLD + NEW ENTRIES COMBINED) ---
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
    if "last_results" in st.session_state:
        with st.expander("🐞 Debug Mode — Kisi bhi PDF ka Raw Text & Company Score Dekhein"):
            debug_list = st.session_state["last_results"].get("debug_list", [])
            if debug_list:
                file_names = [d["file_name"] for d in debug_list]
                selected_name = st.selectbox("Debug karne ke liye PDF chunein:", file_names)
                selected_debug = next(d for d in debug_list if d["file_name"] == selected_name)

                st.write("**Detected Company:**", selected_debug["detected_company"] or "None")
                st.write("**Company Keyword Count:**", selected_debug["company_scores"] or "No match")
                if selected_debug["error_reason"]:
                    st.error(f"Error Reason: {selected_debug['error_reason']}")

                raw_txt = selected_debug["raw_text"] or ""
                st.download_button(
                    "📄 Download Raw Text (.txt)",
                    data=raw_txt.encode("utf-8"),
                    file_name=f"DEBUG_{selected_name}.txt",
                    mime="text/plain"
                )
                st.text_area("Extracted Text (Preview)", raw_txt[:6000], height=300)
