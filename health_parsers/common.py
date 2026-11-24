import io
import os
import re
from datetime import date, datetime, timedelta, timezone
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

DATE_FIELDS = {"Inception Date", "Expiry Date", "Reminder Date", "Date of Entry", "DOB"}
DATE_FIELDS_LOWER = {c.lower() for c in DATE_FIELDS}

ALL_SYSTEM_FIELDS = OUTPUT_COLUMNS + ["Occupation", "Accounts", "PYP premium"]
SYSTEM_FIELD_LOOKUP = {f.lower(): f for f in ALL_SYSTEM_FIELDS}

MONTH_NAMES_BY_NUM = {
    1: ("JANUARY", "JAN"),
    2: ("FEBRUARY", "FEB"),
    3: ("MARCH", "MAR"),
    4: ("APRIL", "APR"),
    5: ("MAY", "MAY"),
    6: ("JUNE", "JUN"),
    7: ("JULY", "JUL"),
    8: ("AUGUST", "AUG"),
    9: ("SEPTEMBER", "SEP"),
    10: ("OCTOBER", "OCT"),
    11: ("NOVEMBER", "NOV"),
    12: ("DECEMBER", "DEC"),
}

_COMPANY_ALIASES = {
    "ICIC LOMBARD": "ICICI LOMBARD",
    "ICICI LOMBARD GENERAL INSURANCE": "ICICI LOMBARD",
    "MANIPAL SIGMA": "MANIPAL CIGNA",
    "MANIPALCIGNA": "MANIPAL CIGNA",
    "MAX BUPA": "NIVA BUPA",
    "RELIGARE HEALTH": "CARE HEALTH",
    "ORIENTAL INSURANCE": "ORIENTAL",
    "THE ORIENTAL": "ORIENTAL",
    "THE ORIENTAL INSURANCE": "ORIENTAL",
    "UNITED INDIA INSURANCE": "UNITED INDIA",
    "THE NEW INDIA ASSURANCE": "NEW INDIA",
    "NEW INDIA ASSURANCE": "NEW INDIA",
    "NATIONAL INSURANCE": "NATIONAL",
    "NATIONAL INSURANCE COMPANY": "NATIONAL",
    "STAR HEALTH AND ALLIED": "STAR HEALTH",
    "ADITYA BIRLA HEALTH": "ADITYA BIRLA",
    "IFFCO-TOKIO": "IFFCO TOKIO",
}

_AGENCY_SHORT_ALIASES = {
    "SURESH KUMAR CHINCHANI": "SKC",
    "SONAL LADDHA": "SL",
    "CHAYAN LADDHA": "CL",
    "SUMIT MAHESHWARI": "SM",
    "MOHIT MAHESHWARI": "MM",
}

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

_RN_COMPANY_PATTERNS = [
    ("HDFC ERGO", r"HDFC\s*ERGO"),
    ("STAR HEALTH", r"STAR\s*HEALTH"),
    ("CARE HEALTH", r"CARE\s*HEALTH|RELIGARE\s*HEALTH"),
    ("NIVA BUPA", r"NIVA\s*BUPA|MAX\s*BUPA"),
    ("MANIPAL CIGNA", r"MANIPAL\s*CIGNA|MANIPAL\s*SIGMA|MANIPALCIGNA"),
    ("TATA AIG", r"TATA\s*AIG"),
    ("TATA AIA", r"TATA\s*AIA"),
    ("ICICI LOMBARD", r"ICICI?\s*LOMBARD"),
    ("BAJAJ ALLIANZ", r"BAJAJ\s*ALLIANZ"),
    ("UNITED INDIA", r"UNITED\s*INDIA"),
    ("NEW INDIA", r"(?:THE\s+)?NEW\s*INDIA"),
    ("ORIENTAL", r"(?:THE\s+)?ORIENTAL(?:\s*INSURANCE)?"),
    ("NATIONAL", r"NATIONAL(?:\s*INSURANCE)?"),
    ("ADITYA BIRLA", r"ADITYA\s*BIRLA"),
    ("IFFCO TOKIO", r"IFFCO[\s\-]*TOKIO"),
    ("SBI GENERAL", r"SBI\s*GENERAL"),
    ("GO DIGIT", r"GO\s*DIGIT|DIGIT"),
    ("SHRIRAM", r"SHRIRAM"),
    ("ROYAL SUNDARAM", r"ROYAL\s*SUNDARAM"),
    ("CHOLA MS", r"CHOLA\s*MS|CHOLAMANDALAM"),
    ("FUTURE GENERALI", r"FUTURE\s*GENERALI"),
    ("RELIANCE", r"RELIANCE\s*GENERAL"),
    ("LIBERTY", r"LIBERTY"),
    ("MAGMA", r"MAGMA"),
    ("ZURICH KOTAK", r"ZURICH\s*KOTAK|KOTAK"),
]

