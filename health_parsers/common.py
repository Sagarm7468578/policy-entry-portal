import io
import re
from datetime import date, datetime, timedelta, timezone
import pymupdf
from pypdf import PdfReader

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


def shorten_agency_name(name: str) -> str:
    """Shortens long corporate broker names (e.g. 'GIRNAR INSURANCE BROKERS PRIVATE LIMITED' -> 'GIRNAR',
    'BIMAKAVACH INSURANCE BROKING PRIVATE LIMITED' -> 'BIMAKAVACH') while leaving human agent names untouched."""
    s = re.sub(r"\s+", " ", str(name or "")).strip(" .,:-_/")
    if not s:
        return ""
    s_up = s.upper()

    known_brokers = [
        (r"\bGIRNAR\b", "GIRNAR"),
        (r"\bBIMA\s*KAVACH\b", "BIMAKAVACH"),
        (r"\bPOLICY\s*BAZAAR\b", "POLICYBAZAAR"),
        (r"\bTURTLE\s*MINT\b", "TURTLEMINT"),
        (r"\bINSURANCE\s*DEKHO\b", "INSURANCEDEKHO"),
        (r"\bSQUARE\s*INSURANCE\b", "SQUARE"),
        (r"\bRENEW\s*BUY\b", "RENEWBUY"),
        (r"\bPROBUS\b", "PROBUS"),
        (r"\bPB\s*PARTNERS\b", "PBPARTNERS"),
        (r"\bBIMA\s*WALE\s*BHAIYA\b", "BIMA WALE BHAIYA"),
    ]
    for pat, short_nm in known_brokers:
        if re.search(pat, s_up):
            return short_nm

    corp_pat = (
        r"(?i)\b(?:"
        r"INSURANCE\s+BROKING|INSURANCE\s+BROKERS?|INSURANCE\s+WEB\s+AGGREGATOR|"
        r"INSURANCE\s+MARKETING(?:\s+FIRM)?|INSURANCE\s+SERVICES?|"
        r"BROKING\s+SERVICES?|BROKING|BROKERS?|"
        r"PRIVATE\s+LIMITED|PVT\.?\s*LTD\.?|LIMITED|LTD\.?|PRIVATE|LLP"
        r")\b"
    )
    if re.search(corp_pat, s_up):
        trimmed = re.split(corp_pat, s_up)[0]
        trimmed = re.sub(r"\s+", " ", trimmed).strip(" .,:-_/")
        if len(trimmed) >= 2:
            return trimmed
    return s_up


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
                    return shorten_agency_name(val)
    return ""


def extract_premium_mode(pdf_text: str) -> str:
    for m_pay in re.finditer(
        r"(?i)(?:Mode\s*of\s*Payment|(?<!Premium\s)Payment\s*Mode|Payment\s*Details|Payment\s*received\s*by|Instrument\s*Details|Instrument\s*(?:No\.?|Number)|Payment\s*Method)([\s\S]{0,280})",
        pdf_text,
    ):
        block = m_pay.group(0)
        block = re.split(
            r"(?i)(?:Eligibility\s*of\s*Premium|Section\s*80D|Income\s*Tax\s*Act|Terms\s*&\s*Conditions|Processing\s*Centre)",
            block,
        )[0]
        clean_block = re.sub(
            r"(?i)(?:Pin\s*Code|Pincode|HSN\s*Code|Mumbai|Indore|Delhi|Chennai|Hyderabad)\s*[:\-]?\s*\d{6}",
            "",
            block,
        )

        if re.search(
            r"(?i)(?:\b(?:IPG|EPG|PG|Online|UPI|NEFT|RTGS|IMPS|Net\s*Banking|NetBanking|Internet\s*Banking|Credit\s*Card|Debit\s*Card|Card|E-?Pay(?:ment)?|Digital|BillDesk|Razorpay|PayU|Payment\s*Gateway|Gateway|BizDirect|OPS[A-Z0-9]{8,}|EASI\d{8,}|QR_RENEWAL|paymentLink\w*)\b|PG_[A-Z0-9_]+)",
            clean_block,
        ):
            return "ONLINE"

        if re.search(r"(?i)\b(?:Cheque|Chq\.?|DD|Demand\s*Draft)\b", clean_block):
            return "CHEQUE"

        if re.search(r"(?i)Instrument\s*(?:Details|No\.?|Number)", clean_block):
            if re.search(
                r"(?i)Instrument\s*(?:Details|No\.?|Number)[\s\S]{0,120}?(?<![A-Za-z0-9/\-])(\d{10,24})(?![A-Za-z0-9/\-])",
                clean_block,
            ):
                return "ONLINE"
            if re.search(
                r"(?i)Instrument\s*(?:Details|No\.?|Number)[\s\S]{0,200}?(?<![A-Za-z0-9/\-])(\d{6})(?![A-Za-z0-9/\-])",
                clean_block,
            ):
                return "CHEQUE"

        if re.search(r"(?i)\b(?:ECS|NACH|Auto\s*Debit|Standing\s*Instruction)\b", clean_block):
            return "AUTO DEBIT"

        cash_check_block = re.sub(r"(?i)(?:other\s+than\s+cash|paid\s+in\s+cash|cashless)", "", clean_block)
        if re.search(r"(?i)\bCash\b", cash_check_block):
            return "CASH"

    if re.search(r"(?i)Document\s+generated\s+by\s+(?:QR_RENEWAL|ONLINE|PORTAL|WEB)", pdf_text):
        return "ONLINE"

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
