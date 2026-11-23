import re
from .common import default_extracted_data, clean_person_name, clean_amount, parse_any_date


def parse(pdf_text: str) -> dict:
    data = default_extracted_data()
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
    if m:
        data["client_name"] = clean_person_name(m.group(1))

    m = re.search(r"(?i)Policy Number\s*[:]?\s*(\d{2}-\d{2}-\d{7}-\d{2})", pdf_text)
    if m:
        data["policy_number"] = m.group(1).strip()

    m = (
        re.search(r"(?i)receipt of premium amount of INR\s*([\d,\.]+)", pdf_text)
        or re.search(r"(?i)(?:Gross|Total)\s*Premium[^\d]{1,20}([\d,\.]+)", pdf_text)
    )
    if m:
        data["premium"] = clean_amount(m.group(1))

    m = (
        re.search(r"(?i)\b([1-9]\d{4,8})\s*[\r\n]*\s*(?:30\s*Days|Zone\s*[IV]*)", pdf_text)
        or re.search(r"(?i)Sum Insured[^\d]{1,30}([1-9][\d,]{4,})", pdf_text)
    )
    if m:
        data["sum_insured"] = clean_amount(m.group(1))

    m = re.search(r"(?i)Start Date of Policy & Time.*?on\s*(\d{2}/\d{2}/\d{4})", pdf_text)
    if m:
        data["start_dt"] = parse_any_date(m.group(1))

    m = re.search(r"(?i)Expiry Date & Time of Policy.*?on\s*(\d{2}/\d{2}/\d{4})", pdf_text)
    if m:
        data["end_dt"] = parse_any_date(m.group(1))

    m = re.search(r"(?i)Previous Policy Number\s*[:]?\s*(\d{2}-\d{2}-\d{7}-\d{2})", pdf_text)
    if m:
        data["pyp_number"] = m.group(1).strip()

    return data