_RN_SUBTYPE_PATTERNS = [
    ("PERSONAL ACCIDENT", r"PERSONAL\s*ACCIDENT"),
    ("TRAVEL INSURANCE", r"TRAVEL\s*INSURANCE"),
    ("SUPER TOP UP", r"SUPER\s*TOP[\s\-]*UP"),
    ("TOP UP", r"TOP[\s\-]*UP"),
    ("CRITICAL ILLNESS", r"CRITICAL\s*ILLNESS"),
    ("MEDICLAIM", r"MEDICLAIM"),
    ("WORKMEN COMPENSATION", r"WORKMEN\s*COMPENSATION|WC"),
    ("BURGLARY", r"BURGLARY"),
    ("MARINE", r"MARINE"),
    ("FIRE", r"FIRE"),
]

_RN_TAIL_RE = re.compile(
    r"(?<![\d.,])(?P<premium>\d{1,3}(?:,\d{2,3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s+"
    r"(?P<si>\d{1,3}(?:,\d{2,3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s+"
    r"(?P<inc>\d{2}[-/]\d{2}[-/]\d{2,4})\s+"
    r"(?P<exp>\d{2}[-/]\d{2}[-/]\d{2,4})\s*$"
)


def _norm_upper(val: str) -> str:
    return re.sub(r"\s+", " ", str(val or "").strip().upper()).strip(" .:-_")


def _norm_company(val: str) -> str:
    u = _norm_upper(val)
    return _COMPANY_ALIASES.get(u, u)


def _norm_agency_alias(val: str) -> str:
    u = _norm_upper(val)
    return _AGENCY_SHORT_ALIASES.get(u, u)


def _norm_policy_id(p: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(p or "").upper())


def _norm_name_compact(name: str) -> str:
    s = re.sub(r"(?i)^\s*((?:MRS|MISS|MR|MS|DR|SMT|SHRI|MASTER|MAST|M/S)(?:\.|\b)\s*)+", "", str(name or ""))
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def parse_renewal_list_pdf(pdf_bytes: bytes) -> list:
    """Extracts structured rows from Renewal List PDFs (Health / Motor / SME)."""
    text = ""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = "\n".join(p.extract_text() or "" for p in reader.pages)
    except Exception:
        text = ""

    if len(text.strip()) < 30:
        try:
            doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
            text = "\n".join(page.get_text("text") or "" for page in doc)
            doc.close()
        except Exception:
            pass

    records = []
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        low = line.lower()
        if "client name" in low and "expiry date" in low:
            continue

        m_tail = _RN_TAIL_RE.search(line)
        if not m_tail:
            continue

        premium = clean_amount(m_tail.group("premium"))
        sum_insured = clean_amount(m_tail.group("si"))
        exp_str = m_tail.group("exp")
        left = line[:m_tail.start()].strip()

        comp_name = ""
        comp_pos = len(left)
        for cname, cpat in _RN_COMPANY_PATTERNS:
            mc = re.search(rf"(?i)\b(?:{cpat})\b", left)
            if mc and mc.start() < comp_pos:
                comp_pos = mc.start()
                comp_name = cname

        sub_type = ""
        sub_pos = len(left)
        for sname, spat in _RN_SUBTYPE_PATTERNS:
            ms = re.search(rf"(?i)\b(?:{spat})\b", left)
            if ms and ms.start() < sub_pos:
                sub_pos = ms.start()
                sub_type = sname

        split_pos = min(comp_pos, sub_pos)
        head = left[:split_pos].strip()

        head_spaced = re.sub(r"([A-Za-z])([6-9]\d{9}\b)", r"\1 \2", head)
        head_spaced = re.sub(r"(\d{10}),(\S)", r"\1 ,\2", head_spaced)

        tokens = head_spaced.split()
        name_tokens = []
        id_tokens = []
        in_ids = False
        for tok in tokens:
            if not in_ids and (re.search(r"\d", tok) or tok.startswith(",")):
                in_ids = True
            if in_ids:
                id_tokens.append(tok)
            else:
                name_tokens.append(tok)

        client_name = " ".join(name_tokens).strip(" .,:-_").upper()
        id_str = " ".join(id_tokens).strip()

        policy_no = ""
        if "," in id_str:
            after_comma = id_str.split(",", 1)[1].strip()
            policy_no = _norm_policy_id(after_comma)
        else:
            m_mob_55 = re.match(r"^[6-9]\d{4}\s+\d{5}\s+(.+)$", id_str)
            m_mob_10 = re.match(r"^[6-9]\d{9}\s+(.+)$", id_str)
            if m_mob_55 and re.search(r"\d", m_mob_55.group(1)):
                policy_no = _norm_policy_id(m_mob_55.group(1))
            elif m_mob_10 and re.search(r"\d", m_mob_10.group(1)):
                policy_no = _norm_policy_id(m_mob_10.group(1))
            elif m_mob_10 and not re.search(r"\d", m_mob_10.group(1)):
                policy_no = ""
            elif re.search(r"\d", id_str):
                policy_no = _norm_policy_id(id_str)

        records.append({
            "client_name": client_name,
            "client_compact": _norm_name_compact(client_name),
            "policy_no_norm": policy_no,
            "sub_type": sub_type,
            "company": comp_name,
            "premium": premium,
            "sum_insured": sum_insured,
            "exp_dt": parse_any_date(exp_str),
        })

    return records


