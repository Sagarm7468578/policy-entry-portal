import io
import os
import re
from datetime import date, datetime
import openpyxl
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from health_parsers.common import (
    OUTPUT_COLUMNS,
    DATE_FIELDS,
    DATE_FIELDS_LOWER,
    SYSTEM_FIELD_LOOKUP,
    parse_any_date,
    _norm_date_key,
)


def parse_custom_columns(spec_str: str):
    raw = str(spec_str or "").strip()
    if not raw:
        return [(c, c) for c in OUTPUT_COLUMNS]

    parts = re.split(r"[\r\n|]+", raw) if ("\n" in raw or "\r" in raw or "|" in raw) else raw.split(",")
    mapping, seen_headers = [], set()
    for part in parts:
        item = part.strip()
        if not item:
            continue
        if "=>" in item:
            src_raw, dst_raw = item.split("=>", 1)
            src_clean = src_raw.strip()
            dst_clean = dst_raw.strip() or src_clean
            src_canonical = SYSTEM_FIELD_LOOKUP.get(src_clean.lower(), "")
        else:
            dst_clean = item
            src_canonical = SYSTEM_FIELD_LOOKUP.get(item.lower(), "")

        key_lower = dst_clean.lower()
        if key_lower in seen_headers:
            continue
        seen_headers.add(key_lower)
        mapping.append((src_canonical, dst_clean))

    return mapping if mapping else [(c, c) for c in OUTPUT_COLUMNS]


def normalize_custom_columns_spec(spec_str: str) -> str:
    raw = str(spec_str or "").strip()
    if not raw:
        return ""
    parts = re.split(r"[\r\n|]+", raw) if ("\n" in raw or "\r" in raw or "|" in raw) else raw.split(",")
    cleaned, seen = [], set()
    for p in parts:
        item = p.strip()
        if not item:
            continue
        if "=>" in item:
            a, b = item.split("=>", 1)
            item = f"{a.strip()} => {b.strip()}"
            hdr_key = (b.strip() or a.strip()).lower()
        else:
            hdr_key = item.lower()
        if hdr_key not in seen:
            seen.add(hdr_key)
            cleaned.append(item)
    return " | ".join(cleaned)


def spec_to_multiline(spec_str: str) -> str:
    raw = str(spec_str or "").strip()
    if not raw:
        return "\n".join(OUTPUT_COLUMNS)
    parts = re.split(r"[\r\n|]+", raw) if ("\n" in raw or "\r" in raw or "|" in raw) else raw.split(",")
    lines = [p.strip() for p in parts if p.strip()]
    return "\n".join(lines) if lines else "\n".join(OUTPUT_COLUMNS)


def get_custom_schema_info(spec_str: str) -> dict:
    mapping = parse_custom_columns(spec_str)
    headers = [dst for _, dst in mapping]
    col_types = {}
    policy_col, expiry_col = "Policy Number", "Expiry Date"

    for src, dst in mapping:
        canonical = src or SYSTEM_FIELD_LOOKUP.get(dst.lower(), "")
        if canonical in {"Premium", "Sum Insured", "PYP premium", "Share", "Share %"}:
            col_types[dst] = "number"
        elif canonical == "Mobile":
            col_types[dst] = "mobile"
        elif canonical in {"Policy Number", "PYP Number"}:
            col_types[dst] = "policy_id"
        elif canonical in {"Client Code", "Family code"}:
            col_types[dst] = "code_id"
        elif canonical in DATE_FIELDS:
            col_types[dst] = "date"
        else:
            col_types[dst] = "text"

        if canonical == "Policy Number":
            policy_col = dst
        elif canonical == "Expiry Date":
            expiry_col = dst

    return {
        "mapping": mapping,
        "headers": headers,
        "col_types": col_types,
        "policy_col": policy_col,
        "expiry_col": expiry_col,
    }


def project_rows_to_schema(rows: list, spec_str: str):
    schema = get_custom_schema_info(spec_str)
    mapping = schema["mapping"]
    projected = []
    for r in rows:
        lower_r = {str(k).strip().lower(): v for k, v in r.items()}
        out = {}
        for src, dst in mapping:
            if src:
                val = r.get(src, "")
                if val == "" and src.lower() in lower_r:
                    val = lower_r[src.lower()]
                if val == "" and dst.lower() in lower_r:
                    val = lower_r[dst.lower()]
                out[dst] = val if val is not None else ""
            else:
                val = r.get(dst, "")
                if val == "" and dst.lower() in lower_r:
                    val = lower_r[dst.lower()]
                out[dst] = val if val is not None else ""
        projected.append(out)
    return projected, schema


