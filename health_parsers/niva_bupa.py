import re
from .common import default_extracted_data, clean_person_name, clean_amount, parse_any_date


def parse(pdf_text: str) -> dict:
    data = default_extracted_data()

    m = re.search(r"(?i)Product Name\s*:\s*(ReAssure 3\.0|ReAssure 2\.0|ReAssure|Health Companion|Health Recharge|Aspire)", pdf_text)
    if m:
        data["plan_name"] = m.group(1).strip().upper()
        data["sub_type"] = "TOP UP" if data["plan_name"] == "HEALTH RECHARGE" else "MEDICLAIM"

    m = re.search(r"(?i)Policyholder Name\s*[:]?\s*([\s\S]{1,100}?)(?=\s*Policyholder Address)", pdf_text)
    if m:
        data["client_name"] = clean_person_name(m.group(1))

    m = re.search(r"(?i)Policy Number\s*[:]?\s*([0-9]{10,})", pdf_text)
    if m:
        data["policy_number"] = m.group(1).strip()

    m = re.search(r"(?i)Gross Premium[^\d]*([\d,]+)", pdf_text)
    if m:
        data["premium"] = clean_amount(m.group(1))

    m = re.search(r"(?i)(?:Base\s*)?Sum Insured[\s]*(?:INR|\(in Rs\.?\)|\(Rs\.?\)|in Rs|Rs\.?)?\s*([\d,]{4,}|Unlimited)", pdf_text)
    if m:
        data["sum_insured"] = clean_amount(m.group(1)).upper()

    m = re.search(r"(?i)From\s*(\d{2}[/-][A-Za-z0-9]{2,3}[/-]\d{4})", pdf_text)
    if m:
        data["start_dt"] = parse_any_date(m.group(1))

    m = re.search(r"(?i)To\s*(\d{2}[/-][A-Za-z0-9]{2,3}[/-]\d{4})", pdf_text)
    if m:
        data["end_dt"] = parse_any_date(m.group(1))

    return data