def get_renewal_lookup_months(row_dict: dict) -> list:
    """
    Returns ordered list of (year_int, month_int) tuples to check in Renewal List folder.
    Uses Inception Date Month & Year as primary, plus boundary month fallback for 30th/31st-to-1st renewals.
    """
    inc_dt = parse_any_date(row_dict.get("Inception Date", ""))
    exp_dt = parse_any_date(row_dict.get("Expiry Date", ""))
    targets = []

    if inc_dt:
        targets.append((inc_dt.year, inc_dt.month))
        if inc_dt.day <= 5:
            prev_dt = inc_dt - timedelta(days=inc_dt.day)
            targets.append((prev_dt.year, prev_dt.month))
        elif inc_dt.day >= 26:
            nxt_dt = inc_dt + timedelta(days=7)
            targets.append((nxt_dt.year, nxt_dt.month))
    elif exp_dt:
        targets.append((exp_dt.year - 1, exp_dt.month))

    seen = set()
    ordered = []
    for ym in targets:
        if ym not in seen:
            seen.add(ym)
            ordered.append(ym)
    return ordered


def match_renewal_record(row_dict: dict, records: list):
    """Matches a new policy entry against parsed Renewal List PDF rows."""
    if not records:
        return None

    pyp_norm = _norm_policy_id(row_dict.get("PYP Number", ""))
    pno_norm = _norm_policy_id(row_dict.get("Policy Number", ""))
    cname_compact = _norm_name_compact(row_dict.get("Client Name", ""))
    comp_norm = _norm_company(row_dict.get("Company Name", ""))
    sub_norm = _norm_upper(row_dict.get("Sub Type", ""))
    inc_dt = parse_any_date(row_dict.get("Inception Date", ""))

    # Priority 1: PYP Number exact / contained match
    if len(pyp_norm) >= 6:
        for r in records:
            rp = r["policy_no_norm"]
            if rp and (rp == pyp_norm or (len(rp) >= 8 and (rp in pyp_norm or pyp_norm in rp))):
                return r

    # Priority 2: Same Policy Number or same base policy prefix (HDFC ERGO / Niva Bupa renewal suffix change)
    if len(pno_norm) >= 6:
        for r in records:
            rp = r["policy_no_norm"]
            if rp and rp == pno_norm:
                return r
        for r in records:
            rp = r["policy_no_norm"]
            if rp and len(rp) >= 12 and len(pno_norm) >= 12:
                if rp[:14] == pno_norm[:14]:
                    return r
                if rp[:8] == pno_norm[:8] and cname_compact and r["client_compact"] == cname_compact:
                    return r

    # Priority 3: Client Name + Company + Sub Type + Date proximity match
    if cname_compact:
        name_matches = []
        for r in records:
            rc = r["client_compact"]
            if not rc:
                continue
            if rc == cname_compact or (len(rc) >= 8 and len(cname_compact) >= 8 and (rc in cname_compact or cname_compact in rc)):
                score = 0
                if comp_norm and _norm_company(r["company"]) == comp_norm:
                    score += 10
                if sub_norm and _norm_upper(r["sub_type"]) == sub_norm:
                    score += 5
                if inc_dt and r["exp_dt"]:
                    diff_days = abs((inc_dt - r["exp_dt"]).days)
                    if diff_days <= 15:
                        score += 8
                    elif diff_days <= 45:
                        score += 3
                name_matches.append((score, r))
        if name_matches:
            name_matches.sort(key=lambda x: x[0], reverse=True)
            best_score, best_rec = name_matches[0]
            if best_score >= 5 or len(name_matches) == 1:
                return best_rec

    return None


