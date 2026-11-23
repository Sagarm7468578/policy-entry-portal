import re
from .common import default_extracted_data, clean_person_name, clean_amount, parse_any_date


def parse(pdf_text: str) -> dict:
    data = default_extracted_data()

    if re.search(r"(?i)HAPPY FAMILY FLOATER", pdf_text):
        data["plan_name"], data["sub_type"] = "HAPPY FAMILY FLOATER", "MEDICLAIM"

    m = re.search(r"(?i)Insured Name[\s\r\n:]*([A-Za-z\.\s]+)", pdf_text)
    if m:
        data["client_name"] = clean_person_name(m.group(1))

    m = re.search(r"(?i)forming part of policy number[\s\r\n]*([0-9/]{10,})", pdf_text) or re.search(r"(?i)Policy No\.?[\s\r\n]*([0-9/]{10,})", pdf_text)
    if m:
        data["policy_number"] = m.group(1).strip()

    m = re.search(r"(?i)(?:Gross Premium|Total Premium in words)[\s\S]{1,100}?Total\s*:\s*([\d,]+)", pdf_text)
    if m:
        data["premium"] = clean_amount(m.group(1))

    m = re.search(r"(?i)Plan Sum Insured\s*:\s*([\d,]+)", pdf_text)
    if m:
        data["sum_insured"] = clean_amount(m.group(1))

    m = re.search(r"(?i)FROM\s*[\d:]+\s*ON\s*(\d{2}/\d{2}/\d{4})", pdf_text)
    if m:
        data["start_dt"] = parse_any_date(m.group(1))

    m = re.search(r"(?i)TO\s*MIDNIGHT\s*OF\s*(\d{2}/\d{2}/\d{4})", pdf_text)
    if m:
        data["end_dt"] = parse_any_date(m.group(1))

    m = re.search(r"(?i)Prev\.?\s*Policy\s*No\.?\s*:\s*([0-9/]+)", pdf_text)
    if m:
        data["pyp_number"] = m.group(1).strip()

    return data
