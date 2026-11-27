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
    2. Annexure / Member-List-only PDFs
    3. E-Card / Health Card-only PDFs
    4. Standalone Tax Invoice-only PDFs (no Policy Period / Period of Insurance)
    """
    if is_scanned_error(is_ok, err_msg):
        return err_msg or "Scanned / Image PDF (text readable nahi hai)"

    raw_text = str((debug_info or {}).get("raw_text") or "")
    has_period_fields = bool(
        re.search(
            r"(?i)(?:Period\s*of\s*Insurance|Policy\s*Period|Commencement\s*Date|Travel\s*Dates|Endorsement\s*Number|Policy\s*Effective\s*from)",
            raw_text,
        )
    )
    has_schedule_fields = has_period_fields or bool(
        re.search(r"(?i)(?:Total\s*Premium|Gross\s*Premium|Net\s*Premium|Final\s*Premium)", raw_text)
    )

    has_annex_marker = bool(
        re.search(r"(?i)annexure\s+attached\s+to\s+and\s+forming\s+(?:a\s+)?part\s+of", raw_text)
        or re.search(r"(?i)\bannexure\b", str(fname or ""))
    )
    if has_annex_marker and not has_schedule_fields:
        return "Annexure / Member List PDF (Not a Policy Schedule — Skipped)"

    has_ecard_marker = bool(
        re.search(r"(?i)\b(?:e[\-\s]?cards?|health[\-\s]?cards?|id[\-\s]?cards?)\b", str(fname or ""))
        or (re.search(r"(?i)Card\s*No\s*[\r\n\s]*:", raw_text) and re.search(r"(?i)Emp\.?\s*ID", raw_text))
    )
    if has_ecard_marker and not has_schedule_fields:
        return "E-Card / Health ID Card PDF (Not a Policy Schedule — Skipped)"

    has_tax_inv_marker = bool(
        re.search(r"(?i)\btax\s*invo?i?ce\b", str(fname or ""))
        or re.match(r"(?i)^\s*TAX\s+INVOICE\b", raw_text)
    )
    if has_tax_inv_marker and not has_period_fields:
        return "Standalone Tax Invoice PDF (Not a Policy Schedule — Skipped)"

    return ""


def parse_retest_row_numbers(spec: str, total_rows: int) -> list:
    """
    Parses 1-based row numbers like '1, 5, 12' or '2-4, 9' into sorted unique 0-based indices.
    Returns [] if blank or no valid row numbers found (meaning re-test all PDFs).
    """
    if not spec or total_rows <= 0:
        return []
    indices = set()
    for part in re.split(r"[,;\s]+", str(spec).strip()):
        if not part:
            continue
        m_rng = re.fullmatch(r"(\d+)\-(\d+)", part)
        if m_rng:
            a, b = int(m_rng.group(1)), int(m_rng.group(2))
            if a > b:
                a, b = b, a
            for n in range(a, b + 1):
                if 1 <= n <= total_rows:
                    indices.add(n - 1)
        elif part.isdigit():
            n = int(part)
            if 1 <= n <= total_rows:
                indices.add(n - 1)
    return sorted(indices)


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


def run_preview_retest(ctx, res, target_indices=None):
    """
    Reloads latest parsers and re-parses ONLY selected bug PDFs (or all cached PDFs if none selected).
    Updates only those rows in-place so existing row numbering & 🔴/🟢 highlights stay 100% intact.
    """
    cached_pdfs = res.get("retest_pdfs") or []
    if not cached_pdfs:
        st.warning("No cached PDFs found for this batch — please run a fresh batch once to enable 1-click Re-Test.")
        return

    existing_rows = list(res.get("batch_rows") or [])
    existing_debugs = list(res.get("debug_list") or [])
    valid_indices = sorted({i for i in (target_indices or []) if 0 <= i < len(cached_pdfs)})
    is_partial = bool(valid_indices) and (len(existing_rows) == len(cached_pdfs))

    indices_to_run = valid_indices if is_partial else list(range(len(cached_pdfs)))
    cnt = len(indices_to_run)
    spinner_msg = (
        f"🔄 Reloading latest parsers & re-testing {cnt} selected bug PDF{'s' if cnt != 1 else ''}..."
        if is_partial
        else f"🔄 Reloading latest parsers & re-testing all {cnt} PDFs..."
    )

    with st.spinner(spinner_msg):
        fresh_process_pdf, fresh_project_schema = reload_health_parsers()
        master_df = get_active_master_df(ctx["manual_master_file"])
        accounts_df = get_active_accounts_df("health", ctx["manual_acc_files"])

        parsed_rows = []
        parsed_debugs = []
        for idx in indices_to_run:
            item = cached_pdfs[idx]
            row_dict, _is_ok, _err_msg, debug_info = fresh_process_pdf(
                item["file_name"],
                item["pdf_bytes"],
                master_df,
                accounts_df=accounts_df,
            )
            parsed_rows.append(row_dict)
            parsed_debugs.append(debug_info)

        if parsed_rows:
            apply_share_commission(
                parsed_rows,
                st.session_state.health_share_under60,
                st.session_state.health_share_60plus,
            )
            if st.session_state.health_renewal_folder_url:
                apply_renewal_list_lookup(parsed_rows, st.session_state.health_renewal_folder_url)

        proj_rows, proj_schema = fresh_project_schema(parsed_rows, st.session_state.health_custom_columns)

        if is_partial and (res.get("batch_columns") == proj_schema["headers"]):
            for pos, idx in enumerate(indices_to_run):
                existing_rows[idx] = proj_rows[pos]
                if idx < len(existing_debugs):
                    existing_debugs[idx] = parsed_debugs[pos]
            res["batch_rows"] = existing_rows
            res["debug_list"] = existing_debugs
            row_labels = ", ".join(str(i + 1) for i in indices_to_run)
            res["last_retest_scope"] = f"{cnt} Selected PDF{'s' if cnt != 1 else ''} (Rows: {row_labels})"
        else:
            res["batch_rows"] = proj_rows
            res["batch_columns"] = proj_schema["headers"]
            res["debug_list"] = parsed_debugs
            res["last_retest_scope"] = f"All {cnt} PDFs"

        res["retest_count"] = int(res.get("retest_count", 0)) + 1
        res["retest_time"] = datetime.now(IST).strftime("%I:%M:%S %p")