def lookup_accounts_master(company_name: str, agency_name: str, accounts_df: pd.DataFrame) -> str:
    """
    Dynamically looks up 'Accounts' value from user's linked/uploaded Accounts Master sheet
    using (Company Name + Agency). Works for all users across Health, Motor, and SME.
    """
    if accounts_df is None or accounts_df.empty or not company_name or not agency_name:
        return ""

    cols = {str(c).strip().lower(): c for c in accounts_df.columns}
    comp_col = cols.get("company name") or cols.get("company") or cols.get("insurer") or cols.get("insurance company")
    ag_col = cols.get("agency") or cols.get("agency name") or cols.get("intermediary") or cols.get("agent") or cols.get("broker")
    acc_col = cols.get("accounts") or cols.get("account") or cols.get("account name")

    if not comp_col or not ag_col or not acc_col:
        return ""

    target_comp_raw = _norm_upper(company_name)
    target_comp_norm = _norm_company(company_name)
    target_ag_raw = _norm_upper(agency_name)
    target_ag_alias = _norm_agency_alias(agency_name)

    exact_map = {}
    comp_norm_map = {}
    full_norm_map = {}

    for _, row in accounts_df.iterrows():
        c_val = row[comp_col]
        a_val = row[ag_col]
        acc_val = row[acc_col]
        if pd.isna(c_val) or pd.isna(a_val) or pd.isna(acc_val):
            continue
        acc_str = str(acc_val).strip()
        if not acc_str or acc_str.lower() == "nan":
            continue

        c_raw = _norm_upper(c_val)
        c_norm = _norm_company(c_val)
        a_raw = _norm_upper(a_val)
        a_alias = _norm_agency_alias(a_val)
        if not c_raw or not a_raw:
            continue

        exact_map.setdefault((c_raw, a_raw), acc_str)
        comp_norm_map.setdefault((c_norm, a_raw), acc_str)
        full_norm_map.setdefault((c_norm, a_alias), acc_str)

    if (target_comp_raw, target_ag_raw) in exact_map:
        return exact_map[(target_comp_raw, target_ag_raw)]
    if (target_comp_norm, target_ag_raw) in comp_norm_map:
        return comp_norm_map[(target_comp_norm, target_ag_raw)]
    if (target_comp_norm, target_ag_alias) in full_norm_map:
        return full_norm_map[(target_comp_norm, target_ag_alias)]
    return ""


def build_sample_accounts_master_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Accounts Master"
    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)
    headers = ["Company Name", "Agency", "Accounts"]
    for idx, h in enumerate(headers, start=1):
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


def parse_custom_columns(spec_str: str):
    raw = str(spec_str or "").strip()
    if not raw:
        return [(c, c) for c in OUTPUT_COLUMNS]

    if "\n" in raw or "\r" in raw or "|" in raw:
        parts = re.split(r"[\r\n|]+", raw)
    else:
        parts = raw.split(",")

    mapping = []
    seen_headers = set()
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
    if "\n" in raw or "\r" in raw or "|" in raw:
        parts = re.split(r"[\r\n|]+", raw)
    else:
        parts = raw.split(",")

    cleaned = []
    seen = set()
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
    if "\n" in raw or "\r" in raw or "|" in raw:
        parts = re.split(r"[\r\n|]+", raw)
    else:
        parts = raw.split(",")
    lines = [p.strip() for p in parts if p.strip()]
    return "\n".join(lines) if lines else "\n".join(OUTPUT_COLUMNS)


