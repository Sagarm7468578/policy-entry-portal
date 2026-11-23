import io
import os
import re
from datetime import datetime, timedelta, timezone
import pandas as pd
import pymupdf
from pypdf import PdfReader
import openpyxl
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

IST = timezone(timedelta(hours=5, minutes=30))

OUTPUT_COLUMNS = [
    "Client Name", "Client Code", "Mobile", "Mail Id", "Policy Number",
    "Insurance Type", "Sub Type", "Company Name", "Agency", "Sub agent",
    "Plan Name", "Premium", "Sum Insured", "Inception Date", "Expiry Date",
    "Reminder Date", "Premium Mode", "Policy Status", "Remark",
    "PYP Number", "Share", "Share %", "Family code", "Date of Entry",
    "DOB", "OUR RENEWAL"
]

COMPANY_KEYWORDS = {
    "MANIPAL CIGNA": ["manipalcigna", "manipal cigna"],
    "CARE HEALTH": ["care health", "religare health"],
    "NIVA BUPA": ["niva bupa", "max bupa"],
    "ORIENTAL": ["the oriental insurance", "oriental insurance"],
    "UNITED INDIA": ["united india insurance", "united india"],
    "ICICI LOMBARD": ["icici lombard"],
    "NEW INDIA": ["the new india assurance", "new india assurance", "new india"],
    "IFFCO TOKIO": ["iffco-tokio", "iffco tokio"],
    "BAJAJ ALLIANZ": ["bajaj allianz"],
    "TATA AIG": ["tata aig"],
    "HDFC ERGO": ["hdfc ergo"],
    "NATIONAL": ["national insurance company", "national insurance"],
    "ADITYA BIRLA": ["aditya birla health", "aditya birla"],
    "STAR HEALTH": ["star health and allied", "star health"],
}


def default_extracted_data() -> dict:
    return {
        "client_name": "",
        "policy_number": "",
        "sub_type": "MEDICLAIM",
        "plan_name": "N/A",
        "premium": "",
        "sum_insured": "",
        "start_dt": None,
        "end_dt": None,
        "pyp_number": "",
        "agency": "",
        "premium_mode": "",
        "dob": "",
    }


def extract_pdf_text(pdf_bytes: bytes, max_pages: int = 15) -> str:
    """Primary: PyMuPDF (HDFC ERGO jaise strict font PDFs bhi bina crash padhta hai). Backup: pypdf."""
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        parts = []
        for page in doc[:max_pages]:
            parts.append(page.get_text("text") or "")
        doc.close()
        text = "\n".join(parts)
        if text.strip():
            return text
    except Exception:
        pass

    reader = PdfReader(io.BytesIO(pdf_bytes))
    parts = []
    for page in reader.pages[:max_pages]:
        parts.append(page.extract_text() or "")
    return "\n".join(parts)


def get_company_scores(pdf_text: str) -> dict:
    """Renamer Bot Logic: Har company ka naam kitni baar aaya uska score nikalta hai."""
    text_lower = pdf_text.lower()
    scores = {}
    for company, keywords in COMPANY_KEYWORDS.items():
        count = sum(len(re.findall(re.escape(kw), text_lower)) for kw in keywords)
        if count > 0:
            scores[company] = count
    return dict(sorted(scores.items(), key=lambda x: x[1], reverse=True))


def parse_any_date(date_str: str):
    if not date_str:
        return None
    clean = re.sub(r"\s+", " ", date_str.strip()).replace("/", "-").replace(",", "")
    formats = [
        "%d-%m-%Y", "%d-%m-%y", "%d-%b-%Y", "%d-%b-%y",
        "%b %d %Y", "%B %d %Y", "%d %b %Y", "%d %B %Y"
    ]
    for fmt in formats:
        try:
            return datetime.strptime(clean, fmt)
        except ValueError:
            continue
    return None


def fmt_date(dt) -> str:
    return dt.strftime("%d-%m-%Y") if dt else ""


def clean_amount(val: str) -> str:
    if not val:
        return ""
    val = re.sub(r"\.\d+$", "", val.strip())
    return re.sub(r"[,\s]", "", val)


def clean_person_name(name: str) -> str:
    if not name:
        return ""
    name = re.sub(r"[\r\n]+", " ", name)
    name = re.sub(r"\s+\d{4,}.*$", "", name)
    name = re.sub(r"(?i)^\s*((?:MRS|MISS|MR|MS|DR|SMT|SHRI|MASTER|MAST|M/S)(?:\.|\b)\s*)+", "", name)
    name = re.sub(r"\s+", " ", name).strip(" .,:-_")
    return name.upper()


