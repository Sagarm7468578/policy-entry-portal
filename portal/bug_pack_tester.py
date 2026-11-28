import importlib
import re
import sys
from datetime import datetime, timedelta, timezone
import pandas as pd
import streamlit as st
from portal.backend import apply_share_commission
from portal.state import get_active_master_df, get_active_accounts_df

IST = timezone(timedelta(hours=5, minutes=30))

# Columns that depend on each user's personal Master / Renewal files rather than PDF parsing
_USER_MASTER_COLS = {
    "client code", "occupation", "mobile", "mail id", "sub agent",
    "accounts", "family code", "pyp premium", "our renewal",
}

_PREVIEW_CORE_COLS = [
    "PDF File", "Client Name", "Policy Number", "Sub Type", "Company Name",
    "Agency", "Plan Name", "Premium", "Sum Insured", "Inception Date",
    "Expiry Date", "Reminder Date", "Premium Mode", "Portability company",
    "Portability Year", "Policy Status", "PYP Number", "DOB", "Share", "Share %",
]


def parse_bug_pack_txt(pack_text: str, source_pack_name: str = "") -> dict:
    """
    Parses any Admin BUG_PACK_*.txt or User USER_BUG_PACK_*.txt file into structured entries
    containing reported [BUG] fields and the exact RAW PDF TEXT for live parser replay.
    """
    text = str(pack_text or "").replace("\r\n", "\n")
    meta = {
        "source_file": source_pack_name,
        "batch_id": "",
        "reported_by": "",
        "user_note": "",
        "entries": [],
    }

    m_batch = re.search(r"Batch ID:\s*([^\|\n]+)", text)
    if m_batch:
        meta["batch_id"] = m_batch.group(1).strip()
    m_rep = re.search(r"Reported By:\s*([^\n]+)", text)
    if m_rep:
        meta["reported_by"] = m_rep.group(1).strip()
    m_note = re.search(r"User Note\s*:\s*([^\n]+)", text)
    if m_note:
        meta["user_note"] = m_note.group(1).strip()

    # Split into individual BUG ENTRY #N OF M blocks
    entry_starts = [m.start() for m in re.finditer(r"BUG ENTRY #\d+\s+OF\s+\d+", text)]
    for i, start_pos in enumerate(entry_starts):
        end_pos = entry_starts[i + 1] if i + 1 < len(entry_starts) else len(text)
        block = text[start_pos:end_pos]

        def _grab(label: str) -> str:
            m_lbl = re.search(rf"^{label}\s*:\s*(.*)$", block, re.M)
            return m_lbl.group(1).strip() if m_lbl else ""

        pdf_file = _grab("PDF FILE")
        client_name = _grab("CLIENT NAME")
        company_name = _grab("COMPANY NAME")
        plan_name = _grab("PLAN NAME")

        bugs = []
        for m_b in re.finditer(r'^\s*-\s*\[BUG\]\s*([^:]+?):\s*"(.*)"\s*$', block, re.M):
            bugs.append({"col": m_b.group(1).strip(), "before": m_b.group(2).strip()})

        raw_text = ""
        m_raw = re.search(
            r"--- RAW PDF TEXT START \([^\n]*\) ---\n([\s\S]*?)\n--- RAW PDF TEXT END \([^\n]*\) ---",
            block,
        )
        if m_raw:
            raw_text = m_raw.group(1)

        if pdf_file or raw_text:
            meta["entries"].append({
                "source_pack": source_pack_name,
                "reported_client": client_name,
                "reported_company": company_name,
                "reported_plan": plan_name,
                "pdf_file": pdf_file or f"Entry_{i + 1}.pdf",
                "bugs": bugs,
                "raw_text": raw_text,
            })

    return meta


def _reload_text_processor():
    """Reloads latest health_parser + all health_parsers.plans from disk so GitHub commits work live."""
    importlib.invalidate_caches()
    for mod_name in list(sys.modules.keys()):
        if mod_name == "health_parser" or mod_name == "health_parsers" or mod_name.startswith("health_parsers."):
            sys.modules.pop(mod_name, None)
    hp_mod = importlib.import_module("health_parser")
    return hp_mod.process_health_text, hp_mod.project_rows_to_schema


