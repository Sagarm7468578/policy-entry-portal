import io
import zipfile
from datetime import datetime, timedelta, timezone
import pandas as pd
import requests
import streamlit as st
from health_parser import (
    process_health_pdf,
    build_excel_bytes,
    build_sample_master_bytes,
)

st.set_page_config(page_title="Policy Entry Portal", page_icon="📄", layout="wide")

WEB_APP_URL = st.secrets["WEB_APP_URL"]
SECRET_KEY = st.secrets["SECRET_KEY"]
IST = timezone(timedelta(hours=5, minutes=30))


def call_backend(payload):
    payload["secret"] = SECRET_KEY
    try:
        res = requests.post(WEB_APP_URL, json=payload, timeout=30)
        return res.json()
    except Exception as e:
        return {"success": False, "message": f"Connection error: {e}"}


if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user_id = ""
    st.session_state.expiry = ""


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
            st.rerun()

    st.title("📄 Automatic Policy Entry Portal (24x7)")

    if policy_category != "Health Insurance":
        st.info(f"**{policy_category}** abhi setup ho raha hai. Filhaal **Health Insurance** chunein.")
        st.stop()

    col_left, col_right = st.columns([1, 2])

    with col_left:
        st.subheader("1️⃣ Client Master (Optional)")
        master_file = st.file_uploader(
            "Apni Client Master Excel/CSV upload karein (Client Code, Mobile, Mail Id, Sub agent, Family code ke liye)",
            type=["xlsx", "csv"]
        )

    with col_right:
        st.subheader("2️⃣ Policy PDFs Upload Karein")
        uploaded_pdfs = st.file_uploader(
            "Ek ya ek se zyada Health Policy PDF select karein",
            type=["pdf"],
            accept_multiple_files=True
        )

    if st.button("🚀 Start Policy Entry", type="primary", use_container_width=True):
        if not uploaded_pdfs:
            st.warning("Pehle kam se kam ek Policy PDF upload karein.")
        else:
            master_df = None
            if master_file is not None:
                try:
                    if master_file.name.lower().endswith(".csv"):
                        master_df = pd.read_csv(master_file, dtype=str)
                    else:
                        master_df = pd.read_excel(master_file, dtype=str)
                except Exception as e:
                    st.warning(f"Client Master read nahi ho payi ({e}). Bina master ke entry kar rahe hain.")

            rows = []
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
                rows.append(row_dict)
                debug_list.append(debug_info)

                if is_ok:
                    comp = row_dict["Company Name"].replace(" ", "_")
                    done_files.append((f"{comp}_{pdf.name}", pdf_bytes))
                else:
                    error_files.append((pdf.name, pdf_bytes))
                    error_details.append({"File Name": pdf.name, "Reason": err_msg})

                progress.progress((idx + 1) / len(uploaded_pdfs))

            status_text.empty()
            progress.empty()

            excel_bytes = build_excel_bytes(rows)

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

            st.session_state["last_results"] = {
                "rows": rows,
                "done_count": len(done_files),
                "error_count": len(error_files),
                "error_details": error_details,
                "debug_list": debug_list,
                "excel_bytes": excel_bytes,
                "all_zip_bytes": all_zip_bytes,
                "err_zip_bytes": err_zip_bytes,
                "timestamp": datetime.now(IST).strftime("%Y%m%d_%H%M"),
            }

    # --- RESULTS & DOWNLOAD SECTION ---
    if "last_results" in st.session_state:
        res = st.session_state["last_results"]
        st.divider()

        m1, m2, m3 = st.columns(3)
        m1.metric("Total PDFs", res["done_count"] + res["error_count"])
        m2.metric("Done (YES) ✅", res["done_count"])
        m3.metric("Error (Check Karein) ❌", res["error_count"])

        d1, d2, d3 = st.columns(3)
        with d1:
            st.download_button(
                "📥 Download Policy Entry Excel (.xlsx)",
                data=res["excel_bytes"],
                file_name=f"Health_Policy_Entry_{res['timestamp']}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                use_container_width=True
            )
        with d2:
            st.download_button(
                "📦 Download Sorted PDFs (Done + Error ZIP)",
                data=res["all_zip_bytes"],
                file_name=f"Sorted_Policies_{res['timestamp']}.zip",
                mime="application/zip",
                use_container_width=True
            )
        with d3:
            if res["err_zip_bytes"]:
                st.download_button(
                    "⚠️ Download Only Error PDFs (ZIP)",
                    data=res["err_zip_bytes"],
                    file_name=f"Error_Policies_{res['timestamp']}.zip",
                    mime="application/zip",
                    use_container_width=True
                )

        if res["error_details"]:
            st.warning("Neeche di gayi PDFs me problem aayi — ye `Error` folder me alag kar di gayi hain:")
            st.dataframe(pd.DataFrame(res["error_details"]), use_container_width=True, hide_index=True)

        st.subheader("📊 Extracted Policy Data Preview")
        st.dataframe(pd.DataFrame(res["rows"]), use_container_width=True, hide_index=True)

        with st.expander("🐞 Debug Mode — Kisi bhi PDF ka Raw Text & Company Score Dekhein"):
            debug_list = res.get("debug_list", [])
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
