import re
from .common import default_extracted_data, clean_person_name, clean_amount, parse_any_date


def parse(pdf_text: str) -> dict:
    data = default_extracted_data()

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
    if m:
        data["policy_number"] = m.group(1).strip()

    m = (
        re.search(r"(?i)(?:Net Premium[\s\r\n]*\(With[\s\r\n]*GST\)|Net Premium Amt\.?)[^\d]*([\d,]+)", pdf_text)
        or re.search(r"(?i)Total\(`\)[\s\S]{1,80}?`\s*[\d,]+\s*`\s*[\d,]+\s*`\s*([1-9][\d,]+)", pdf_text)
    )
    if m:
        data["premium"] = clean_amount(m.group(1))

    m = (
        re.search(r"(?i)(?:Floater Sum Insured|Total Sum Insured|Capital Sum Insured)\s*([1-9][\d,]+)", pdf_text)
        or re.search(r"(?im)\b(?:Proposer|Spouse|Self|Child|Daughter|Son)\b\s+(?:NA\s+)?([1-9][\d,]{4,})", pdf_text)
    )
    if m:
        data["sum_insured"] = clean_amount(m.group(1))

    m = re.search(r"(?i)(?:Period of Insurance|Policy Period)[\s\S]{1,50}?(?:From\s*:\s*)?(\d{2}/\d{2}/\d{4})", pdf_text)
    if m:
        data["start_dt"] = parse_any_date(m.group(1))

    m = re.search(r"(?i)To\s*:?\s*(\d{2}/\d{2}/\d{4})", pdf_text)
    if m:
        data["end_dt"] = parse_any_date(m.group(1))

    m = re.search(r"(?i)Prev(?:ious)?\.?\s*Policy\s*(?:no\.?|Number)\s*[:]?\s*([A-Z0-9\-]+)", pdf_text)
    if m:
        data["pyp_number"] = m.group(1).strip()

    return data
