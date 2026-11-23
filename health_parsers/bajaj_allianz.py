import re
from .common import default_extracted_data, clean_person_name, clean_amount, parse_any_date


def parse(pdf_text: str) -> dict:
    data = default_extracted_data()

    if re.search(r"(?i)INDIVIDUAL TRAVEL", pdf_text):
        data["plan_name"], data["sub_type"] = "TRAVEL", "TRAVEL INSURANCE"

    m = re.search(r"(?i)Dear\s+(?!Customer)([^,\r\n]+)", pdf_text) or re.search(r"(?i)Proposer Name\s*:\s*([^\r\n]+)", pdf_text)
    if m:
        data["client_name"] = clean_person_name(m.group(1))

    m = re.search(r"(?i)Policy No\.\s*([\d\-]+)", pdf_text)
    if m:
        data["policy_number"] = m.group(1).strip()

    m = re.search(r"(?i)Total Premium\s*(?:Rs\.?)?\s*([0-9][\d,\.]+)", pdf_text)
    if m:
        data["premium"] = clean_amount(m.group(1))

    m = re.search(r"(?i)(?:Medical Expenses[\s\S]{1,60}?|Platinum\s*)(?:USD|\$)\s*([1-9][\d,]+)", pdf_text)
    if m:
        data["sum_insured"] = clean_amount(m.group(1))

    m = re.search(r"(?i)From\s*:\s*(\d{2}/\d{2}/\d{4})", pdf_text)
    if m:
        data["start_dt"] = parse_any_date(m.group(1))

    m = re.search(r"(?i)To\s*:\s*(\d{2}/\d{2}/\d{4})", pdf_text)
    if m:
        data["end_dt"] = parse_any_date(m.group(1))

    m = re.search(r"(?i)Previous Policy No[\s:]*([0-9][A-Z0-9\-]{5,})", pdf_text)
    if m:
        data["pyp_number"] = m.group(1).strip()

    return data
