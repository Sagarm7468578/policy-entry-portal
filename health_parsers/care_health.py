import re
from .common import default_extracted_data, clean_person_name, clean_amount, parse_any_date


def parse(pdf_text: str) -> dict:
    data = default_extracted_data()

    if re.search(r"(?i)CARE SUPREME", pdf_text):
        data["plan_name"], data["sub_type"] = "CARE SUPREME", "MEDICLAIM"

    m = re.search(r"(?i)Dear\s+([^\r\n,]+)", pdf_text)
    if m:
        data["client_name"] = clean_person_name(m.group(1))

    m = re.search(r"(?i)Policy No[\.\:]*\s*([A-Z0-9]{8,})", pdf_text)
    if m:
        data["policy_number"] = m.group(1).strip()

    m = re.search(r"(?i)Premium Paid\s*Rs\.?\s*([\d,]+)", pdf_text) or re.search(r"(?im)^Total\s*([\d,]+)", pdf_text)
    if m:
        data["premium"] = clean_amount(m.group(1))

    m = re.search(r"(?i)(?:1\s*)?Sum Insured\s*([1-9][0-9,]*000)", pdf_text)
    if m:
        data["sum_insured"] = clean_amount(m.group(1))

    m = re.search(r"(?i)Start Date[\s\S]{1,30}?(\d{2}-[A-Za-z]{3}-\d{4})", pdf_text)
    if m:
        data["start_dt"] = parse_any_date(m.group(1))

    m = re.search(r"(?i)End Date[\s\S]{1,30}?(\d{2}-[A-Za-z]{3}-\d{4})", pdf_text)
    if m:
        data["end_dt"] = parse_any_date(m.group(1))

    m = re.search(r"(?i)Previous\s*Policy\s*Number[\s\S]{1,400}?\b([0-9]{8,})\b", pdf_text)
    if m:
        data["pyp_number"] = m.group(1).strip()

    return data