def get_custom_schema_info(spec_str: str) -> dict:
    mapping = parse_custom_columns(spec_str)
    headers = [dst for _, dst in mapping]
    col_types = {}
    policy_col = "Policy Number"
    expiry_col = "Expiry Date"

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
    text_lower = pdf_text.lower()
    scores = {}
    for company, keywords in COMPANY_KEYWORDS.items():
        count = sum(len(re.findall(re.escape(kw), text_lower)) for kw in keywords)
        if count > 0:
            scores[company] = count
    return dict(sorted(scores.items(), key=lambda x: x[1], reverse=True))


def parse_any_date(date_str):
    if not date_str:
        return None
    if isinstance(date_str, datetime):
        return date_str
    if isinstance(date_str, date):
        return datetime(date_str.year, date_str.month, date_str.day)
    clean = re.sub(r"\s+", " ", str(date_str).strip()).replace("/", "-").replace(",", "")
    formats = [
        "%d-%m-%Y", "%d-%m-%y", "%Y-%m-%d", "%d-%b-%Y", "%d-%b-%y",
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


def _norm_date_key(val) -> str:
    if val is None or val == "":
        return ""
    if isinstance(val, datetime):
        return val.strftime("%d-%m-%Y")
    if isinstance(val, date):
        return val.strftime("%d-%m-%Y")
    s = str(val).strip()
    dt = parse_any_date(s)
    return dt.strftime("%d-%m-%Y") if dt else s


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
        r"(?i)Name\s+of\s+(?:the\s+)?[\r\n\s]*(?:Agent|Intermediary|Broker|Advisor|POSP)(?:[/\s]*(?:Agent|Intermediary|Broker|Advisor|POSP|CPSC|User|IMD|Direct))*[\s:\-\r\n]+([^\r\n]{3,70})",
        r"(?i)Intermediary\s*Details\s*[\r\n]+\s*Name\s*[\r\n]+\s*Code\s*[\r\n]+\s*Contact\s*(?:Details|Number|No\.?)\s*[\r\n]+\s*([^\r\n]{3,60})",
        r"(?i)Intermediary\s*Details\s*[\r\n]+\s*Name\s*[\r\n]+\s*Code\s*[\r\n]+\s*([A-Za-z][A-Za-z\s.&/-]{2,55})",
        r"(?i)Intermediary\s*Name\s*[\r\n]+\s*Intermediary\s*Code\s*[\r\n]+\s*Intermediary\s*Contact\s*(?:Number|No\.?)\s*[\r\n]+\s*([^\r\n]{3,60})",
        r"(?i)Intermediary\s*Name\s*[\r\n]+\s*Intermediary\s*Code\s*[\r\n]+\s*([A-Za-z][A-Za-z\s.&/-]{2,55})",
        r"(?i)Agent/Intermediary Contact No\.[\s\r\n]+([A-Za-z\s]+?)\s+[A-Z0-9]{5,20}\s+\d{8,15}",
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
    empty = {
        "client_code": "",
        "occupation": "",
        "mobile": "",
        "mail_id": "",
        "sub_agent": "",
        "family_code": "",
    }
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
        "occupation": get_val(["occupation", "profession"]),
        "mobile": get_val(["mobile", "mobile no", "phone"]),
        "mail_id": get_val(["mail id", "mail", "email", "email id"]),
        "sub_agent": get_val(["sub agent", "subagent"]),
        "family_code": get_val(["family code"]),
    }


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
        if dt:
            return dt.date(), "dd-mm-yyyy"
        return val, None

    if t == "number":
        cleaned = val.replace(",", "").replace("%", "").strip()
        if re.fullmatch(r"-?\d+", cleaned):
            return int(cleaned), "0"
        if re.fullmatch(r"-?\d+\.\d+", cleaned):
            return float(cleaned), "0.##"
        return val, None

    if t == "mobile":
        cleaned = re.sub(r"[\s\-]", "", val)
        if re.fullmatch(r"[1-9]\d{6,14}", cleaned):
            return int(cleaned), "0"
        return val, "@"

    if t == "policy_id":
        if re.fullmatch(r"[1-9]\d{0,14}", val):
            return int(val), "0"
        if re.fullmatch(r"\d{16,}", val):
            return f",{val}", "@"
        return val, "@"

    if t == "code_id":
        if re.fullmatch(r"[1-9]\d{0,14}", val):
            return int(val), "0"
        return val, "@"

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
    headers = ["Client Name", "Client Code", "Occupation", "Mobile", "Mail Id", "Sub agent", "Family code"]
    ws.append(headers)
    ws.append(["RAJESH SHARMA", "CL001", "BUSINESS", "9876543210", "rajesh@example.com", "AGENT A", "FAM01"])
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
    wb,
    rows: list,
    sheet_name: str = "",
    skip_duplicates: bool = True,
    custom_columns=None,
    col_types=None,
    policy_col: str = "Policy Number",
    expiry_col: str = "Expiry Date",
):
    target_cols = custom_columns if custom_columns else OUTPUT_COLUMNS
    types_map = col_types or {}
    ws = _pick_worksheet(wb, sheet_name)

    existing_headers = [
        str(ws.cell(row=1, column=c).value or "").strip()
        for c in range(1, max(ws.max_column, 1) + 1)
    ]
    if not any(existing_headers):
        header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True)
        for col_idx, col_name in enumerate(target_cols, start=1):
            cell = ws.cell(row=1, column=col_idx, value=col_name)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")
            col_letter = cell.column_letter
            ws.column_dimensions[col_letter].width = max(
                len(col_name) + 4,
                22 if types_map.get(col_name) == "policy_id" else 16
            )
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

    added = 0
    skipped = 0
    write_row = last_row + 1

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

    total_entries = max(write_row - 2, 0)
    return added, skipped, total_entries, ws.title


