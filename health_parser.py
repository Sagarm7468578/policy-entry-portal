import io
import re
from datetime import datetime, timedelta, timezone
import pandas as pd
from pypdf import PdfReader
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

IST = timezone(timedelta(hours=5, minutes=30))

OUTPUT_COLUMNS = [
    "Client Name", "Client Code", "Mobile", "Mail Id", "Policy Number",
    "Insurance Type", "Sub Type", "Company Name", "Agency", "Sub agent",
    "Plan Name", "Premium", "Sum Insured", "Inception Date", "Expiry Date",
    "Reminder Date", "Premium Mode", "Policy Status", "Remark", "Folder",
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
    reader = PdfReader(io.BytesIO(pdf_bytes))
    parts = []
    for page in reader.pages[:max_pages]:
        txt = page.extract_text() or ""
        parts.append(txt)
    return "\n".join(parts)


def detect_company_by_frequency(pdf_text: str) -> str:
    """Renamer Bot Logic: Jis company ka naam PDF me sabse zyada baar aaye wahi select hogi."""
    text_lower = pdf_text.lower()
    best_company = ""
    best_count = 0

    for company, keywords in COMPANY_KEYWORDS.items():
        count = sum(len(re.findall(re.escape(kw), text_lower)) for kw in keywords)
        if count > best_count:
            best_count = count
            best_company = company

    return best_company if best_count > 0 else ""


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


def extract_generic_agency(pdf_text: str) -> str:
    patterns = [
        r"(?i)(?:Intermediary|Agent|Broker|IMD|Advisor)\s*Name\s*[:\-]\s*([^\r\n]{3,60})",
        r"(?i)Name\s*of\s*(?:Intermediary|Agent|Broker)\s*[:\-]\s*([^\r\n]{3,60})",
    ]
    for pat in patterns:
        m = re.search(pat, pdf_text)
        if m:
            val = re.split(r"(?i)\b(?:Code|Contact|Mobile|Email|Phone|License|ID)\b", m.group(1))[0]
            val = re.sub(r"[^A-Za-z0-9\s.&/-]", "", val).strip()
            if len(val) >= 3:
                return val.upper()
    return ""


def extract_premium_mode(pdf_text: str) -> str:
    m = re.search(r"(?i)(?:Premium\s*(?:Payment\s*)?Mode|Payment\s*Frequency|Policy\s*Tenure)\s*[:\-]?\s*(Annual|Yearly|Half[- ]?Yearly|Quarterly|Monthly|Single|1\s*Year|2\s*Years?|3\s*Years?)", pdf_text)
    if m:
        return m.group(1).strip().upper()
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
        m = re.search(r"(?i)(?:Dear\s+|Name:\s*)([A-Za-z\s]+)", pdf_text)
        if m: data["client_name"] = m.group(1).strip().upper()
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
        m = re.search(r"(?i)(?:Ltd\.?|Co\.?|Company|Limited|Insurance)[\s\r\n]+([A-Z0-9\-\r\n]{8,})[\s\r\n]+MEDICLAIM", pdf_text)
        if m: data["pyp_number"] = re.sub(r"\s+", "", m.group(1))

    # 2. CARE HEALTH
    elif company == "CARE HEALTH":
        if re.search(r"(?i)CARE SUPREME", pdf_text):
            data["plan_name"], data["sub_type"] = "CARE SUPREME", "MEDICLAIM"
        m = re.search(r"(?i)Dear\s+(?:MR\.|MRS\.|MS\.|DR\.|MR\s+|MRS\s+|MS\s+|DR\s+)?([^\r\n,]+)", pdf_text)
        if m: data["client_name"] = m.group(1).strip().upper()
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
        if m:
            name = re.sub(r"[\r\n]+", " ", m.group(1))
            name = re.sub(r"(?i)^\s*(MR\.|MRS\.|MS\.|DR\.|MR\s+|MRS\s+|MS\s+|DR\s+)", "", name)
            data["client_name"] = re.sub(r"\s+\.\s*$", "", name).strip().upper()
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
        if m:
            name = re.sub(r"(?i)\b(MR\.|MRS\.|MS\.|MR\s+|MRS\s+|MS\s+|SHRI\s+)", "", m.group(1))
            data["client_name"] = name.strip().upper()
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
        if m:
            name = re.sub(r"(?i)^((?:MR\.|MRS\.|MS\.|MR|MRS|MS|SHRI)\s*)+", "", m.group(1))
            data["client_name"] = name.strip().upper()
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

    # 6. ICICI LOMBARD
    elif company == "ICICI LOMBARD":
        if re.search(r"(?i)Group Health \(Floater\)", pdf_text):
            data["plan_name"], data["sub_type"] = "GROUP HEALTH", "MEDICLAIM"
        m = re.search(r"(?i)(?:Name of the Insured|Insured Name|Policyholder Name)\s*:\s*([^\r\n]+)", pdf_text)
        if m: data["client_name"] = m.group(1).strip().upper()
        m = re.search(r"(?i)Policy\s*(?:Number|No\.?)\s*[:\-]\s*([0-9]{10,}(?:\s+[0-9]+)?|[0-9]{4}/[A-Z0-9]+/[0-9/]+)", pdf_text)
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
            name = re.sub(r"(?i)^\s*(MR\.|MRS\.|MS\.|MR|MRS|MS)\s*", "", m.group(1))
            name = re.sub(r"(?i)(?:Customer ID|Office Code).*", "", name)
            name = re.sub(r"(?i)\s*S/O\s+(?:MR\.?\s+|MRS\.?\s+|MS\.?\s+)?[A-Z]+", "", name)
            data["client_name"] = name.strip().upper()
        m = re.search(r"(?i)Policy\s*(?:Number|No)\s*[:]?\s*([0-9][A-Z0-9\-]{5,})", pdf_text)
        if m: data["policy_number"] = m.group(1).strip()
        m = re.search(r"(?i)(?:Net Premium[\s\r\n]*\(With[\s\r\n]*GST\)|Net Premium Amt\.?)[^\d]*([\d,]+)", pdf_text)
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
        if m: data["client_name"] = re.sub(r"(?i)IFFCO-TOKIO\s*", "", m.group(1)).strip().upper()
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
        if m: data["client_name"] = m.group(1).replace(",", "").strip().upper()
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

    # 10. TATA AIG
    elif company == "TATA AIG":
        if re.search(r"(?i)Travel Insurance", pdf_text):
            data["plan_name"], data["sub_type"] = "TRAVEL", "TRAVEL INSURANCE"
        m = re.search(r"(?i)(?:Policy\s*Holder\s*Name|Policyholder\s*name)\s*[:]?\s*([^\r\n]+)", pdf_text)
        if m:
            name = re.sub(r"(?i)\s*Policy Number.*", "", m.group(1))
            name = re.sub(r"(?i)^\s*(MR\.|MRS\.|MS\.|MR|MRS|MS)\s*", "", name)
            data["client_name"] = name.strip().upper()
        m = re.search(r"(?i)Policy Number\s*[:]?\s*(\d+)", pdf_text)
        if m: data["policy_number"] = m.group(1).strip()
        m = re.search(r"(?i)(?:Total Premium|Final Premium \(post-tax\))\s*(?:INR)?\s*([0-9][\d,\.]+)", pdf_text)
        if m: data["premium"] = clean_amount(m.group(1))
        m = re.search(r"(?i)(?:Accident & Sickness Medical Expenses|Medical Expenses- Injury and / or Illness).*?(?:\$|USD)\s*([1-9][\d,]+)", pdf_text)
        if m: data["sum_insured"] = clean_amount(m.group(1))
        m = re.search(r"(?i)(?:From|Policy Period Start Date)\s*[:]?\s*(\d{2}/\d{2}/\d{4})", pdf_text)
        if m: data["start_dt"] = parse_any_date(m.group(1))
        m = re.search(r"(?i)(?:To|Policy Period End Date)\s*[:]?\s*(\d{2}/\d{2}/\d{4})", pdf_text)
        if m: data["end_dt"] = parse_any_date(m.group(1))

    # 11. HDFC ERGO
    elif company == "HDFC ERGO":
        if re.search(r"(?i)Optima Secure\s*\+", pdf_text):
            data["plan_name"], data["sub_type"] = "OPTIMA SECURE +", "MEDICLAIM"
        elif re.search(r"(?i)Optima Super Secure", pdf_text):
            data["plan_name"], data["sub_type"] = "OSS", "MEDICLAIM"
        elif re.search(r"(?i)Optima Secure", pdf_text):
            data["plan_name"], data["sub_type"] = "OS", "MEDICLAIM"
        elif re.search(r"(?i)Optima Restore", pdf_text):
            data["plan_name"], data["sub_type"] = "OPTIMA RESTORE", "MEDICLAIM"
        elif re.search(r"(?i)Arogya Sanjeevani", pdf_text):
            data["plan_name"], data["sub_type"] = "AROGYA SANJEEVANI", "MEDICLAIM"
        elif re.search(r"(?i)Energy \(Silver\)", pdf_text):
            data["plan_name"], data["sub_type"] = "ENERGY (SILVER)", "MEDICLAIM"
        elif re.search(r"(?i)SARV SURAKSHA PLUS \(GROUP\)", pdf_text):
            data["plan_name"], data["sub_type"] = "SARV SURAKSHA PLUS (GROUP)", "MEDICLAIM"
        elif re.search(r"(?i)Koti Suraksha", pdf_text):
            data["plan_name"], data["sub_type"] = "KOTI SURAKSHA", "PERSONAL ACCIDENT"
        elif re.search(r"(?i)Individual Personal Accident", pdf_text):
            data["plan_name"], data["sub_type"] = "PERSONAL ACCIDENT", "PERSONAL ACCIDENT"

        if data["plan_name"] == "SARV SURAKSHA PLUS (GROUP)":
            m = re.search(r"(?i)(?<=Name & Address of the Policyholder\s)[^\r\n]+", pdf_text)
            if m: data["client_name"] = m.group(0).strip().upper()
        else:
            m = re.search(r"(?i)(?:Proposer Name\s*:\s*|Dear\s+)([^\r\n,]+)", pdf_text)
            if m:
                name = re.sub(r"(?i)^\s*(MR\.|MRS\.|MS\.|MR|MRS|MS)\s+", "", m.group(1))
                data["client_name"] = name.strip().upper()

        m = re.search(r"\b(\d{15,20})\b", pdf_text)
        if m: data["policy_number"] = m.group(1)
        m = re.search(r"(?i)Gross Premium[^\d]{1,30}([0-9][0-9,]{2,}(?:\.\d{1,2})?)", pdf_text) or re.search(r"(?i)(?:Total Premium|Net Premium|Amount Payable)[^\d]{1,30}([0-9][0-9,]{2,}(?:\.\d{1,2})?)", pdf_text)
        if m: data["premium"] = clean_amount(m.group(1))
        m = re.search(r"(?i)(?:Base Sum Insured\s*per\s*Insured\s*Person[^\d]{0,40}|Sum Insured opted\s*:[^\d]{0,10}|Base Sum Insured[^\d]{0,20}|Total Sum Insured[^\d]{0,20})([1-9][0-9, ]{4,})", pdf_text)
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
    matched = master_df[series.str.contains(re.escape(target), na=False)]
    if matched.empty:
        return empty

    row = matched.iloc[0]
    def get_val(keys):
        for k in keys:
            if k in cols:
                v = row[cols[k]]
                if pd.notna(v):
                    return str(v).strip()
        return ""

    return {
        "client_code": get_val(["client code"]),
        "mobile": get_val(["mobile", "mobile no", "phone"]),
        "mail_id": get_val(["mail id", "mail", "email", "email id"]),
        "sub_agent": get_val(["sub agent", "subagent"]),
        "family_code": get_val(["family code"]),
    }


def process_health_pdf(file_name: str, pdf_bytes: bytes, master_df=None):
    """Returns (row_dict, is_success, error_reason)"""
    today_ist = datetime.now(IST).replace(tzinfo=None)
    entry_date = fmt_date(today_ist)

    base_row = {col: "" for col in OUTPUT_COLUMNS}
    base_row["Insurance Type"] = "HEALTH INSURANCE"
    base_row["Date of Entry"] = entry_date

    try:
        pdf_text = extract_pdf_text(pdf_bytes)
        if len(pdf_text.strip()) < 80:
            base_row["Client Name"] = file_name
            base_row["Folder"] = "PLS CHECK ERROR"
            return base_row, False, "Scanned / Image PDF (text readable nahi hai)"

        company = detect_company_by_frequency(pdf_text)
        supported = {
            "MANIPAL CIGNA", "CARE HEALTH", "NIVA BUPA", "ORIENTAL",
            "UNITED INDIA", "ICICI LOMBARD", "NEW INDIA", "IFFCO TOKIO",
            "BAJAJ ALLIANZ", "TATA AIG", "HDFC ERGO"
        }

        if not company or company not in supported:
            base_row["Client Name"] = file_name
            base_row["Company Name"] = company or "UNKNOWN"
            base_row["Folder"] = "PLS CHECK ERROR"
            return base_row, False, f"Company parser abhi add nahi hua: {company or 'Unknown'}"

        extracted = extract_fields_by_company(company, pdf_text)
        if not extracted["client_name"] and not extracted["policy_number"]:
            base_row["Client Name"] = file_name
            base_row["Company Name"] = company
            base_row["Folder"] = "PLS CHECK ERROR"
            return base_row, False, "Client Name aur Policy Number extract nahi ho paya"

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
            "Policy Number": extracted["policy_number"],
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
            "Folder": "YES",
            "PYP Number": extracted["pyp_number"],
            "Share": "",
            "Share %": "",
            "Family code": master_info["family_code"],
            "Date of Entry": entry_date,
            "DOB": extract_oldest_dob(pdf_text, extracted["start_dt"]),
            "OUR RENEWAL": "",
        })
        return base_row, True, ""

    except Exception as e:
        base_row["Client Name"] = file_name
        base_row["Folder"] = "PLS CHECK ERROR"
        return base_row, False, str(e)


def build_excel_bytes(rows: list) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Policy Entries"

    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)
    text_cols = {"Policy Number", "PYP Number", "Mobile", "Client Code", "Family code"}

    for col_idx, col_name in enumerate(OUTPUT_COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for r_idx, row_dict in enumerate(rows, start=2):
        for col_idx, col_name in enumerate(OUTPUT_COLUMNS, start=1):
            val = row_dict.get(col_name, "")
            cell = ws.cell(row=r_idx, column=col_idx, value=val)
            if col_name in text_cols:
                cell.number_format = "@"

    for col_idx, col_name in enumerate(OUTPUT_COLUMNS, start=1):
        col_letter = ws.cell(row=1, column=col_idx).column_letter
        ws.column_dimensions[col_letter].width = max(len(col_name) + 4, 16)

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