def to_excel_value(col_name: str, raw_val, col_type: str = ""):
    if isinstance(raw_val, (datetime, date)):
        d_obj = raw_val.date() if isinstance(raw_val, datetime) else raw_val
        return d_obj, "dd-mm-yyyy"

    val = str(raw_val if raw_val is not None else "").strip()
    if not val:
        return "", None

    t = col_type
    if not t:
        c_low = col_name.lower()
        if c_low in {"premium", "sum insured", "pyp premium", "share", "share %"}:
            t = "number"
        elif c_low == "mobile":
            t = "mobile"
        elif c_low in {"policy number", "pyp number"}:
            t = "policy_id"
        elif c_low in {"client code", "family code"}:
            t = "code_id"
        elif c_low in DATE_FIELDS_LOWER:
            t = "date"
        else:
            t = "text"

    if t == "date":
        dt = parse_any_date(val)
        return (dt.date(), "dd-mm-yyyy") if dt else (val, None)

    if t == "number":
        cleaned = val.replace(",", "").replace("%", "").strip()
        if re.fullmatch(r"-?\d+", cleaned):
            return int(cleaned), "0"
        if re.fullmatch(r"-?\d+\.\d+", cleaned):
            return float(cleaned), "0.##"
        return val, None

    if t == "mobile":
        cleaned = re.sub(r"[\s\-]", "", val)
        return (int(cleaned), "0") if re.fullmatch(r"[1-9]\d{6,14}", cleaned) else (val, "@")

    if t == "policy_id":
        if re.fullmatch(r"[1-9]\d{0,14}", val):
            return int(val), "0"
        if re.fullmatch(r"\d{16,}", val):
            return f",{val}", "@"
        return val, "@"

    if t == "code_id":
        return (int(val), "0") if re.fullmatch(r"[1-9]\d{0,14}", val) else (val, "@")

    return val, None