def read_excel_headers_from_bytes(excel_bytes: bytes, sheet_name: str = ""):
    try:
        wb = openpyxl.load_workbook(io.BytesIO(excel_bytes), read_only=True, data_only=True)
        req = str(sheet_name or "").strip()
        ws = None
        if not req:
            ws = wb.active
        else:
            for nm in wb.sheetnames:
                if nm.strip().lower() == req.lower():
                    ws = wb[nm]
                    break
        if ws is None:
            tabs = list(wb.sheetnames)
            wb.close()
            return [], tabs, f"Excel me '{req}' naam ka tab nahi mila. Available tabs: {', '.join(tabs)}"
        first_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
        headers = [str(v).strip() for v in first_row if v is not None and str(v).strip() != ""]
        tabs = list(wb.sheetnames)
        wb.close()
        return headers, tabs, ""
    except Exception as e:
        return [], [], f"Excel headers read error: {e}"


def append_rows_to_excel_bytes(
    excel_bytes: bytes,
    rows: list,
    sheet_name: str = "",
    skip_duplicates: bool = True,
    custom_columns=None,
    col_types=None,
    policy_col: str = "Policy Number",
    expiry_col: str = "Expiry Date",
    keep_vba: bool = False,
):
    try:
        wb = openpyxl.load_workbook(io.BytesIO(excel_bytes), keep_vba=keep_vba)
        added, skipped, total_entries, used_tab = _append_rows_to_workbook(
            wb=wb,
            rows=rows,
            sheet_name=sheet_name,
            skip_duplicates=skip_duplicates,
            custom_columns=custom_columns,
            col_types=col_types,
            policy_col=policy_col,
            expiry_col=expiry_col,
        )
        out_buf = io.BytesIO()
        wb.save(out_buf)
        out_buf.seek(0)
        return True, "", out_buf.getvalue(), added, skipped, total_entries, used_tab
    except Exception as e:
        return False, f"Excel update error: {e}", b"", 0, 0, 0, ""


def append_rows_to_local_excel(
    file_path: str,
    rows: list,
    sheet_name: str = "",
    skip_duplicates: bool = True,
    custom_columns=None,
    col_types=None,
    policy_col: str = "Policy Number",
    expiry_col: str = "Expiry Date",
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
            wb=wb,
            rows=rows,
            sheet_name=sheet_name,
            skip_duplicates=skip_duplicates,
            custom_columns=custom_columns,
            col_types=col_types,
            policy_col=policy_col,
            expiry_col=expiry_col,
        )
        wb.save(clean_path)
        return True, f"{added} nayi entries direct '{os.path.basename(clean_path)}' me save ho gayi!", added, skipped, total_entries

    except PermissionError:
        return False, "Excel file abhi MS Excel me khuli hui hai! Pehle Excel close karein aur dobara try karein.", 0, 0, 0
    except Exception as e:
        return False, f"Local Excel save error: {e}", 0, 0, 0