def extract_generic_agency(pdf_text: str) -> str:
    patterns = [
        # New India / PSU multi-line format
        r"(?i)Name\s+of\s+(?:the\s+)?[\r\n\s]*(?:Agent|Intermediary|Broker|Advisor|POSP)(?:[/\s]*(?:Agent|Intermediary|Broker|Advisor|POSP|CPSC|User|IMD|Direct))*[\s:\-\r\n]+([^\r\n]{3,70})",
        # Care Health stacked format
        r"(?i)Intermediary\s*Details\s*[\r\n]+\s*Name\s*[\r\n]+\s*Code\s*[\r\n]+\s*Contact\s*(?:Details|Number|No\.?)\s*[\r\n]+\s*([^\r\n]{3,60})",
        r"(?i)Intermediary\s*Details\s*[\r\n]+\s*Name\s*[\r\n]+\s*Code\s*[\r\n]+\s*([A-Za-z][A-Za-z\s.&/-]{2,55})",
        # HDFC ERGO stacked format
        r"(?i)Intermediary\s*Name\s*[\r\n]+\s*Intermediary\s*Code\s*[\r\n]+\s*Intermediary\s*Contact\s*(?:Number|No\.?)\s*[\r\n]+\s*([^\r\n]{3,60})",
        r"(?i)Intermediary\s*Name\s*[\r\n]+\s*Intermediary\s*Code\s*[\r\n]+\s*([A-Za-z][A-Za-z\s.&/-]{2,55})",
        # TATA AIG format
        r"(?i)Agent/Intermediary Contact No\.[\s\r\n]+([A-Za-z\s]+?)\s+[A-Z0-9]{5,20}\s+\d{8,15}",
        # General inline formats
        r"(?i)(?:Intermediary|Agent|Broker|IMD|Advisor|POSP|Channel\s*Partner|Partner)(?:\s*/\s*(?:Intermediary|Agent|Broker|Advisor|POSP))?\s*Name\s*[:\-]?\s*([^\r\n]{3,65})",
        r"(?i)(?:Intermediary|Agent|Broker|Advisor)\s*Name\s*[:\-]?\s*[\r\n]+\s*([A-Za-z][A-Za-z\s.&/-]{2,55})",
    ]
    bad_starts = (
        "intermediary", "agent", "broker", "advisor", "code", "contact",
        "mobile", "email", "phone", "license", "details", "number", "no", "id", "address", "user", "cpsc"
    )
    for pat in patterns:
        for m in re.finditer(pat, pdf_text):
            raw = re.sub(r"\([^)]*\)", "", m.group(1))
            val = re.split(
                r"(?i)\b(?:Intermediary|Agent|Broker|Code|Contact|Mobile|Email|Phone|License|ID|No\.|Number|Address|Branch|Location)\b",
                raw,
            )[0]
            val = re.sub(r"(?i)^\s*((?:MRS|MISS|MR|MS|DR|SMT|SHRI)(?:\.|\b)\s*)+", "", val)
            val = re.sub(r"[^A-Za-z0-9\s.&/-]", "", val)
            val = re.sub(r"\s+", " ", val).strip(" .:-_/")
            if len(val) >= 3 and not val.isdigit():
                first_word = val.split()[0].lower()
                if first_word not in bad_starts:
                    return val.upper()
    return ""


def extract_premium_mode(pdf_text: str) -> str:
    """Payment Details / Instrument Details / Mode of Payment se payment mode nikalta hai."""
    for m_pay in re.finditer(
        r"(?i)(?:Mode\s*of\s*Payment|(?<!Premium\s)Payment\s*Mode|Payment\s*Details|Instrument\s*Details|Instrument\s*(?:No\.?|Number)|Payment\s*Method)([\s\S]{0,250})",
        pdf_text,
    ):
        block = m_pay.group(0)
        block = re.split(
            r"(?i)(?:Eligibility\s*of\s*Premium|Section\s*80D|Income\s*Tax\s*Act|Terms\s*&\s*Conditions)",
            block,
        )[0]
        clean_block = re.sub(
            r"(?i)(?:Pin\s*Code|Pincode|HSN\s*Code|Mumbai|Indore|Delhi|Chennai|Hyderabad)\s*[:\-]?\s*\d{6}",
            "",
            block,
        )

        if re.search(
            r"(?i)\b(?:IPG|EPG|PG|Online|UPI|NEFT|RTGS|IMPS|Net\s*Banking|NetBanking|Internet\s*Banking|Credit\s*Card|Debit\s*Card|Card|E-?Pay(?:ment)?|Digital|BillDesk|Razorpay|PayU)\b",
            clean_block,
        ):
            return "ONLINE"

        if re.search(r"(?i)\b(?:Cheque|Chq\.?|DD|Demand\s*Draft)\b", clean_block):
            return "CHEQUE"

        if re.search(r"(?i)Instrument\s*(?:Details|No\.?|Number)", clean_block):
            m_inst = re.search(
                r"(?i)Instrument\s*(?:Details|No\.?|Number)[\s\S]{0,200}?(?<![A-Za-z0-9/\-])(\d{6})(?![A-Za-z0-9/\-])",
                clean_block,
            )
            if m_inst:
                return "CHEQUE"

        if re.search(r"(?i)\b(?:ECS|NACH|Auto\s*Debit|Standing\s*Instruction)\b", clean_block):
            return "AUTO DEBIT"

        cash_check_block = re.sub(r"(?i)(?:other\s+than\s+cash|paid\s+in\s+cash|cashless)", "", clean_block)
        if re.search(r"(?i)\bCash\b", cash_check_block):
            return "CASH"

    return ""