def _lookup_col_value(col_name: str, raw_row: dict, proj_row: dict) -> str:
    """Resolves a bug column name against both projected custom headers and standard system fields."""
    target = col_name.strip().lower()
    for d in (proj_row, raw_row):
        for k, v in (d or {}).items():
            if str(k).strip().lower() == target:
                s = str(v if v is not None else "").strip()
                return s if s else "[BLANK]"
    return "[BLANK]"


def _run_bug_pack_replay(ctx, entries: list, use_my_masters: bool = False):
    """Runs all Bug Pack entries through fresh parsers and builds Before-vs-After scorecard + full rows."""
    process_text_fn, project_schema_fn = _reload_text_processor()
    master_df = get_active_master_df(ctx["manual_master_file"]) if use_my_masters else None
    accounts_df = get_active_accounts_df("health", ctx["manual_acc_files"]) if use_my_masters else None

    scorecard = []
    full_rows = []
    error_list = []

    for ent in entries:
        fname = ent["pdf_file"]
        raw_text = ent["raw_text"]
        if not raw_text or raw_text.strip() == "[Raw PDF text not available]":
            error_list.append({"PDF File": fname, "Reason": "Raw PDF text not found inside Bug Pack .txt"})
            continue

        row_dict, is_ok, err_msg, _dbg = process_text_fn(
            fname, raw_text, master_df=master_df, accounts_df=accounts_df
        )
        apply_share_commission(
            [row_dict],
            st.session_state.health_share_under60,
            st.session_state.health_share_60plus,
        )
        proj_rows, _ = project_schema_fn([row_dict], st.session_state.health_custom_columns)
        proj_row = proj_rows[0] if proj_rows else row_dict

        if not is_ok and err_msg:
            error_list.append({"PDF File": fname, "Reason": err_msg})

        row_view = {"PDF File": fname}
        for c in _PREVIEW_CORE_COLS[1:]:
            row_view[c] = row_dict.get(c, "")
        full_rows.append(row_view)

        for b in ent.get("bugs", []):
            col_nm = b["col"]
            before_val = b["before"] or "[BLANK]"
            after_val = _lookup_col_value(col_nm, row_dict, proj_row)

            norm_before = before_val.strip().upper()
            norm_after = after_val.strip().upper()
            is_master_col = col_nm.strip().lower() in _USER_MASTER_COLS

            if norm_after != norm_before and norm_after != "[BLANK]":
                status = "🟢 FIXED"
            elif norm_after != norm_before:
                status = "🟡 CHANGED"
            elif is_master_col and not use_my_masters:
                status = "⚪ User Master Field"
            else:
                status = "🔴 STILL SAME"

            scorecard.append({
                "PDF File": fname,
                "Client (Live)": row_dict.get("Client Name") or ent.get("reported_client") or "—",
                "Company": row_dict.get("Company Name") or ent.get("reported_company") or "—",
                "Plan": row_dict.get("Plan Name") or ent.get("reported_plan") or "—",
                "Bug Column": col_nm,
                "Before (Reported)": before_val,
                "After Fix (Live)": after_val,
                "Status": status,
            })

    return {
        "scorecard": scorecard,
        "full_rows": full_rows,
        "errors": error_list,
        "run_time": datetime.now(IST).strftime("%I:%M:%S %p"),
        "entry_count": len(entries),
    }


