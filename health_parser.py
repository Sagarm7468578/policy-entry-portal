import io
import re
from datetime import datetime, timedelta, timezone
import pandas as pd
import pymupdf
from pypdf import PdfReader
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
        # New India / PSU multi-line format:
        # Name of the \n Agent/Intermediary/CPSC \n User \n Mrs. SONAL LADDHA \n (NIAAG00134008)
        r"(?i)Name\s+of\s+(?:the\s+)?[\r\n\s]*(?:Agent|Intermediary|Broker|Advisor|POSP)(?:[/\s]*(?:Agent|Intermediary|Broker|Advisor|POSP|CPSC|User|IMD|Direct))*[\s:\-\r\n]+([^\r\n]{3,70})",
        # Care Health stacked format: Intermediary Details \n Name \n Code \n Contact Details \n <Name>
        r"(?i)Intermediary\s*Details\s*[\r\n]+\s*Name\s*[\r\n]+\s*Code\s*[\r\n]+\s*Contact\s*(?:Details|Number|No\.?)\s*[\r\n]+\s*([^\r\n]{3,60})",
        # Care Health / General stacked 2-col format: Intermediary Details \n Name \n Code \n <Name>
        r"(?i)Intermediary\s*Details\s*[\r\n]+\s*Name\s*[\r\n]+\s*Code\s*[\r\n]+\s*([A-Za-z][A-Za-z\s.&/-]{2,55})",
        # Stacked 3-column table format (HDFC ERGO style)
        r"(?i)Intermediary\s*Name\s*[\r\n]+\s*Intermediary\s*Code\s*[\r\n]+\s*Intermediary\s*Contact\s*(?:Number|No\.?)\s*[\r\n]+\s*([^\r\n]{3,60})",
        # Stacked 2-column table format
        r"(?i)Intermediary\s*Name\s*[\r\n]+\s*Intermediary\s*Code\s*[\r\n]+\s*([A-Za-z][A-Za-z\s.&/-]{2,55})",
        # TATA AIG format
        r"(?i)Agent/Intermediary Contact No\.[\s\r\n]+([A-Za-z\s]+?)\s+[A-Z0-9]{5,20}\s+\d{8,15}",
        # General inline formats (colon optional, slash supported)
        r"(?i)(?:Intermediary|Agent|Broker|IMD|Advisor|POSP|Channel\s*Partner|Partner)(?:\s*/\s*(?:Intermediary|Agent|Broker|Advisor|POSP))?\s*Name\s*[:\-]?\s*([^\r\n]{3,65})",
        # Value on immediate next line after label
        r"(?i)(?:Intermediary|Agent|Broker|Advisor)\s*Name\s*[:\-]?\s*[\r\n]+\s*([A-Za-z][A-Za-z\s.&/-]{2,55})",
    ]
    bad_starts = (
        "intermediary", "agent", "broker", "advisor", "code", "contact",
        "mobile", "email", "phone", "license", "details", "number", "no", "id", "address", "user", "cpsc"
    )
    for pat in patterns:
        for m in re.finditer(pat, pdf_text):
            raw = m.group(1)
            # Bracket me likha code (jaise (NIAAG00134008)) hatayein
            raw = re.sub(r"\([^)]*\)", "", raw)
            val = re.split(
                r"(?i)\b(?:Intermediary|Agent|Broker|Code|Contact|Mobile|Email|Phone|License|ID|No\.|Number|Address|Branch|Location)\b",
                raw,
            )[0]
            # Title (Mr./Mrs./Ms./Smt./Shri./Dr.) hatayein
            val = re.sub(r"(?i)^\s*((?:MRS|MISS|MR|MS|DR|SMT|SHRI)(?:\.|\b)\s*)+", "", val)
            val = re.sub(r"[^A-Za-z0-9\s.&/-]", "", val)
            val = re.sub(r"\s+", " ", val).strip(" .:-_/")
            if len(val) >= 3 and not val.isdigit():
                first_word = val.split()[0].lower()
                if first_word not in bad_starts:
                    return val.upper()
    return ""


def extract_premium_mode(pdf_text: str) -> str:
    """
    Payment Details / Instrument Details / Mode of Payment se payment mode
    (CHEQUE / ONLINE / CASH / AUTO DEBIT) nikalta hai.
    'Premium Payment Mode: Single Premium' (frequency) ko skip karke asli payment mode check karta hai.
    """
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


