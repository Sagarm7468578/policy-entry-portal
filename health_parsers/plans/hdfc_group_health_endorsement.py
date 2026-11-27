import re
from health_parsers.common import (
    default_extracted_data,
    parse_any_date,
    clean_amount,
    clean_person_name,
)


def is_hdfc_group_health_endorsement(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)HDFC\s+ERGO\s+Group\s+Health\s+Insurance", pdf_text)
        and re.search(r"(?i)Endorsement\s+(?:Form|Number)", pdf_text)
    )


def parse_hdfc_group_health_endorsement(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "GROUP HEALTH ENDORSEMENT"
    data["sub_type"] = "MEDICLAIM"

    m_end = re.search(r"(?i)Endorsement\s*Number\s*[\r\n]+\s*(?:Date\s*of\s*Issue\s*[\r\n]+\s*)?(\d{15,22})\b", pdf_text)
    if not m_end:
        m_end = re.search(r"(?i)Endorsement\s*Number\s*[:\-]\s*(\d{15,22})\b", pdf_text)
    if m_end:
        data["policy_number"] = m_end.group(1).strip()

    m_base = re.search(r"(?i)Policy\s*No\.?\s*[:\-]?\s*(\d{15,22})\b", pdf_text)
    if m_base:
        data["pyp_number"] = m_base.group(1).strip()
        if not data["policy_number"]:
            data["policy_number"] = m_base.group(1).strip()

    m_nm = re.search(r"(?i)Policy\s*Holder\s*[:\-]\s*[\r\n\s]*([^\r\n]{3,90})", pdf_text)
    if m_nm:
        data["client_name"] = clean_person_name(m_nm.group(1))

    date_tok = r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})"
    m_exp = re.search(rf"(?i)To\s*Date\s*and\s*Time\s*[\r\n\s]*{date_tok}", pdf_text)
    if m_exp:
        data["end_dt"] = parse_any_date(m_exp.group(1))

    m_iss = re.search(rf"(?i)Contact\s*No\s*[\r\n\s]*{date_tok}", pdf_text)
    if not m_iss:
        m_iss = re.search(rf"(?i)Date\s*of\s*Issue\s*[:\-]?\s*[\r\n\s]*{date_tok}", pdf_text)
    if m_iss:
        data["start_dt"] = parse_any_date(m_iss.group(1))

    m_si = re.search(r"(?i)Total\s*No\.\s*of\s*[\r\n\s]*Employees\s*[\r\n]+\s*([\d,]{5,12})\b", pdf_text)
    if not m_si:
        m_si = re.search(r"(?i)Self\s*[\r\n]+\s*\d{1,3}\s*[\r\n]+\s*([\d,]{5,12})\b", pdf_text)
    if m_si:
        data["sum_insured"] = clean_amount(m_si.group(1))

    m_p = re.search(r"(?i)premium\s+amounting\s+to\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)", pdf_text)
    if m_p:
        amt = clean_amount(m_p.group(1))
        data["premium"] = f"-{amt}" if re.search(r"(?i)hereby\s+refunded", pdf_text) else amt

    data["agency"] = "FILL MANUAL"
    data["premium_mode"] = "FILL MANUAL"
    data["dob"] = "GROUP POLICY"
    return data