def render_bug_pack_tester(ctx):
    """Renders the Admin '🧪 Test User Bug Pack (.txt)' replay tool inside Bugging Mode."""
    st.info(
        "🧪 **Zero-PDF Bug Pack Verifier:** User ke Gmail par aayi **`USER_BUG_PACK_...txt`** (ya apni `BUG_PACK_...txt`) "
        "upload karein — bina original PDF ke, latest GitHub parsers par live **Before vs After** check ho jayega!"
    )

    uploaded_packs = st.file_uploader(
        "Upload 1 or more Bug Pack files (.txt)",
        type=["txt"],
        accept_multiple_files=True,
        key="bug_pack_txt_uploader",
    )

    if not uploaded_packs:
        st.session_state.pop("bug_pack_replay_res", None)
        st.session_state.pop("bug_pack_replay_sig", None)
        return

    all_entries = []
    pack_notes = []
    sig_parts = []
    for f in uploaded_packs:
        raw_bytes = f.getvalue()
        sig_parts.append(f"{f.name}:{len(raw_bytes)}")
        parsed = parse_bug_pack_txt(raw_bytes.decode("utf-8", errors="ignore"), source_pack_name=f.name)
        all_entries.extend(parsed["entries"])
        if parsed.get("reported_by") or parsed.get("user_note"):
            note_part = f" — Note: *{parsed['user_note']}*" if parsed.get("user_note") else ""
            pack_notes.append(f"📄 `{f.name}` ({len(parsed['entries'])} entries) | {parsed.get('reported_by', 'Admin')}{note_part}")

    if pack_notes:
        st.caption("  \n".join(pack_notes))

    if not all_entries:
        st.warning("⚠️ Uploaded `.txt` file me koi `BUG ENTRY` / `RAW PDF TEXT` block nahi mila. Please valid Policy Mitra Bug Pack upload karein.")
        return

    c_opt, c_btn = st.columns([2.2, 1.4])
    with c_opt:
        use_my_masters = st.checkbox(
            "Also apply my linked Client Master & Accounts rules (optional)",
            value=False,
            key="bug_pack_use_masters",
            help="Off rakhein to sirf pure PDF parser output verify hoga (recommended for remote users' bug packs).",
        )
    with c_btn:
        manual_rerun = st.button(
            f"🔄 Re-Test Bug Pack ({len(all_entries)} Entries)",
            type="primary",
            use_container_width=True,
            key="btn_retest_bug_pack_txt",
        )

    curr_sig = "|".join(sig_parts) + f"|masters={use_my_masters}"
    if manual_rerun or st.session_state.get("bug_pack_replay_sig") != curr_sig or "bug_pack_replay_res" not in st.session_state:
        with st.spinner(f"🔄 Reloading latest parsers & testing {len(all_entries)} Bug Pack entries..."):
            st.session_state["bug_pack_replay_res"] = _run_bug_pack_replay(ctx, all_entries, use_my_masters=use_my_masters)
            st.session_state["bug_pack_replay_sig"] = curr_sig

    res = st.session_state["bug_pack_replay_res"]
    scorecard = res["scorecard"]
    fixed_cnt = sum(1 for r in scorecard if r["Status"].startswith("🟢"))
    pending_cnt = sum(1 for r in scorecard if r["Status"].startswith("🔴"))
    master_cnt = sum(1 for r in scorecard if r["Status"].startswith("⚪"))

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Entries Tested", res["entry_count"])
    m2.metric("Reported Bugs", len(scorecard))
    m3.metric("Fixed 🟢", fixed_cnt)
    m4.metric("Pending 🔴", pending_cnt)

    if pending_cnt == 0 and fixed_cnt > 0:
        extra = f" ({master_cnt} user-master fields skipped)" if master_cnt else ""
        st.success(f"🎉 All {fixed_cnt} PDF parser bugs FIXED! (Verified at {res['run_time']}){extra}")
    elif pending_cnt > 0:
        st.warning(f"⚠️ {pending_cnt} bug(s) still unchanged (Checked at {res['run_time']}). Commit parser fix and click **🔄 Re-Test Bug Pack**.")

    if res["errors"]:
        st.error("Some entries had errors during replay:")
        st.dataframe(pd.DataFrame(res["errors"]), use_container_width=True, hide_index=True)

    if scorecard:
        st.subheader("🎯 Before vs After Verification Scorecard")
        df_sc = pd.DataFrame(scorecard)

        def _style_status(val: str):
            if str(val).startswith("🟢"):
                return "background-color: #dcfce7; color: #166534; font-weight: 700;"
            if str(val).startswith("🔴"):
                return "background-color: #fee2e2; color: #991b1b; font-weight: 700;"
            if str(val).startswith("🟡"):
                return "background-color: #fef9c3; color: #854d0e; font-weight: 700;"
            return "background-color: #f1f5f9; color: #475569;"

        styler = df_sc.style
        styled_df = styler.map(_style_status, subset=["Status"]) if hasattr(styler, "map") else styler.applymap(_style_status, subset=["Status"])
        st.dataframe(
            styled_df,
            use_container_width=True,
            hide_index=True,
            height=min(120 + len(df_sc) * 36, 460),
        )

    if res["full_rows"]:
        with st.expander(f"📋 Full Live Extracted Output ({len(res['full_rows'])} rows)", expanded=False):
            st.dataframe(
                pd.DataFrame(res["full_rows"]),
                use_container_width=True,
                hide_index=True,
                height=min(120 + len(res["full_rows"]) * 36, 460),
            )
