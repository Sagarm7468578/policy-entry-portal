import re
from .common import default_extracted_data, clean_person_name, clean_amount, parse_any_date


def parse(pdf_text: str) -> dict:
    data = default_extracted_data()

    if re.search(r"(?i)Sarvah", pdf_text):
        data["plan_name"], data["sub_type"] = "SARVAH PARAM", "MEDICLAIM"
    elif re.search(r"(?i)Super Top Up", pdf_text):
        data["plan_name"], data["sub_type"] = "SUPER TOP UP PLUS", "TOP UP"

    m = re.search(r"(?i)(?:Dear\s+|Name:\s*)([A-Za-z\s\.]+)", pdf_text)
    if m:
        data["client_name"] = clean_person_name(m.group(1))

    m = re.search(r"(?i)Policy\s*Number\s*[:]?\s*([A-Z0-9]{10,})", pdf_text)
    if m:
        data["policy_number"] = m.group(1).strip()

    m = re.search(r"(?i)premium\s*of\s*Rs\.?\s*([\d,]+)", pdf_text) or re.search(r"(?i)Total\s*Premium[^\d]*([\d,]+)", pdf_text)
    if m:
        data["premium"] = clean_amount(m.group(1))

    m = re.search(r"(?i)(?:Base\s*)?Sum\s*Insured[\s\S]{1,100}?\s([1-9][0-9]{5,6})", pdf_text) or re.search(r"(?i)([1-9][0-9]{5,6})\s+25000", pdf_text)
    if m:
        data["sum_insured"] = clean_amount(m.group(1))

    m = re.search(r"(?i)(?:Start\s*Date|From)[\s:a-z0-9]*?(\d{2}-[A-Za-z]{3}-\d{4})", pdf_text)
    if m:
        data["start_dt"] = parse_any_date(m.group(1))

    m = re.search(r"(?i)(?:End\s*Date|To)[\s:a-z0-9]*?(\d{2}-[A-Za-z]{3}-\d{4})", pdf_text)
    if m:
        data["end_dt"] = parse_any_date(m.group(1))

    m = (
        re.search(r"(?i)(?:Ltd\.?|Co\.?|Company|Limited|Insurance)[\s\r\n]+([A-Z0-9\-\r\n]{8,})[\s\r\n]+MEDICLAIM", pdf_text)
        or re.search(r"(?i)Previous\s*Policy\s*Number[\s\S]{1,300}?(?:Ltd\.?|Co\.?|Company|Limited|Insurance)[\s\r\n]+([A-Z0-9\-\r\n]{8,})", pdf_text)
    )
    if m:
        pyp = re.sub(r"(?i)\b(Company|Limited|Insurance|Ltd|Co|MEDICLAIM|Previous\s*Policy\s*Number)\b[\.]?", "", m.group(1))
        data["pyp_number"] = re.sub(r"[\r\n\s]+", "", pyp)

    return data
