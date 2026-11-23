import re
from .common import default_extracted_data, clean_person_name, clean_amount, parse_any_date


def parse(pdf_text: str) -> dict:
    data = default_extracted_data()

    if re.search(r"(?i)Travel Insurance", pdf_text):
        data["plan_name"], data["sub_type"] = "TRAVEL", "TRAVEL INSURANCE"

    m = re.search(r"(?i)(?:Policy\s*Holder\s*Name|Policyholder\s*name)\s*[:]?\s*([^\r\n]+)", pdf_text)
    if m:
        name = re.sub(r"(?i)\s*Policy Number.*", "", m.group(1))
        data["client_name"] = clean_person_name(name)

    m = re.search(r"(?i)Policy\s*(?:No\.?|Number)\s*[:]?\s*(\d+)", pdf_text)
    if m:
        data["policy_number"] = m.group(1).strip()

    m = re.search(r"(?i)(?:Total Premium|Final Premium \(post-tax\)|Total Amount \(in INR\)|Total Amount Payable|Final Premium)\s*[:]?\s*(?:Rs\.?|INR)?\s*([0-9][\d,\.]+)", pdf_text)
    if m:
        data["premium"] = clean_amount(m.group(1))

    m = (
        re.search(r"(?i)Personal Accident in India[^0-9]*([1-9][\d,]+)", pdf_text)
        or re.search(r"(?i)(?:Accident & Sickness Medical Expenses|Medical Expenses- Injury and / or Illness).*?(?:\$|USD)\s*([1-9][\d,]+)", pdf_text)
    )
    if m:
        data["sum_insured"] = clean_amount(m.group(1))

    m = re.search(r"(?i)(?:From|Policy Period Start Date)\s*[:]?\s*(\d{2}/\d{2}/\d{4})", pdf_text)
    if m:
        data["start_dt"] = parse_any_date(m.group(1))

    m = re.search(r"(?i)(?:To|Policy Period End Date)\s*[:]?\s*(\d{2}/\d{2}/\d{4})", pdf_text)
    if m:
        data["end_dt"] = parse_any_date(m.group(1))

    return data
