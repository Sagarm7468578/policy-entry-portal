import importlib
import re
import sys
from datetime import datetime, timedelta, timezone
import streamlit as st
from portal.backend import (
    apply_renewal_list_lookup,
    apply_share_commission,
)
from portal.state import (
    get_active_master_df,
    get_active_accounts_df,
)

IST = timezone(timedelta(hours=5, minutes=30))


def is_scanned_error(is_ok: bool, err_msg: str) -> bool:
    """Returns True when a PDF has no readable text layer (scanned/image-only)."""
    if is_ok:
        return False
    low = str(err_msg or "").lower()
    return ("scanned" in low) or ("image pdf" in low)


def get_skip_pdf_reason(fname: str, is_ok: bool, err_msg: str, debug_info: dict = None) -> str:
    """
    Returns a skip reason if a PDF should be excluded from Excel & Preview Mode:
    1. Scanned / Image-only PDFs
    2. Annexure / Member-List-only PDFs (no premium or policy period — not a Policy Schedule)
    """
    if is_scanned_error(is_ok, err_msg):
        return err_msg or "Scanned / Image PDF (text readable nahi hai)"

    raw_text = str((debug_info or {}).get("raw_text") or "")
    has_annex_marker = bool(
        re.search(r"(?i)annexure\s+attached\s+to\s+and\s+forming\s+(?:a\s+)?part\s+of", raw_text)
        or re.search(r"(?i)\bannexure\b", str(fname or ""))
    )
    if has_annex_marker:
        has_schedule_fields = bool(
            re.search(
                r"(?i)(?:Total\s*Premium|Gross\s*Premium|Net\s*Premium|Period\s*of\s*Insurance|Policy\s*Period|Commencement\s*Date)",
                raw_text,
            )
        )
        if not has_schedule_fields:
            return "Annexure / Member List PDF (Not a Policy Schedule — Skipped)"

    return ""


def reload_health_parsers():
    """Evicts cached parser modules and re-imports fresh code from disk for live Re-Test."""
    importlib.invalidate_caches()
    for mod_name in list(sys.modules.keys()):
        if mod_name == "health_parser" or mod_name == "health_parsers" or mod_name.startswith("health_parsers."):
            sys.modules.pop(mod_name, None)
    hp_mod = importlib.import_module("health_parser")
    return hp_mod.process_health_pdf, hp_mod.project_rows_to_schema


def attach_retest_cache(retest_pdfs: list, extracted_rows: list):
    """Stores current round's PDF bytes in memory so Admin can Re-Test Preview without saving to Excel."""
    if "last_results" not in st.session_state:
        return
    lr = st.session_state["last_results"]
    batch_rows = lr.get("batch_rows") or []
    if len(batch_rows) == len(retest_pdfs):
        lr["retest_pdfs"] = retest_pdfs
    else:
        kept_pols = {str(r.get("Policy Number", "")).strip() for r in batch_rows}
        lr["retest_pdfs"] = [
            item for item, er in zip(retest_pdfs, extracted_rows)
            if str(er.get("Policy Number", "")).strip() in kept_pols
        ]
    lr["retest_count"] = 0
    lr["retest_time"] = ""


def run_preview_retest(ctx, res):
    """Reloads latest parsers and re-parses cached PDFs for Preview Mode ONLY (no Excel/Sheet save)."""
    cached_pdfs = res.get("retest_pdfs") or []
    if not cached_pdfs:
        st.warning("No cached PDFs found for this batch — please run a fresh batch once to enable 1-click Re-Test.")
        return

    with st.spinner(f"🔄 Reloading latest parsers & re-testing {len(cached_pdfs)} PDFs (Preview only — No Excel save)..."):
        fresh_process_pdf, fresh_project_schema = reload_health_parsers()
        master_df = get_active_master_df(ctx["manual_master_file"])
        accounts_df = get_active_accounts_df("health", ctx["manual_acc_files"])

        new_rows = []
        new_debug_list = []
        for item in cached_pdfs:
            row_dict, _is_ok, _err_msg, debug_info = fresh_process_pdf(
                item["file_name"],
                item["pdf_bytes"],
                master_df,
                accounts_df=accounts_df,
            )
            new_rows.append(row_dict)
            new_debug_list.append(debug_info)

        if new_rows:
            apply_share_commission(
                new_rows,
                st.session_state.health_share_under60,
                st.session_state.health_share_60plus,
            )
            if st.session_state.health_renewal_folder_url:
                apply_renewal_list_lookup(new_rows, st.session_state.health_renewal_folder_url)

        proj_rows, proj_schema = fresh_project_schema(new_rows, st.session_state.health_custom_columns)
        res["batch_rows"] = proj_rows
        res["batch_columns"] = proj_schema["headers"]
        res["debug_list"] = new_debug_list
        res["retest_count"] = int(res.get("retest_count", 0)) + 1
        res["retest_time"] = datetime.now(IST).strftime("%I:%M:%S %p")
