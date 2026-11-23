import re
from .common import default_extracted_data, clean_person_name, clean_amount, parse_any_date


def parse(pdf_text: str) -> dict:
    data = default_extracted_data()

    if re.search(r"(?i)PERSONAL ACCIDENT", pdf_text):
        data["plan_name"], data["sub_type"] = "PERSONAL ACCIDENT", "PERSONAL ACCIDENT"
    elif re.search(r"(?i)Family Health Protector", pdf_text):
        data["plan_name"], data["sub_type"] = "FHP", "MEDICLAIM"

    if data["plan_name"] == "FHP":
        m = re.search(r"(?i)Proposer Name\s+([A-Za-z][A-Za-z\s]+?)(?=\s+Address|\s+Gstin|\s+Contact|\s+Tax|\s+Policy|\n|$)", pdf_text)
    else:
        m = (
            re.search(r"(?i)Insured.*?Name\s*[:;]?[\s\r\n]*([A-Za-z\s]+)", pdf_text)
            or re.search(r'(?im)^"?([A-Za-z\s]+?)"?[\s,]+\d{1,2}[\s,]+Self\b', pdf_text)
        )
    if m:
        name = re.sub(r"(?i)IFFCO-TOKIO\s*", "", m.group(1))
        data["client_name"] = clean_person_name(name)

    m = re.search(r"(?i)Policy\s*(?:#|No)[^\da-z]*([A-Z0-9\-]*\d[A-Z0-9\-]*)", pdf_text)
    if m:
        data["policy_number"] = m.group(1).strip()

    m = re.search(r"(?i)(?:received an amount of|Gross Premium Payable|Invoice Value)[^\d]*([\d,\.]+)", pdf_text)
    if m:
        data["premium"] = clean_amount(m.group(1))

    m = re.search(r"(?i)(?:Basic Sum Insured For Family|Total Floater Sum Insured|DEATH)[\s\r\n]*([1-9][\d,]+)", pdf_text)
    if m:
        data["sum_insured"] = clean_amount(m.group(1))

    m = re.search(r"(?i)From\s*(?:0001\s*hrs\s*on\s*:?\s*)?(\d{2}/\d{2}/\d{4})", pdf_text)
    if m:
        data["start_dt"] = parse_any_date(m.group(1))

    m = re.search(r"(?i)Midnight\s*on\s*(\d{2}/\d{2}/\d{4})", pdf_text)
    if m:
        data["end_dt"] = parse_any_date(m.group(1))

    m = re.search(r"(?i)LTD\s+([A-Z0-9]{6,})\s+\d{2}/\d{2}/\d{4}", pdf_text)
    if m:
        data["pyp_number"] = m.group(1).strip()

    return data
