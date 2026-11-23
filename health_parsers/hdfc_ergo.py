import re
from .common import default_extracted_data, clean_person_name, clean_amount, parse_any_date


def parse(pdf_text: str) -> dict:
    data = default_extracted_data()

    is_my_optima = bool(re.search(r"(?i)my:\s*Optima Secure", pdf_text))
    m_plan = re.search(
        r"(?i)(?:my:\s*Optima Secure\s*[-–]\s*|Insured Person.?s Details and Sum Insured\s*[-–]\s*|Arogya Sanjeevani Policy,\s*)(Optima Secure[\s+]*|Optima Super Secure|HDFC ERGO)",
        pdf_text
    )
    temp_plan = m_plan.group(0) if m_plan else ""

    if "+" in temp_plan:
        data["plan_name"], data["sub_type"] = "OPTIMA SECURE +", "MEDICLAIM"
    elif re.search(r"(?i)Super", temp_plan) or re.search(r"(?i)Optima Super Secure", pdf_text):
        data["plan_name"], data["sub_type"] = "OSS", "MEDICLAIM"
    elif re.search(r"(?i)Arogya Sanjeevani", pdf_text):
        data["plan_name"], data["sub_type"] = "AROGYA SANJEEVANI", "MEDICLAIM"
    elif re.search(r"(?i)Optima Secure", pdf_text):
        data["plan_name"], data["sub_type"] = "OS", "MEDICLAIM"
    elif re.search(r"(?i)Optima Restore", pdf_text):
        data["plan_name"], data["sub_type"] = "OPTIMA RESTORE INDIVIDUAL", "MEDICLAIM"
    elif re.search(r"(?i)Energy \(Silver\)", pdf_text):
        data["plan_name"], data["sub_type"] = "ENERGY (SILVER)", "MEDICLAIM"
    elif re.search(r"(?i)SARV SURAKSHA PLUS \(GROUP\)", pdf_text):
        data["plan_name"], data["sub_type"] = "SARV SURAKSHA PLUS (GROUP)", "MEDICLAIM"
    elif re.search(r"(?i)Koti Suraksha", pdf_text):
        data["plan_name"], data["sub_type"] = "KOTI SURAKSHA", "PERSONAL ACCIDENT"
    elif re.search(r"(?i)(?:Product/Policy Individual Personal Accident|Individual Personal Accident)", pdf_text):
        data["plan_name"], data["sub_type"] = "PERSONAL ACCIDENT", "PERSONAL ACCIDENT"

    if data["plan_name"] == "SARV SURAKSHA PLUS (GROUP)":
        m = re.search(r"(?i)(?<=Name & Address of the Policyholder\s)[^\r\n]+", pdf_text)
        if m:
            data["client_name"] = clean_person_name(m.group(0))
    else:
        m = re.search(r"(?i)(?:Proposer Name\s*:\s*|Dear\s+)([^\r\n,]+)", pdf_text)
        if m:
            data["client_name"] = clean_person_name(m.group(1))

    m = re.search(r"\b(\d{15,20})\b", pdf_text)
    if m:
        data["policy_number"] = f",{m.group(1)}"

    if is_my_optima:
        m = (
            re.search(r"(?i)received\s*an\s*amount\s*of[^0-9]*([0-9,]{4,})", pdf_text)
            or re.search(r"(?i)(?:Total Premium|Net Premium|Amount Payable)[^\d]{1,30}([0-9][0-9,]{2,}(?:\.\d{1,2})?)", pdf_text)
        )
    else:
        m = (
            re.search(r"(?i)Gross Premium[^\d]{1,30}([0-9][0-9,]{2,}(?:\.\d{1,2})?)", pdf_text)
            or re.search(r"(?i)(?:Total Premium|Net Premium|Amount Payable)[^\d]{1,30}([0-9][0-9,]{2,}(?:\.\d{1,2})?)", pdf_text)
        )
    if m:
        data["premium"] = clean_amount(m.group(1))

    m = (
        re.search(r"(?i)(?:Base Sum Insured\s*per\s*Insured\s*Person[^\d]{0,40}|Sum Insured opted\s*:[^\d]{0,10}|Base Sum Insured[^\d]{0,20}|Total Sum Insured[^\d]{0,20})([1-9][0-9, ]{4,})", pdf_text)
        or re.search(r"(?i)(?:Sum Insured opted[\s:]*|1[\s\.\-]*Accidental Death[^\d]{0,20})([1-9][0-9,]{4,})", pdf_text)
        or re.search(r"(?i)Base\s*Sum\s*Insured[\s\S]{1,500}?\b\d{2}[/-]\d{2}[/-]\d{4}\s+([1-9][0-9,]{4,8})\b", pdf_text)
    )
    if m:
        data["sum_insured"] = clean_amount(m.group(1))

    if data["plan_name"] == "SARV SURAKSHA PLUS (GROUP)":
        m = re.search(r"(?i)From\s*00:01\s*hours:\s*([A-Za-z]+\s*\d{1,2},\s*\d{4})", pdf_text)
        if m:
            data["start_dt"] = parse_any_date(m.group(1))
        m = re.search(r"(?i)To\s*\(Midnight\)\s*:\s*([A-Za-z]+\s*\d{1,2},\s*\d{4})", pdf_text)
        if m:
            data["end_dt"] = parse_any_date(m.group(1))
    else:
        m = re.search(r"(?i)From\s*(?:\d{2}:\d{2}\s*hrs\s*on\s*)?(\d{2}[/-]\d{2}[/-]\d{4})", pdf_text)
        if m:
            data["start_dt"] = parse_any_date(m.group(1))
        m = re.search(r"(?i)To\s*(?:\d{2}:\d{2}\s*hrs\s*on\s*)?(\d{2}[/-]\d{2}[/-]\d{4})", pdf_text)
        if m:
            data["end_dt"] = parse_any_date(m.group(1))

    m = re.search(r"(?i)Previous Policy[\s:]*(\d{6,})", pdf_text)
    if m:
        data["pyp_number"] = f",{m.group(1).strip()}"

    return data
