import re
from .common import default_extracted_data, clean_person_name, clean_amount, parse_any_date


def parse(pdf_text: str) -> dict:
    data = default_extracted_data()

    if re.search(r"(?i)Group Health \(Floater\)", pdf_text):
        data["plan_name"], data["sub_type"] = "GROUP HEALTH", "MEDICLAIM"

    m = re.search(r"(?i)(?:Name of the Insured|Insured Name|Policyholder Name)\s*:\s*([^\r\n]+)", pdf_text)
    if m:
        data["client_name"] = clean_person_name(m.group(1))

    m = (
        re.search(r"\b(\d{4}/[A-Z0-9]+/\d{5,}/\d+/\d+)\b", pdf_text)
        or re.search(r"(?i)Policy\s*(?:Number|No\.?)\s*[:\-]\s*([0-9]{10,}(?:\s+[0-9]+)?|[0-9]{4}/[A-Z0-9]+/[0-9/]+)", pdf_text)
    )
    if m:
        data["policy_number"] = re.sub(r"\s+", "", m.group(1))

    m = re.search(r"(?i)(?:Basic Premium|Total Premium)\s*:\s*[`₹Rs\.\s]*([\d,]+)", pdf_text)
    if m:
        data["premium"] = clean_amount(m.group(1))

    m = (
        re.search(r"(?i)Total Lives Insured[\s\S]{1,60}?Sum Insured\s*:\s*[`₹Rs\.\s]*([\d,]+)", pdf_text)
        or re.search(r"(?i)Sum Insured\s*:\s*[`₹Rs\.\s]*([\d,]{5,})", pdf_text)
    )
    if m:
        data["sum_insured"] = clean_amount(m.group(1))

    m = re.search(r"(?i)Period\s*of\s*Insurance[\s\S]{1,60}?From:?\s*(?:00:00\s*Hours\s*of\s*)?([A-Za-z]{3}\s+\d{1,2}[,\s]+\d{4}|\d{2}[-/]\d{2}[-/]\d{4}|\d{2}[-/][A-Za-z]{3}[-/]\d{4})", pdf_text)
    if m:
        data["start_dt"] = parse_any_date(m.group(1))

    m = re.search(r"(?i)To\s*(?:Midnight\s*)?([A-Za-z]{3}\s+\d{1,2}[,\s]+\d{4}|\d{2}[-/]\d{2}[-/]\d{4}|\d{2}[-/][A-Za-z]{3}[-/]\d{4})", pdf_text)
    if m:
        data["end_dt"] = parse_any_date(m.group(1))

    return data