def build_excel_bytes(rows: list, columns=None, col_types=None) -> bytes:
    cols = columns if columns else OUTPUT_COLUMNS
    types_map = col_types or {}

    wb = Workbook()
    ws = wb.active
    ws.title = "Policy Entries"

    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)

    for col_idx, col_name in enumerate(cols, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for r_idx, row_dict in enumerate(rows, start=2):
        for col_idx, col_name in enumerate(cols, start=1):
            parsed_val, num_fmt = to_excel_value(col_name, row_dict.get(col_name, ""), types_map.get(col_name, ""))
            cell = ws.cell(row=r_idx, column=col_idx, value=parsed_val)
            if num_fmt == "@":
                cell.data_type = "s"
                cell.number_format = "@"
            elif num_fmt:
                cell.number_format = num_fmt

    for col_idx, col_name in enumerate(cols, start=1):
        col_letter = ws.cell(row=1, column=col_idx).column_letter
        c_type = types_map.get(col_name, "")
        ws.column_dimensions[col_letter].width = max(
            len(col_name) + 4,
            22 if c_type == "policy_id" or col_name in {"Policy Number", "PYP Number"} else 16
        )

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


def build_sample_master_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Client Master"
    ws.append(["Client Name", "Client Code", "Occupation", "Mobile", "Mail Id", "Sub agent", "Family code"])
    ws.append(["RAJESH SHARMA", "CL001", "BUSINESS", "9876543210", "rajesh@example.com", "AGENT A", "FAM01"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


def build_sample_accounts_master_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Accounts Master"
    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)
    for idx, h in enumerate(["Company Name", "Agency", "Accounts"], start=1):
        cell = ws.cell(row=1, column=idx, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[cell.column_letter].width = 24
    ws.append(["HDFC ERGO", "SKC", "SM"])
    ws.append(["STAR HEALTH", "CL", "CL"])
    ws.append(["CARE HEALTH", "SONAL LADDHA", "SM"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


def _pick_worksheet(wb, sheet_name: str = ""):
    req = str(sheet_name or "").strip()
    if not req:
        return wb.active
    if req in wb.sheetnames:
        return wb[req]
    for nm in wb.sheetnames:
        if nm.strip().lower() == req.lower():
            return wb[nm]
    return wb.create_sheet(title=req)


def _append_rows_to_workbook(
    wb, rows: list, sheet_name: str = "", skip_duplicates: bool = True,
    custom_columns=None, col_types=None, policy_col: str = "Policy Number", expiry_col: str = "Expiry Date",
):
    target_cols = custom_columns if custom_columns else OUTPUT_COLUMNS
    types_map = col_types or {}
    ws = _pick_worksheet(wb, sheet_name)

    existing_headers = [str(ws.cell(row=1, column=c).value or "").strip() for c in range(1, max(ws.max_column, 1) + 1)]
    if not any(existing_headers):
        header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True)
        for col_idx, col_name in enumerate(target_cols, start=1):
            cell = ws.cell(row=1, column=col_idx, value=col_name)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")
            ws.column_dimensions[cell.column_letter].width = max(len(col_name) + 4, 22 if types_map.get(col_name) == "policy_id" else 16)
        col_map = {name.lower(): idx for idx, name in enumerate(target_cols, start=1)}
        active_headers = list(target_cols)
    else:
        col_map = {}
        for idx, h in enumerate(existing_headers, start=1):
            if h and h.lower() not in col_map:
                col_map[h.lower()] = idx
        active_headers = [h for h in existing_headers if h]

    last_row = 1
    max_col = max(col_map.values()) if col_map else 1
    for r in range(ws.max_row, 1, -1):
        if any(ws.cell(row=r, column=c).value not in (None, "") for c in range(1, max_col + 1)):
            last_row = r
            break

    existing_keys = set()
    pno_col = col_map.get(policy_col.lower()) or col_map.get("policy number")
    exp_col = col_map.get(expiry_col.lower()) or col_map.get("expiry date")
    if skip_duplicates and pno_col and last_row > 1:
        for r in range(2, last_row + 1):
            p_val = str(ws.cell(row=r, column=pno_col).value or "").strip().lstrip(",")
            e_val = _norm_date_key(ws.cell(row=r, column=exp_col).value) if exp_col else ""
            if p_val:
                existing_keys.add((p_val, e_val))

    added, skipped, write_row = 0, 0, last_row + 1
    for row_dict in rows:
        lower_row = {str(k).strip().lower(): v for k, v in row_dict.items()}
        pno_norm = str(lower_row.get(policy_col.lower(), lower_row.get("policy number", "")) or "").strip().lstrip(",")
        exp_norm = _norm_date_key(lower_row.get(expiry_col.lower(), lower_row.get("expiry date", "")))
        key = (pno_norm, exp_norm)

        if skip_duplicates and pno_norm and key in existing_keys:
            skipped += 1
            continue

        for h_name in active_headers:
            h_low = h_name.lower()
            if h_low in lower_row:
                c_idx = col_map[h_low]
                parsed_val, num_fmt = to_excel_value(h_name, lower_row[h_low], types_map.get(h_name, ""))
                cell = ws.cell(row=write_row, column=c_idx, value=parsed_val)
                if num_fmt == "@":
                    cell.data_type = "s"
                    cell.number_format = "@"
                elif num_fmt:
                    cell.number_format = num_fmt

        if pno_norm:
            existing_keys.add(key)
        write_row += 1
        added += 1

    return added, skipped, max(write_row - 2, 0), ws.title


def read_excel_headers_from_bytes(excel_bytes: bytes, sheet_name: str = ""):
    try:
        wb = openpyxl.load_workbook(io.BytesIO(excel_bytes), read_only=True, data_only=True)
        req = str(sheet_name or "").strip()
        ws = wb.active if not req else next((wb[nm] for nm in wb.sheetnames if nm.strip().lower() == req.lower()), None)
        tabs = list(wb.sheetnames)
        if ws is None:
            wb.close()
            return [], tabs, f"Excel me '{req}' naam ka tab nahi mila. Available tabs: {', '.join(tabs)}"
        first_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
        headers = [str(v).strip() for v in first_row if v is not None and str(v).strip() != ""]
        wb.close()
        return headers, tabs, ""
    except Exception as e:
        return [], [], f"Excel headers read error: {e}"


def append_rows_to_excel_bytes(
    excel_bytes: bytes, rows: list, sheet_name: str = "", skip_duplicates: bool = True,
    custom_columns=None, col_types=None, policy_col: str = "Policy Number", expiry_col: str = "Expiry Date", keep_vba: bool = False,
):
    try:
        wb = openpyxl.load_workbook(io.BytesIO(excel_bytes), keep_vba=keep_vba)
        added, skipped, total_entries, used_tab = _append_rows_to_workbook(
            wb, rows, sheet_name, skip_duplicates, custom_columns, col_types, policy_col, expiry_col
        )
        out_buf = io.BytesIO()
        wb.save(out_buf)
        out_buf.seek(0)
        return True, "", out_buf.getvalue(), added, skipped, total_entries, used_tab
    except Exception as e:
        return False, f"Excel update error: {e}", b"", 0, 0, 0, ""


def append_rows_to_local_excel(
    file_path: str, rows: list, sheet_name: str = "", skip_duplicates: bool = True,
    custom_columns=None, col_types=None, policy_col: str = "Policy Number", expiry_col: str = "Expiry Date",
):
    clean_path = str(file_path or "").strip().strip('"').strip("'")
    if not clean_path:
        return False, "Excel file ka path khali hai.", 0, 0, 0
    if not clean_path.lower().endswith((".xlsx", ".xlsm")):
        return False, "Sirf .xlsx ya .xlsm Excel file supported hai.", 0, 0, 0

    parent_dir = os.path.dirname(clean_path)
    if parent_dir and not os.path.exists(parent_dir):
        return False, f"Folder nahi mila: {parent_dir}", 0, 0, 0

    try:
        keep_vba = clean_path.lower().endswith(".xlsm")
        if os.path.exists(clean_path):
            wb = openpyxl.load_workbook(clean_path, keep_vba=keep_vba)
        else:
            wb = Workbook()
            if sheet_name:
                wb.active.title = sheet_name

        added, skipped, total_entries, _ = _append_rows_to_workbook(
            wb, rows, sheet_name, skip_duplicates, custom_columns, col_types, policy_col, expiry_col
        )
        wb.save(clean_path)
        return True, f"{added} nayi entries direct '{os.path.basename(clean_path)}' me save ho gayi!", added, skipped, total_entries
    except PermissionError:
        return False, "Excel file abhi MS Excel me khuli hui hai! Pehle Excel close karein aur dobara try karein.", 0, 0, 0
    except Exception as e:
        return False, f"Local Excel save error: {e}", 0, 0, 0