def extract_fields_by_company(company: str, pdf_text: str) -> dict:
    data = {
        "client_name": "", "policy_number": "", "sub_type": "MEDICLAIM",
        "plan_name": "N/A", "premium": "", "sum_insured": "",
        "start_dt": None, "end_dt": None, "pyp_number": ""
    }

    # 1. MANIPAL CIGNA
    if company == "MANIPAL CIGNA":
        if re.search(r"(?i)Sarvah", pdf_text):
            data["plan_name"], data["sub_type"] = "SARVAH PARAM", "MEDICLAIM"
        elif re.search(r"(?i)Super Top Up", pdf_text):
            data["plan_name"], data["sub_type"] = "SUPER TOP UP PLUS", "TOP UP"
        m = re.search(r"(?i)(?:Dear\s+|Name:\s*)([A-Za-z\s\.]+)", pdf_text)
        if m: data["client_name"] = clean_person_name(m.group(1))
        m = re.search(r"(?i)Policy\s*Number\s*[:]?\s*([A-Z0-9]{10,})", pdf_text)
        if m: data["policy_number"] = m.group(1).strip()
        m = re.search(r"(?i)premium\s*of\s*Rs\.?\s*([\d,]+)", pdf_text) or re.search(r"(?i)Total\s*Premium[^\d]*([\d,]+)", pdf_text)
        if m: data["premium"] = clean_amount(m.group(1))
        m = re.search(r"(?i)(?:Base\s*)?Sum\s*Insured[\s\S]{1,100}?\s([1-9][0-9]{5,6})", pdf_text) or re.search(r"(?i)([1-9][0-9]{5,6})\s+25000", pdf_text)
        if m: data["sum_insured"] = clean_amount(m.group(1))
        m = re.search(r"(?i)(?:Start\s*Date|From)[\s:a-z0-9]*?(\d{2}-[A-Za-z]{3}-\d{4})", pdf_text)
        if m: data["start_dt"] = parse_any_date(m.group(1))
        m = re.search(r"(?i)(?:End\s*Date|To)[\s:a-z0-9]*?(\d{2}-[A-Za-z]{3}-\d{4})", pdf_text)
        if m: data["end_dt"] = parse_any_date(m.group(1))
        m = (
            re.search(r"(?i)(?:Ltd\.?|Co\.?|Company|Limited|Insurance)[\s\r\n]+([A-Z0-9\-\r\n]{8,})[\s\r\n]+MEDICLAIM", pdf_text)
            or re.search(r"(?i)Previous\s*Policy\s*Number[\s\S]{1,300}?(?:Ltd\.?|Co\.?|Company|Limited|Insurance)[\s\r\n]+([A-Z0-9\-\r\n]{8,})", pdf_text)
        )
        if m:
            pyp = re.sub(r"(?i)\b(Company|Limited|Insurance|Ltd|Co|MEDICLAIM|Previous\s*Policy\s*Number)\b[\.]?", "", m.group(1))
            data["pyp_number"] = re.sub(r"[\r\n\s]+", "", pyp)

    # 2. CARE HEALTH
    elif company == "CARE HEALTH":
        if re.search(r"(?i)CARE SUPREME", pdf_text):
            data["plan_name"], data["sub_type"] = "CARE SUPREME", "MEDICLAIM"
        m = re.search(r"(?i)Dear\s+([^\r\n,]+)", pdf_text)
        if m: data["client_name"] = clean_person_name(m.group(1))
        m = re.search(r"(?i)Policy No[\.\:]*\s*([A-Z0-9]{8,})", pdf_text)
        if m: data["policy_number"] = m.group(1).strip()
        m = re.search(r"(?i)Premium Paid\s*Rs\.?\s*([\d,]+)", pdf_text) or re.search(r"(?im)^Total\s*([\d,]+)", pdf_text)
        if m: data["premium"] = clean_amount(m.group(1))
        m = re.search(r"(?i)(?:1\s*)?Sum Insured\s*([1-9][0-9,]*000)", pdf_text)
        if m: data["sum_insured"] = clean_amount(m.group(1))
        m = re.search(r"(?i)Start Date[\s\S]{1,30}?(\d{2}-[A-Za-z]{3}-\d{4})", pdf_text)
        if m: data["start_dt"] = parse_any_date(m.group(1))
        m = re.search(r"(?i)End Date[\s\S]{1,30}?(\d{2}-[A-Za-z]{3}-\d{4})", pdf_text)
        if m: data["end_dt"] = parse_any_date(m.group(1))
        m = re.search(r"(?i)Previous\s*Policy\s*Number[\s\S]{1,400}?\b([0-9]{8,})\b", pdf_text)
        if m: data["pyp_number"] = m.group(1).strip()

    # 3. NIVA BUPA
    elif company == "NIVA BUPA":
        m = re.search(r"(?i)Product Name\s*:\s*(ReAssure 3\.0|ReAssure 2\.0|ReAssure|Health Companion|Health Recharge|Aspire)", pdf_text)
        if m:
            data["plan_name"] = m.group(1).strip().upper()
            data["sub_type"] = "TOP UP" if data["plan_name"] == "HEALTH RECHARGE" else "MEDICLAIM"
        m = re.search(r"(?i)Policyholder Name\s*[:]?\s*([\s\S]{1,100}?)(?=\s*Policyholder Address)", pdf_text)
        if m: data["client_name"] = clean_person_name(m.group(1))
        m = re.search(r"(?i)Policy Number\s*[:]?\s*([0-9]{10,})", pdf_text)
        if m: data["policy_number"] = m.group(1).strip()
        m = re.search(r"(?i)Gross Premium[^\d]*([\d,]+)", pdf_text)
        if m: data["premium"] = clean_amount(m.group(1))
        m = re.search(r"(?i)(?:Base\s*)?Sum Insured[\s]*(?:INR|\(in Rs\.?\)|\(Rs\.?\)|in Rs|Rs\.?)?\s*([\d,]{4,}|Unlimited)", pdf_text)
        if m: data["sum_insured"] = clean_amount(m.group(1)).upper()
        m = re.search(r"(?i)From\s*(\d{2}[/-][A-Za-z0-9]{2,3}[/-]\d{4})", pdf_text)
        if m: data["start_dt"] = parse_any_date(m.group(1))
        m = re.search(r"(?i)To\s*(\d{2}[/-][A-Za-z0-9]{2,3}[/-]\d{4})", pdf_text)
        if m: data["end_dt"] = parse_any_date(m.group(1))

    # 4. ORIENTAL
    elif company == "ORIENTAL":
        if re.search(r"(?i)HAPPY FAMILY FLOATER", pdf_text):
            data["plan_name"], data["sub_type"] = "HAPPY FAMILY FLOATER", "MEDICLAIM"
        m = re.search(r"(?i)Insured Name[\s\r\n:]*([A-Za-z\.\s]+)", pdf_text)
        if m: data["client_name"] = clean_person_name(m.group(1))
        m = re.search(r"(?i)forming part of policy number[\s\r\n]*([0-9/]{10,})", pdf_text) or re.search(r"(?i)Policy No\.?[\s\r\n]*([0-9/]{10,})", pdf_text)
        if m: data["policy_number"] = m.group(1).strip()
        m = re.search(r"(?i)(?:Gross Premium|Total Premium in words)[\s\S]{1,100}?Total\s*:\s*([\d,]+)", pdf_text)
        if m: data["premium"] = clean_amount(m.group(1))
        m = re.search(r"(?i)Plan Sum Insured\s*:\s*([\d,]+)", pdf_text)
        if m: data["sum_insured"] = clean_amount(m.group(1))
        m = re.search(r"(?i)FROM\s*[\d:]+\s*ON\s*(\d{2}/\d{2}/\d{4})", pdf_text)
        if m: data["start_dt"] = parse_any_date(m.group(1))
        m = re.search(r"(?i)TO\s*MIDNIGHT\s*OF\s*(\d{2}/\d{2}/\d{4})", pdf_text)
        if m: data["end_dt"] = parse_any_date(m.group(1))
        m = re.search(r"(?i)Prev\.?\s*Policy\s*No\.?\s*:\s*([0-9/]+)", pdf_text)
        if m: data["pyp_number"] = m.group(1).strip()

    # 5. UNITED INDIA
    elif company == "UNITED INDIA":
        if re.search(r"(?i)INDIVIDUAL HEALTH INSURANCE", pdf_text):
            data["plan_name"], data["sub_type"] = "INDIVIDUAL HEALTH", "MEDICLAIM"
        m = re.search(r"(?i)Policyholder Name\s*:\s*([^\r\n]+)", pdf_text)
        if m: data["client_name"] = clean_person_name(m.group(1))
        m = re.search(r"(?i)Policy No\.?\s*:\s*([0-9]+[A-Za-z][0-9]+)", pdf_text)
        if m: data["policy_number"] = m.group(1).strip()
        m = re.search(r"(?im)^Total\s*:\s*([\d,]+)", pdf_text) or re.search(r"(?i)Premium\s*:\s*([\d,]+)", pdf_text)
        if m: data["premium"] = clean_amount(m.group(1))
        m = re.search(r"(?i)SUMMARY OF COVERAGE[\s\S]{1,150}?(?:Gold|Platinum|Silver|Standard|Base)?\s*([1-9][\d,]+)\.\d{2}", pdf_text) or re.search(r"(?i)Sum Insured(?:\([^\)]*\))?[\s\r\n]+[A-Za-z\s]+([1-9][\d,]{4,})", pdf_text)
        if m: data["sum_insured"] = clean_amount(m.group(1))
        m = re.search(r"(?i)Period of Insurance\s*:\s*From[\s\S]{1,50}?(\d{2}/\d{2}/\d{4})", pdf_text)
        if m: data["start_dt"] = parse_any_date(m.group(1))
        m = re.search(r"(?i)To\s*(?:Midnight\s*on\s*)?(\d{2}/\d{2}/\d{4})", pdf_text)
        if m: data["end_dt"] = parse_any_date(m.group(1))
        m = re.search(r"(?i)Previous Policy No\.?\s*:\s*([0-9]+[A-Za-z][0-9]+)", pdf_text)
        if m: data["pyp_number"] = m.group(1).strip()

    # 6. ICICI LOMBARD (Group Health + Retail Health)
    elif company == "ICICI LOMBARD":
        if re.search(r"(?i)Group Health \(Floater\)", pdf_text):
            data["plan_name"], data["sub_type"] = "GROUP HEALTH", "MEDICLAIM"
        m = re.search(r"(?i)(?:Name of the Insured|Insured Name|Policyholder Name)\s*:\s*([^\r\n]+)", pdf_text)
        if m: data["client_name"] = clean_person_name(m.group(1))
        m = (
            re.search(r"\b(\d{4}/[A-Z0-9]+/\d{5,}/\d+/\d+)\b", pdf_text)
            or re.search(r"(?i)Policy\s*(?:Number|No\.?)\s*[:\-]\s*([0-9]{10,}(?:\s+[0-9]+)?|[0-9]{4}/[A-Z0-9]+/[0-9/]+)", pdf_text)
        )
        if m: data["policy_number"] = re.sub(r"\s+", "", m.group(1))
        m = re.search(r"(?i)(?:Basic Premium|Total Premium)\s*:\s*[`₹Rs\.\s]*([\d,]+)", pdf_text)
        if m: data["premium"] = clean_amount(m.group(1))
        m = re.search(r"(?i)Total Lives Insured[\s\S]{1,60}?Sum Insured\s*:\s*[`₹Rs\.\s]*([\d,]+)", pdf_text) or re.search(r"(?i)Sum Insured\s*:\s*[`₹Rs\.\s]*([\d,]{5,})", pdf_text)
        if m: data["sum_insured"] = clean_amount(m.group(1))
        m = re.search(r"(?i)Period\s*of\s*Insurance[\s\S]{1,60}?From:?\s*(?:00:00\s*Hours\s*of\s*)?([A-Za-z]{3}\s+\d{1,2}[,\s]+\d{4}|\d{2}[-/]\d{2}[-/]\d{4}|\d{2}[-/][A-Za-z]{3}[-/]\d{4})", pdf_text)
        if m: data["start_dt"] = parse_any_date(m.group(1))
        m = re.search(r"(?i)To\s*(?:Midnight\s*)?([A-Za-z]{3}\s+\d{1,2}[,\s]+\d{4}|\d{2}[-/]\d{2}[-/]\d{4}|\d{2}[-/][A-Za-z]{3}[-/]\d{4})", pdf_text)
        if m: data["end_dt"] = parse_any_date(m.group(1))

    # 7. NEW INDIA
    elif company == "NEW INDIA":
        if re.search(r"(?i)Compulsory Personal Accident", pdf_text):
            data["plan_name"], data["sub_type"] = "CPA VEHICLE", "PERSONAL ACCIDENT"
        elif re.search(r"(?i)Yuva Bharat Health", pdf_text):
            data["plan_name"], data["sub_type"] = "YUVA BHARAT", "MEDICLAIM"
        elif re.search(r"(?i)Asha Kiran Policy", pdf_text):
            data["plan_name"], data["sub_type"] = "ASHA KIRAN", "MEDICLAIM"
        elif re.search(r"(?i)New India Mediclaim Policy", pdf_text):
            data["plan_name"], data["sub_type"] = "MEDICLAIM", "MEDICLAIM"
        m = re.search(r"(?i)(?:Insured Name|Policyholder Name)\s*[:]?\s*([^\r\n]+)", pdf_text)
        if m:
            name = re.sub(r"(?i)(?:Customer ID|Office Code).*", "", m.group(1))
            name = re.sub(r"(?i)\s*S/O\s+(?:MR\.?\s+|MRS\.?\s+|MS\.?\s+)?[A-Z]+", "", name)
            data["client_name"] = clean_person_name(name)
        m = re.search(r"(?i)Policy\s*(?:Number|No)\s*[:]?\s*([0-9][A-Z0-9\-]{5,})", pdf_text)
        if m: data["policy_number"] = m.group(1).strip()
        m = (
            re.search(r"(?i)(?:Net Premium[\s\r\n]*\(With[\s\r\n]*GST\)|Net Premium Amt\.?)[^\d]*([\d,]+)", pdf_text)
            or re.search(r"(?i)Total\(`\)[\s\S]{1,80}?`\s*[\d,]+\s*`\s*[\d,]+\s*`\s*([1-9][\d,]+)", pdf_text)
        )
        if m: data["premium"] = clean_amount(m.group(1))
        m = re.search(r"(?i)(?:Floater Sum Insured|Total Sum Insured|Capital Sum Insured)\s*([1-9][\d,]+)", pdf_text) or re.search(r"(?im)\b(?:Proposer|Spouse|Self|Child|Daughter|Son)\b\s+(?:NA\s+)?([1-9][\d,]{4,})", pdf_text)
        if m: data["sum_insured"] = clean_amount(m.group(1))
        m = re.search(r"(?i)(?:Period of Insurance|Policy Period)[\s\S]{1,50}?(?:From\s*:\s*)?(\d{2}/\d{2}/\d{4})", pdf_text)
        if m: data["start_dt"] = parse_any_date(m.group(1))
        m = re.search(r"(?i)To\s*:?\s*(\d{2}/\d{2}/\d{4})", pdf_text)
        if m: data["end_dt"] = parse_any_date(m.group(1))
        m = re.search(r"(?i)Prev(?:ious)?\.?\s*Policy\s*(?:no\.?|Number)\s*[:]?\s*([A-Z0-9\-]+)", pdf_text)
        if m: data["pyp_number"] = m.group(1).strip()

    # 8. IFFCO TOKIO
    elif company == "IFFCO TOKIO":
        if re.search(r"(?i)PERSONAL ACCIDENT", pdf_text):
            data["plan_name"], data["sub_type"] = "PERSONAL ACCIDENT", "PERSONAL ACCIDENT"
        elif re.search(r"(?i)Family Health Protector", pdf_text):
            data["plan_name"], data["sub_type"] = "FHP", "MEDICLAIM"
        if data["plan_name"] == "FHP":
            m = re.search(r"(?i)Proposer Name\s+([A-Za-z][A-Za-z\s]+?)(?=\s+Address|\s+Gstin|\s+Contact|\s+Tax|\s+Policy|\n|$)", pdf_text)
        else:
            m = re.search(r"(?i)Insured.*?Name\s*[:;]?[\s\r\n]*([A-Za-z\s]+)", pdf_text) or re.search(r'(?im)^"?([A-Za-z\s]+?)"?[\s,]+\d{1,2}[\s,]+Self\b', pdf_text)
        if m:
            name = re.sub(r"(?i)IFFCO-TOKIO\s*", "", m.group(1))
            data["client_name"] = clean_person_name(name)
        m = re.search(r"(?i)Policy\s*(?:#|No)[^\da-z]*([A-Z0-9\-]*\d[A-Z0-9\-]*)", pdf_text)
        if m: data["policy_number"] = m.group(1).strip()
        m = re.search(r"(?i)(?:received an amount of|Gross Premium Payable|Invoice Value)[^\d]*([\d,\.]+)", pdf_text)
        if m: data["premium"] = clean_amount(m.group(1))
        m = re.search(r"(?i)(?:Basic Sum Insured For Family|Total Floater Sum Insured|DEATH)[\s\r\n]*([1-9][\d,]+)", pdf_text)
        if m: data["sum_insured"] = clean_amount(m.group(1))
        m = re.search(r"(?i)From\s*(?:0001\s*hrs\s*on\s*:?\s*)?(\d{2}/\d{2}/\d{4})", pdf_text)
        if m: data["start_dt"] = parse_any_date(m.group(1))
        m = re.search(r"(?i)Midnight\s*on\s*(\d{2}/\d{2}/\d{4})", pdf_text)
        if m: data["end_dt"] = parse_any_date(m.group(1))
        m = re.search(r"(?i)LTD\s+([A-Z0-9]{6,})\s+\d{2}/\d{2}/\d{4}", pdf_text)
        if m: data["pyp_number"] = m.group(1).strip()

    # 9. BAJAJ ALLIANZ
    elif company == "BAJAJ ALLIANZ":
        if re.search(r"(?i)INDIVIDUAL TRAVEL", pdf_text):
            data["plan_name"], data["sub_type"] = "TRAVEL", "TRAVEL INSURANCE"
        m = re.search(r"(?i)Dear\s+(?!Customer)([^,\r\n]+)", pdf_text) or re.search(r"(?i)Proposer Name\s*:\s*([^\r\n]+)", pdf_text)
        if m: data["client_name"] = clean_person_name(m.group(1))
        m = re.search(r"(?i)Policy No\.\s*([\d\-]+)", pdf_text)
        if m: data["policy_number"] = m.group(1).strip()
        m = re.search(r"(?i)Total Premium\s*(?:Rs\.?)?\s*([0-9][\d,\.]+)", pdf_text)
        if m: data["premium"] = clean_amount(m.group(1))
        m = re.search(r"(?i)(?:Medical Expenses[\s\S]{1,60}?|Platinum\s*)(?:USD|\$)\s*([1-9][\d,]+)", pdf_text)
        if m: data["sum_insured"] = clean_amount(m.group(1))
        m = re.search(r"(?i)From\s*:\s*(\d{2}/\d{2}/\d{4})", pdf_text)
        if m: data["start_dt"] = parse_any_date(m.group(1))
        m = re.search(r"(?i)To\s*:\s*(\d{2}/\d{2}/\d{4})", pdf_text)
        if m: data["end_dt"] = parse_any_date(m.group(1))
        m = re.search(r"(?i)Previous Policy No[\s:]*([0-9][A-Z0-9\-]{5,})", pdf_text)
        if m: data["pyp_number"] = m.group(1).strip()

    # 10. TATA AIG (Health + Travel International Plus)
    elif company == "TATA AIG":
        if re.search(r"(?i)Travel Insurance", pdf_text):
            data["plan_name"], data["sub_type"] = "TRAVEL", "TRAVEL INSURANCE"
        m = re.search(r"(?i)(?:Policy\s*Holder\s*Name|Policyholder\s*name)\s*[:]?\s*([^\r\n]+)", pdf_text)
        if m:
            name = re.sub(r"(?i)\s*Policy Number.*", "", m.group(1))
            data["client_name"] = clean_person_name(name)
        m = re.search(r"(?i)Policy\s*(?:No\.?|Number)\s*[:]?\s*(\d+)", pdf_text)
        if m: data["policy_number"] = m.group(1).strip()
        m = re.search(r"(?i)(?:Total Premium|Final Premium \(post-tax\)|Total Amount \(in INR\)|Total Amount Payable|Final Premium)\s*[:]?\s*(?:Rs\.?|INR)?\s*([0-9][\d,\.]+)", pdf_text)
        if m: data["premium"] = clean_amount(m.group(1))
        m = (
            re.search(r"(?i)Personal Accident in India[^0-9]*([1-9][\d,]+)", pdf_text)
            or re.search(r"(?i)(?:Accident & Sickness Medical Expenses|Medical Expenses- Injury and / or Illness).*?(?:\$|USD)\s*([1-9][\d,]+)", pdf_text)
        )
        if m: data["sum_insured"] = clean_amount(m.group(1))
        m = re.search(r"(?i)(?:From|Policy Period Start Date)\s*[:]?\s*(\d{2}/\d{2}/\d{4})", pdf_text)
        if m: data["start_dt"] = parse_any_date(m.group(1))
        m = re.search(r"(?i)(?:To|Policy Period End Date)\s*[:]?\s*(\d{2}/\d{2}/\d{4})", pdf_text)
        if m: data["end_dt"] = parse_any_date(m.group(1))

    # 11. HDFC ERGO (Standard + Optima Secure + Arogya Sanjeevani)
    elif company == "HDFC ERGO":
        is_my_optima = bool(re.search(r"(?i)my:\s*Optima Secure", pdf_text))
        m_plan = re.search(
            r"(?i)(?:my:\s*Optima Secure\s*[-–]\s*|Insured Person.?s Details and Sum Insured\s*[-–]\s*|Arogya Sanjeevani Policy,\s*)(Optima Secure[\s+]*|Optima Super Secure|HDFC ERGO)",
            pdf_text
        )
        temp_plan = m_plan.group(0) if m_plan else ""

        if "+" in temp_plan:
            data["plan_name"], data["sub_type"] = "OPTIMA SECURE +", "MEDICLAIM"
        elif re.search(r"(?i)Super", temp_plan) or re.search(r"(?i)Optima Super Secure", pdf_text):
            data["plan_name"], data["sub_type"] = "OSS", "MEDICLAIM"
        elif re.search(r"(?i)Arogya Sanjeevani", pdf_text):
            data["plan_name"], data["sub_type"] = "AROGYA SANJEEVANI", "MEDICLAIM"
        elif re.search(r"(?i)Optima Secure", pdf_text):
            data["plan_name"], data["sub_type"] = "OS", "MEDICLAIM"
        elif re.search(r"(?i)Optima Restore", pdf_text):
            data["plan_name"], data["sub_type"] = "OPTIMA RESTORE INDIVIDUAL", "MEDICLAIM"
        elif re.search(r"(?i)Energy \(Silver\)", pdf_text):
            data["plan_name"], data["sub_type"] = "ENERGY (SILVER)", "MEDICLAIM"
        elif re.search(r"(?i)SARV SURAKSHA PLUS \(GROUP\)", pdf_text):
            data["plan_name"], data["sub_type"] = "SARV SURAKSHA PLUS (GROUP)", "MEDICLAIM"
        elif re.search(r"(?i)Koti Suraksha", pdf_text):
            data["plan_name"], data["sub_type"] = "KOTI SURAKSHA", "PERSONAL ACCIDENT"
        elif re.search(r"(?i)(?:Product/Policy Individual Personal Accident|Individual Personal Accident)", pdf_text):
            data["plan_name"], data["sub_type"] = "PERSONAL ACCIDENT", "PERSONAL ACCIDENT"

        if data["plan_name"] == "SARV SURAKSHA PLUS (GROUP)":
            m = re.search(r"(?i)(?<=Name & Address of the Policyholder\s)[^\r\n]+", pdf_text)
            if m: data["client_name"] = clean_person_name(m.group(0))
        else:
            m = re.search(r"(?i)(?:Proposer Name\s*:\s*|Dear\s+)([^\r\n,]+)", pdf_text)
            if m: data["client_name"] = clean_person_name(m.group(1))

        m = re.search(r"\b(\d{15,20})\b", pdf_text)
        if m: data["policy_number"] = f",{m.group(1)}"

        if is_my_optima:
            m = (
                re.search(r"(?i)received\s*an\s*amount\s*of[^0-9]*([0-9,]{4,})", pdf_text)
                or re.search(r"(?i)(?:Total Premium|Net Premium|Amount Payable)[^\d]{1,30}([0-9][0-9,]{2,}(?:\.\d{1,2})?)", pdf_text)
            )
        else:
            m = (
                re.search(r"(?i)Gross Premium[^\d]{1,30}([0-9][0-9,]{2,}(?:\.\d{1,2})?)", pdf_text)
                or re.search(r"(?i)(?:Total Premium|Net Premium|Amount Payable)[^\d]{1,30}([0-9][0-9,]{2,}(?:\.\d{1,2})?)", pdf_text)
            )
        if m: data["premium"] = clean_amount(m.group(1))

        m = (
            re.search(r"(?i)(?:Base Sum Insured\s*per\s*Insured\s*Person[^\d]{0,40}|Sum Insured opted\s*:[^\d]{0,10}|Base Sum Insured[^\d]{0,20}|Total Sum Insured[^\d]{0,20})([1-9][0-9, ]{4,})", pdf_text)
            or re.search(r"(?i)(?:Sum Insured opted[\s:]*|1[\s\.\-]*Accidental Death[^\d]{0,20})([1-9][0-9,]{4,})", pdf_text)
            or re.search(r"(?i)Base\s*Sum\s*Insured[\s\S]{1,500}?\b\d{2}[/-]\d{2}[/-]\d{4}\s+([1-9][0-9,]{4,8})\b", pdf_text)
        )
        if m: data["sum_insured"] = clean_amount(m.group(1))

        if data["plan_name"] == "SARV SURAKSHA PLUS (GROUP)":
            m = re.search(r"(?i)From\s*00:01\s*hours:\s*([A-Za-z]+\s*\d{1,2},\s*\d{4})", pdf_text)
            if m: data["start_dt"] = parse_any_date(m.group(1))
            m = re.search(r"(?i)To\s*\(Midnight\)\s*:\s*([A-Za-z]+\s*\d{1,2},\s*\d{4})", pdf_text)
            if m: data["end_dt"] = parse_any_date(m.group(1))
        else:
            m = re.search(r"(?i)From\s*(?:\d{2}:\d{2}\s*hrs\s*on\s*)?(\d{2}[/-]\d{2}[/-]\d{4})", pdf_text)
            if m: data["start_dt"] = parse_any_date(m.group(1))
            m = re.search(r"(?i)To\s*(?:\d{2}:\d{2}\s*hrs\s*on\s*)?(\d{2}[/-]\d{2}[/-]\d{4})", pdf_text)
            if m: data["end_dt"] = parse_any_date(m.group(1))

        m = re.search(r"(?i)Previous Policy[\s:]*(\d{6,})", pdf_text)
        if m: data["pyp_number"] = f",{m.group(1).strip()}"

    # 12. NATIONAL INSURANCE
    elif company == "NATIONAL":
        if re.search(r"(?i)National Senior Citizen", pdf_text):
            data["plan_name"], data["sub_type"] = "SENIOR CITIZEN", "MEDICLAIM"
        elif re.search(r"(?i)Personal Accident", pdf_text):
            data["plan_name"], data["sub_type"] = "PERSONAL ACCIDENT", "PERSONAL ACCIDENT"
        elif re.search(r"(?i)Parivar Mediclaim", pdf_text):
            data["plan_name"], data["sub_type"] = "PARIVAR MEDICLAIM", "MEDICLAIM"
        elif re.search(r"(?i)National Mediclaim", pdf_text):
            data["plan_name"], data["sub_type"] = "MEDICLAIM", "MEDICLAIM"

        m = (
            re.search(r"(?i)Customer Name\s*:\s*(?:MR\.|MRS\.|MS\.|MR|MRS|MS|_)?\s*([A-Za-z\s]+?)\s*गाहक", pdf_text)
            or re.search(r"(?i)Customer Name\s*:\s*([^\r\n]+)", pdf_text)
        )
        if m:
            name = re.sub(r"\s*गाहक.*", "", m.group(1))
            data["client_name"] = clean_person_name(name)

        m = re.search(r"(?i)Policy Number[^\d]{1,20}(\d{15,20})", pdf_text)
        if m: data["policy_number"] = m.group(1).strip()

        m = re.search(r"(?i)Total Amount\s*[`₹Rs\.\s]*([\d,]+)", pdf_text)
        if m: data["premium"] = clean_amount(m.group(1))

        si_patterns = [
            r"(?i)24 Hours Coverage[^\d]{1,20}([1-9](?:\d{4,9}|\d{0,2}(?:,\d{2,3})+))",
            r"(?i)Basic Cover Sum\s*Insured[^\d]{1,20}([1-9](?:\d{4,9}|\d{0,2}(?:,\d{2,3})+))",
            r"(?i)\b(?:Male|Female|M|F)\s+([1-9](?:\d{4,9}|\d{0,2}(?:,\d{2,3})+))",
            r"(?i)Capital Sum Insured[^\d]{1,30}([1-9](?:\d{4,9}|\d{0,2}(?:,\d{2,3})+))",
        ]
        for pat in si_patterns:
            m = re.search(pat, pdf_text)
            if m:
                data["sum_insured"] = clean_amount(m.group(1))
                break

        m = re.search(r"(?i)Policy Effective from.*?on\s*(\d{2}/\d{2}/\d{4})", pdf_text)
        if m: data["start_dt"] = parse_any_date(m.group(1))
        m = re.search(r"(?i)to\s*midnight\s*of\s*(\d{2}/\d{2}/\d{4})", pdf_text)
        if m: data["end_dt"] = parse_any_date(m.group(1))

        m_blk = re.search(r"(?i)Previous Policy Number[\s\S]{1,600}?(?:\(|\*सरकारी)", pdf_text)
        if m_blk:
            m_pyp = re.search(r"(\d{15,20})[^\n\r]*[\r\n]+\s*(?:\(|\*सरकारी)", m_blk.group(0))
            if m_pyp:
                data["pyp_number"] = m_pyp.group(1).strip()
            else:
                all_pyps = re.findall(r"\b\d{15,20}\b", m_blk.group(0))
                if all_pyps:
                    data["pyp_number"] = all_pyps[-1]

    # 13. ADITYA BIRLA HEALTH
    elif company == "ADITYA BIRLA":
        data["sub_type"] = "MEDICLAIM"
        if re.search(r"(?i)(?:Plan MAX\+|Variants MAX\+)", pdf_text):
            data["plan_name"] = "ACTIV ONE MAX+"
        elif re.search(r"(?i)Plan MAX", pdf_text):
            data["plan_name"] = "ACTIV ONE MAX"
        elif re.search(r"(?i)(?:Platinum - Enhanced|Platinum - Essential|Product Name:?\s*Activ Health)", pdf_text):
            data["plan_name"] = "ACTIV HEALTH"
        elif re.search(r"(?i)Product Name:?\s*Activ One", pdf_text):
            data["plan_name"] = "ACTIV ONE"

        m = re.search(r"(?i)Policyholder Name\s*[:]?\s*([^\r\n]+)", pdf_text)
        if m: data["client_name"] = clean_person_name(m.group(1))

        m = re.search(r"(?i)Policy Number\s*[:]?\s*(\d{2}-\d{2}-\d{7}-\d{2})", pdf_text)
        if m: data["policy_number"] = m.group(1).strip()

        m = (
            re.search(r"(?i)receipt of premium amount of INR\s*([\d,\.]+)", pdf_text)
            or re.search(r"(?i)(?:Gross|Total)\s*Premium[^\d]{1,20}([\d,\.]+)", pdf_text)
        )
        if m: data["premium"] = clean_amount(m.group(1))

        m = (
            re.search(r"(?i)\b([1-9]\d{4,8})\s*[\r\n]*\s*(?:30\s*Days|Zone\s*[IV]*)", pdf_text)
            or re.search(r"(?i)Sum Insured[^\d]{1,30}([1-9][\d,]{4,})", pdf_text)
        )
        if m: data["sum_insured"] = clean_amount(m.group(1))

        m = re.search(r"(?i)Start Date of Policy & Time.*?on\s*(\d{2}/\d{2}/\d{4})", pdf_text)
        if m: data["start_dt"] = parse_any_date(m.group(1))
        m = re.search(r"(?i)Expiry Date & Time of Policy.*?on\s*(\d{2}/\d{2}/\d{4})", pdf_text)
        if m: data["end_dt"] = parse_any_date(m.group(1))

        m = re.search(r"(?i)Previous Policy Number\s*[:]?\s*(\d{2}-\d{2}-\d{7}-\d{2})", pdf_text)
        if m: data["pyp_number"] = m.group(1).strip()

    # 14. STAR HEALTH
    elif company == "STAR HEALTH":
        if re.search(r"(?i)Medi Classic", pdf_text):
            data["plan_name"], data["sub_type"] = "MEDI CLASSIC", "MEDICLAIM"
        elif re.search(r"(?i)Health Assure", pdf_text):
            data["plan_name"], data["sub_type"] = "HEALTH ASSURE", "MEDICLAIM"
        elif re.search(r"(?i)Star Hospital Cash", pdf_text):
            data["plan_name"], data["sub_type"] = "HOSPITAL CASH", "MEDICLAIM"
        elif re.search(r"(?i)Family Health Optima", pdf_text):
            data["plan_name"], data["sub_type"] = "FAMILY HEALTH OPTIMA", "MEDICLAIM"
        elif re.search(r"(?i)Star Comprehensive", pdf_text):
            data["plan_name"], data["sub_type"] = "STAR COMPREHENSIVE", "MEDICLAIM"
        elif re.search(r"(?i)Star Women Care", pdf_text):
            data["plan_name"], data["sub_type"] = "STAR WOMEN CARE", "MEDICLAIM"
        elif re.search(r"(?i)Super Surplus", pdf_text):
            data["plan_name"], data["sub_type"] = "STAR SUPER SURPLUS", "TOP UP"
        elif re.search(r"(?i)Super Star", pdf_text):
            data["plan_name"], data["sub_type"] = "SUPER STAR", "MEDICLAIM"
        elif re.search(r"(?i)(?:Critical Illness MultiPay|Star Critical Illness)", pdf_text):
            data["plan_name"], data["sub_type"] = "STAR CRITICAL ILLNESS", "MEDICLAIM"
        elif re.search(r"(?i)Arogya Sanjeevani", pdf_text):
            data["plan_name"], data["sub_type"] = "AROGYA SANJEEVANI", "MEDICLAIM"
        elif re.search(r"(?i)Family Accident Care", pdf_text):
            data["plan_name"], data["sub_type"] = "FAMILY ACCIDENT CARE", "PERSONAL ACCIDENT"
        elif re.search(r"(?i)(?:Senior Citizens Red Carpet|Red Carpet)", pdf_text):
            data["plan_name"], data["sub_type"] = "SENIOR CITIZENS RED CARPET", "MEDICLAIM"

        m = re.search(r"(?i)Customer Name\s*:\s*([^\r\n]+(?:\s*[\r\n]+(?![^\r\n]*(?::|\d))[^\r\n]+)?)", pdf_text)
        if m:
            raw_name = re.sub(r"\d.*$", "", m.group(1), flags=re.S).replace(".", " ")
            data["client_name"] = clean_person_name(raw_name)

        m = re.search(r"(?i)(?:Policy No|Certificate No)[^\d]{0,15}(\d{15,20})", pdf_text)
        if m: data["policy_number"] = m.group(1).strip()

        m = re.search(r"(?i)Total Premium\s*:\s*(?:Rs\.?|₹)?\s*([\d,]+)", pdf_text)
        if m: data["premium"] = clean_amount(m.group(1))

        si_match = (
            re.search(r"(?i)(?:Sum Insured|Basic Floater Sum Insured|Basic Sum Insured(?:\s*\(Health\))?)\s*(?:\(Rs\.\)|:)?\s*(?:Rs\.?)?\s*([1-9][\d,\r\n]{4,15})", pdf_text)
            or re.search(r"(?i)(?:Male|Female)\s+(?:\d{2}-[A-Za-z]{3}-\d{4}\s+)?\d{1,3}\s+([1-9][\d,\r\n]{4,15})", pdf_text)
            or re.search(r"(?i)(?:Male|Female)[\s\S]{1,150}?\s([1-9][\d,\r\n]{4,15})\s+[A-Za-z]", pdf_text)
        )
        if si_match:
            cleaned_si_block = re.sub(r"[\r\n]+", "", si_match.group(1))
            m_num = re.search(r"[1-9]\d{0,2}(?:,\d{2,3})+", cleaned_si_block) or re.search(r"[1-9]\d{4,8}", cleaned_si_block)
            if m_num:
                data["sum_insured"] = clean_amount(m_num.group(0))
        if not data["sum_insured"]:
            m_hc = re.search(r"(?i)Hospital Cash Amount[^0-9]+([1-9][\d,]+)", pdf_text)
            if m_hc:
                data["sum_insured"] = clean_amount(m_hc.group(1))

        m = re.search(r"(?i)From\s*:\s*(\d{2}-[A-Za-z]{3}-\d{4}|\d{2}/\d{2}/\d{4})", pdf_text)
        if m: data["start_dt"] = parse_any_date(m.group(1))
        m = re.search(r"(?i)To\s*:\s*(?:Midnight Of\s*)?(\d{2}-[A-Za-z]{3}-\d{4}|\d{2}/\d{2}/\d{4})", pdf_text)
        if m: data["end_dt"] = parse_any_date(m.group(1))

        m = re.search(r"(?i)(?:Previous Policy\s*No|Previous Certificate\s*No|renewal premium of policy number)[^\d]{0,15}(\d{10,25})", pdf_text)
        if m: data["pyp_number"] = m.group(1).strip()

    return data


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