def extract_oldest_dob(pdf_text: str, start_dt=None) -> str:
    cleaned = re.sub(r"(\b\d{2}[/\-][A-Za-z0-9]{2,3}[/\-](?:19|20))[\r\n\s]+(\d{2})\b", r"\1\2", pdf_text)
    matches = re.findall(r"\b\d{2}[/\-][A-Za-z0-9]{2,3}[/\-](?:19|20)\d{2}\b", cleaned)
    today = datetime.now(IST).replace(tzinfo=None)
    cutoff = start_dt - timedelta(days=30) if start_dt else today - timedelta(days=365)

    oldest = None
    for d_str in matches:
        dt = parse_any_date(d_str)
        if dt and datetime(1920, 1, 1) <= dt < cutoff:
            if oldest is None or dt < oldest:
                oldest = dt
    return fmt_date(oldest)


def lookup_client_master(client_name: str, master_df: pd.DataFrame) -> dict:
    empty = {"client_code": "", "mobile": "", "mail_id": "", "sub_agent": "", "family_code": ""}
    if master_df is None or master_df.empty or not client_name:
        return empty

    cols = {str(c).strip().lower(): c for c in master_df.columns}
    name_col = cols.get("client name") or cols.get("name")
    if not name_col:
        return empty

    target = client_name.strip().upper()
    series = master_df[name_col].astype(str).str.strip().str.upper()

    matched = master_df[series == target]
    if matched.empty:
        matched = master_df[series.str.contains(re.escape(target), na=False)]
    if matched.empty:
        return empty

    row = matched.iloc[0]

    def get_val(keys):
        for k in keys:
            if k in cols:
                v = row[cols[k]]
                if pd.notna(v):
                    s = str(v).strip()
                    if s.lower() == "nan":
                        return ""
                    if re.fullmatch(r"\d+\.0+", s):
                        s = s.split(".")[0]
                    return s
        return ""

    return {
        "client_code": get_val(["client code"]),
        "mobile": get_val(["mobile", "mobile no", "phone"]),
        "mail_id": get_val(["mail id", "mail", "email", "email id"]),
        "sub_agent": get_val(["sub agent", "subagent"]),
        "family_code": get_val(["family code"]),
    }


def to_excel_value(col_name: str, raw_val):
    val = str(raw_val if raw_val is not None else "").strip()
    if not val:
        return "", None

    if col_name in {"Premium", "Sum Insured", "Share", "Share %"}:
        cleaned = val.replace(",", "").replace("%", "").strip()
        if re.fullmatch(r"-?\d+", cleaned):
            return int(cleaned), "0"
        if re.fullmatch(r"-?\d+\.\d+", cleaned):
            return float(cleaned), "0.##"
        return val, None

    if col_name == "Mobile":
        cleaned = re.sub(r"[\s\-]", "", val)
        if re.fullmatch(r"[1-9]\d{6,14}", cleaned):
            return int(cleaned), "0"
        return val, "@"

    if col_name in {"Policy Number", "PYP Number"}:
        if re.fullmatch(r"[1-9]\d{0,14}", val):
            return int(val), "0"
        if re.fullmatch(r"\d{16,}", val):
            return f",{val}", "@"
        return val, "@"

    if col_name in {"Client Code", "Family code"}:
        if re.fullmatch(r"[1-9]\d{0,14}", val):
            return int(val), "0"
        return val, "@"

    return val, None


