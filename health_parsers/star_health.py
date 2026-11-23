import re
from .common import default_extracted_data, clean_person_name, clean_amount, parse_any_date


def parse(pdf_text: str) -> dict:
    data = default_extracted_data()

    if re.search(r"(?i)Medi Classic", pdf_text):
        data["plan_name"], data["sub_type"] = "MEDI CLASSIC", "MEDICLAIM"
    elif re.search(r"(?i)Health Assure", pdf_text):
        data["plan_name"], data["sub_type"] = "HEALTH ASSURE", "MEDICLAIM"
    elif re.search(r"(?i)Star Hospital Cash", pdf_text):
        data["plan_name"], data["sub_type"] = "HOSPITAL CASH", "MEDICLAIM"
    elif re.search(r"(?i)Family Health Optima", pdf_text):
        data["plan_name"], data["sub_type"] = "FAMILY HEALTH OPTIMA", "MEDICLAIM"
    elif re.search(r"(?i)Star Comprehensive", pdf_text):
        data["plan_name"], data["sub_type"] = "STAR COMPREHENSIVE", "MEDICLAIM"
    elif re.search(r"(?i)Star Women Care", pdf_text):
        data["plan_name"], data["sub_type"] = "STAR WOMEN CARE", "MEDICLAIM"
    elif re.search(r"(?i)Super Surplus", pdf_text):
        data["plan_name"], data["sub_type"] = "STAR SUPER SURPLUS", "TOP UP"
    elif re.search(r"(?i)Super Star", pdf_text):
        data["plan_name"], data["sub_type"] = "SUPER STAR", "MEDICLAIM"
    elif re.search(r"(?i)(?:Critical Illness MultiPay|Star Critical Illness)", pdf_text):
        data["plan_name"], data["sub_type"] = "STAR CRITICAL ILLNESS", "MEDICLAIM"
    elif re.search(r"(?i)Arogya Sanjeevani", pdf_text):
        data["plan_name"], data["sub_type"] = "AROGYA SANJEEVANI", "MEDICLAIM"
    elif re.search(r"(?i)Family Accident Care", pdf_text):
        data["plan_name"], data["sub_type"] = "FAMILY ACCIDENT CARE", "PERSONAL ACCIDENT"
    elif re.search(r"(?i)(?:Senior Citizens Red Carpet|Red Carpet)", pdf_text):
        data["plan_name"], data["sub_type"] = "SENIOR CITIZENS RED CARPET", "MEDICLAIM"

    m = re.search(r"(?i)Customer Name\s*:\s*([^\r\n]+(?:\s*[\r\n]+(?![^\r\n]*(?::|\d))[^\r\n]+)?)", pdf_text)
    if m:
        raw_name = re.sub(r"\d.*$", "", m.group(1), flags=re.S).replace(".", " ")
        data["client_name"] = clean_person_name(raw_name)

    m = re.search(r"(?i)(?:Policy No|Certificate No)[^\d]{0,15}(\d{15,20})", pdf_text)
    if m:
        data["policy_number"] = m.group(1).strip()

    m = re.search(r"(?i)Total Premium\s*:\s*(?:Rs\.?|₹)?\s*([\d,]+)", pdf_text)
    if m:
        data["premium"] = clean_amount(m.group(1))

    si_match = (
        re.search(r"(?i)(?:Sum Insured|Basic Floater Sum Insured|Basic Sum Insured(?:\s*\(Health\))?)\s*(?:\(Rs\.\)|:)?\s*(?:Rs\.?)?\s*([1-9][\d,\r\n]{4,15})", pdf_text)
        or re.search(r"(?i)(?:Male|Female)\s+(?:\d{2}-[A-Za-z]{3}-\d{4}\s+)?\d{1,3}\s+([1-9][\d,\r\n]{4,15})", pdf_text)
        or re.search(r"(?i)(?:Male|Female)[\s\S]{1,150}?\s([1-9][\d,\r\n]{4,15})\s+[A-Za-z]", pdf_text)
    )
    if si_match:
        cleaned_si_block = re.sub(r"[\r\n]+", "", si_match.group(1))
        m_num = re.search(r"[1-9]\d{0,2}(?:,\d{2,3})+", cleaned_si_block) or re.search(r"[1-9]\d{4,8}", cleaned_si_block)
        if m_num:
            data["sum_insured"] = clean_amount(m_num.group(0))
    if not data["sum_insured"]:
        m_hc = re.search(r"(?i)Hospital Cash Amount[^0-9]+([1-9][\d,]+)", pdf_text)
        if m_hc:
            data["sum_insured"] = clean_amount(m_hc.group(1))

    m = re.search(r"(?i)From\s*:\s*(\d{2}-[A-Za-z]{3}-\d{4}|\d{2}/\d{2}/\d{4})", pdf_text)
    if m:
        data["start_dt"] = parse_any_date(m.group(1))

    m = re.search(r"(?i)To\s*:\s*(?:Midnight Of\s*)?(\d{2}-[A-Za-z]{3}-\d{4}|\d{2}/\d{2}/\d{4})", pdf_text)
    if m:
        data["end_dt"] = parse_any_date(m.group(1))

    m = re.search(r"(?i)(?:Previous Policy\s*No|Previous Certificate\s*No|renewal premium of policy number)[^\d]{0,15}(\d{10,25})", pdf_text)
    if m:
        data["pyp_number"] = m.group(1).strip()

    return data