def process_health_pdf(file_name: str, pdf_bytes: bytes, master_df=None):
    """Returns (row_dict, is_success, error_reason, debug_info)"""
    today_ist = datetime.now(IST).replace(tzinfo=None)
    entry_date = fmt_date(today_ist)

    base_row = {col: "" for col in OUTPUT_COLUMNS}
    base_row["Insurance Type"] = "HEALTH INSURANCE"
    base_row["Date of Entry"] = entry_date

    debug_info = {
        "file_name": file_name,
        "client_name": "",
        "detected_company": "",
        "company_scores": {},
        "raw_text": "",
        "error_reason": "",
    }

    try:
        pdf_text = extract_pdf_text(pdf_bytes)
        debug_info["raw_text"] = pdf_text

        if len(pdf_text.strip()) < 80:
            base_row["Client Name"] = file_name
            debug_info["client_name"] = file_name
            debug_info["error_reason"] = "Scanned / Image PDF (text readable nahi hai)"
            return base_row, False, debug_info["error_reason"], debug_info

        scores = get_company_scores(pdf_text)
        company = next(iter(scores.keys()), "")
        debug_info["company_scores"] = scores
        debug_info["detected_company"] = company

        supported = set(COMPANY_KEYWORDS.keys())
        if not company or company not in supported:
            base_row["Client Name"] = file_name
            base_row["Company Name"] = company or "UNKNOWN"
            debug_info["client_name"] = file_name
            debug_info["error_reason"] = f"Company parser abhi add nahi hua: {company or 'Unknown'}"
            return base_row, False, debug_info["error_reason"], debug_info

        extracted = extract_fields_by_company(company, pdf_text)
        if not extracted["client_name"] and not extracted["policy_number"]:
            base_row["Client Name"] = file_name
            base_row["Company Name"] = company
            debug_info["client_name"] = file_name
            debug_info["error_reason"] = "Client Name aur Policy Number extract nahi ho paya"
            return base_row, False, debug_info["error_reason"], debug_info

        debug_info["client_name"] = extracted["client_name"] or file_name
        master_info = lookup_client_master(extracted["client_name"], master_df)

        end_dt = extracted["end_dt"]
        reminder_date = fmt_date(end_dt - timedelta(days=15)) if end_dt else ""
        policy_status = ""
        if end_dt:
            policy_status = "INACTIVE" if end_dt.date() < today_ist.date() else "ACTIVE"

        base_row.update({
            "Client Name": extracted["client_name"],
            "Client Code": master_info["client_code"],
            "Mobile": master_info["mobile"],
            "Mail Id": master_info["mail_id"],
            "Policy Number": str(extracted["policy_number"]),
            "Insurance Type": "HEALTH INSURANCE",
            "Sub Type": extracted["sub_type"],
            "Company Name": company,
            "Agency": extract_generic_agency(pdf_text),
            "Sub agent": master_info["sub_agent"],
            "Plan Name": extracted["plan_name"],
            "Premium": extracted["premium"],
            "Sum Insured": extracted["sum_insured"],
            "Inception Date": fmt_date(extracted["start_dt"]),
            "Expiry Date": fmt_date(end_dt),
            "Reminder Date": reminder_date,
            "Premium Mode": extract_premium_mode(pdf_text),
            "Policy Status": policy_status,
            "Remark": "",
            "PYP Number": str(extracted["pyp_number"]),
            "Share": "",
            "Share %": "",
            "Family code": master_info["family_code"],
            "Date of Entry": entry_date,
            "DOB": extract_oldest_dob(pdf_text, extracted["start_dt"]),
            "OUR RENEWAL": "",
        })
        return base_row, True, "", debug_info

    except Exception as e:
        base_row["Client Name"] = file_name
        debug_info["client_name"] = file_name
        debug_info["error_reason"] = str(e)
        return base_row, False, str(e), debug_info


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