def build_excel_bytes(rows: list) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Policy Entries"

    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)

    for col_idx, col_name in enumerate(OUTPUT_COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for r_idx, row_dict in enumerate(rows, start=2):
        for col_idx, col_name in enumerate(OUTPUT_COLUMNS, start=1):
            parsed_val, num_fmt = to_excel_value(col_name, row_dict.get(col_name, ""))
            cell = ws.cell(row=r_idx, column=col_idx, value=parsed_val)
            if num_fmt == "@":
                cell.data_type = "s"
                cell.number_format = "@"
            elif num_fmt:
                cell.number_format = num_fmt

    for col_idx, col_name in enumerate(OUTPUT_COLUMNS, start=1):
        col_letter = ws.cell(row=1, column=col_idx).column_letter
        ws.column_dimensions[col_letter].width = max(
            len(col_name) + 4,
            22 if col_name in {"Policy Number", "PYP Number"} else 16
        )

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


def build_sample_master_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Client Master"
    headers = ["Client Name", "Client Code", "Mobile", "Mail Id", "Sub agent", "Family code"]
    ws.append(headers)
    ws.append(["RAJESH SHARMA", "CL001", "9876543210", "rajesh@example.com", "AGENT A", "FAM01"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


def append_rows_to_local_excel(file_path: str, rows: list, sheet_name: str = "", skip_duplicates: bool = True):
    """
    Fixed location wali local Excel (.xlsx) me purani entries ke neeche nayi entries directly save karta hai.
    Returns (success, message, added_count, skipped_count, total_rows)
    """
    clean_path = str(file_path or "").strip().strip('"').strip("'")
    if not clean_path:
        return False, "Excel file ka path khali hai.", 0, 0, 0
    if not clean_path.lower().endswith(".xlsx"):
        return False, "Sirf .xlsx Excel file supported hai (path ke end me .xlsx hona chahiye).", 0, 0, 0

    parent_dir = os.path.dirname(clean_path)
    if parent_dir and not os.path.exists(parent_dir):
        return False, f"Folder nahi mila: {parent_dir}", 0, 0, 0

    try:
        if os.path.exists(clean_path):
            wb = openpyxl.load_workbook(clean_path)
            if sheet_name and sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
            elif sheet_name:
                ws = wb.create_sheet(title=sheet_name)
            else:
                ws = wb.active
        else:
            wb = Workbook()
            ws = wb.active
            ws.title = sheet_name or "Policy Entries"

        existing_headers = [
            str(ws.cell(row=1, column=c).value or "").strip()
            for c in range(1, max(ws.max_column, 1) + 1)
        ]
        if not any(existing_headers):
            header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
            header_font = Font(color="FFFFFF", bold=True)
            for col_idx, col_name in enumerate(OUTPUT_COLUMNS, start=1):
                cell = ws.cell(row=1, column=col_idx, value=col_name)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center", vertical="center")
                col_letter = cell.column_letter
                ws.column_dimensions[col_letter].width = max(
                    len(col_name) + 4,
                    22 if col_name in {"Policy Number", "PYP Number"} else 16
                )
            col_map = {name.lower(): idx for idx, name in enumerate(OUTPUT_COLUMNS, start=1)}
        else:
            col_map = {}
            for idx, h in enumerate(existing_headers, start=1):
                if h:
                    col_map[h.lower()] = idx
            next_col = len(existing_headers) + 1
            for col_name in OUTPUT_COLUMNS:
                if col_name.lower() not in col_map:
                    cell = ws.cell(row=1, column=next_col, value=col_name)
                    cell.font = Font(bold=True)
                    col_map[col_name.lower()] = next_col
                    next_col += 1

        last_row = 1
        max_col = max(col_map.values())
        for r in range(ws.max_row, 1, -1):
            if any(ws.cell(row=r, column=c).value not in (None, "") for c in range(1, max_col + 1)):
                last_row = r
                break

        existing_keys = set()
        pno_col = col_map.get("policy number")
        exp_col = col_map.get("expiry date")
        if skip_duplicates and pno_col and last_row > 1:
            for r in range(2, last_row + 1):
                p_val = str(ws.cell(row=r, column=pno_col).value or "").strip().lstrip(",")
                e_val = str(ws.cell(row=r, column=exp_col).value or "").strip() if exp_col else ""
                if p_val:
                    existing_keys.add((p_val, e_val))

        added = 0
        skipped = 0
        write_row = last_row + 1

        for row_dict in rows:
            pno_norm = str(row_dict.get("Policy Number", "") or "").strip().lstrip(",")
            exp_norm = str(row_dict.get("Expiry Date", "") or "").strip()
            key = (pno_norm, exp_norm)

            if skip_duplicates and pno_norm and key in existing_keys:
                skipped += 1
                continue

            for col_name in OUTPUT_COLUMNS:
                c_idx = col_map[col_name.lower()]
                parsed_val, num_fmt = to_excel_value(col_name, row_dict.get(col_name, ""))
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

        wb.save(clean_path)
        total_entries = max(write_row - 2, 0)
        return True, f"{added} nayi entries direct '{os.path.basename(clean_path)}' me save ho gayi!", added, skipped, total_entries

    except PermissionError:
        return False, "Excel file abhi MS Excel me khuli hui hai! Pehle Excel close karein aur dobara try karein.", 0, 0, 0
    except Exception as e:
        return False, f"Local Excel save error: {e}", 0, 0, 0
