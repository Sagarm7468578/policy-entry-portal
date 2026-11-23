import re
from .common import default_extracted_data, clean_person_name, clean_amount, parse_any_date


def parse(pdf_text: str) -> dict:
    data = default_extracted_data()

    if re.search(r"(?i)INDIVIDUAL HEALTH INSURANCE", pdf_text):
        data["plan_name"], data["sub_type"] = "INDIVIDUAL HEALTH", "MEDICLAIM"

    m = re.search(r"(?i)Policyholder Name\s*:\s*([^\r\n]+)", pdf_text)
    if m:
        data["client_name"] = clean_person_name(m.group(1))

    m = re.search(r"(?i)Policy No\.?\s*:\s*([0-9]+[A-Za-z][0-9]+)", pdf_text)
    if m:
        data["policy_number"] = m.group(1).strip()

    m = re.search(r"(?im)^Total\s*:\s*([\d,]+)", pdf_text) or re.search(r"(?i)Premium\s*:\s*([\d,]+)", pdf_text)
    if m:
        data["premium"] = clean_amount(m.group(1))

    m = (
        re.search(r"(?i)SUMMARY OF COVERAGE[\s\S]{1,150}?(?:Gold|Platinum|Silver|Standard|Base)?\s*([1-9][\d,]+)\.\d{2}", pdf_text)
        or re.search(r"(?i)Sum Insured(?:\([^\)]*\))?[\s\r\n]+[A-Za-z\s]+([1-9][\d,]{4,})", pdf_text)
    )
    if m:
        data["sum_insured"] = clean_amount(m.group(1))

    m = re.search(r"(?i)Period of Insurance\s*:\s*From[\s\S]{1,50}?(\d{2}/\d{2}/\d{4})", pdf_text)
    if m:
        data["start_dt"] = parse_any_date(m.group(1))

    m = re.search(r"(?i)To\s*(?:Midnight\s*on\s*)?(\d{2}/\d{2}/\d{4})", pdf_text)
    if m:
        data["end_dt"] = parse_any_date(m.group(1))

    m = re.search(r"(?i)Previous Policy No\.?\s*:\s*([0-9]+[A-Za-z][0-9]+)", pdf_text)
    if m:
        data["pyp_number"] = m.group(1).strip()

    return data
