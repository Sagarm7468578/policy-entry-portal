import re
from .common import default_extracted_data, clean_person_name, clean_amount, parse_any_date


def parse(pdf_text: str) -> dict:
    data = default_extracted_data()

    if re.search(r"(?i)National Senior Citizen", pdf_text):
        data["plan_name"], data["sub_type"] = "SENIOR CITIZEN", "MEDICLAIM"
    elif re.search(r"(?i)Personal Accident", pdf_text):
        data["plan_name"], data["sub_type"] = "PERSONAL ACCIDENT", "PERSONAL ACCIDENT"
    elif re.search(r"(?i)Parivar Mediclaim", pdf_text):
        data["plan_name"], data["sub_type"] = "PARIVAR MEDICLAIM", "MEDICLAIM"
    elif re.search(r"(?i)National Mediclaim", pdf_text):
        data["plan_name"], data["sub_type"] = "MEDICLAIM", "MEDICLAIM"

    m = (
        re.search(r"(?i)Customer Name\s*:\s*(?:MR\.|MRS\.|MS\.|MR|MRS|MS|_)?\s*([A-Za-z\s]+?)\s*गाहक", pdf_text)
        or re.search(r"(?i)Customer Name\s*:\s*([^\r\n]+)", pdf_text)
    )
    if m:
        name = re.sub(r"\s*गाहक.*", "", m.group(1))
        data["client_name"] = clean_person_name(name)

    m = re.search(r"(?i)Policy Number[^\d]{1,20}(\d{15,20})", pdf_text)
    if m:
        data["policy_number"] = m.group(1).strip()

    m = re.search(r"(?i)Total Amount\s*[`₹Rs\.\s]*([\d,]+)", pdf_text)
    if m:
        data["premium"] = clean_amount(m.group(1))

    si_patterns = [
        r"(?i)24 Hours Coverage[^\d]{1,20}([1-9](?:\d{4,9}|\d{0,2}(?:,\d{2,3})+))",
        r"(?i)Basic Cover Sum\s*Insured[^\d]{1,20}([1-9](?:\d{4,9}|\d{0,2}(?:,\d{2,3})+))",
        r"(?i)\b(?:Male|Female|M|F)\s+([1-9](?:\d{4,9}|\d{0,2}(?:,\d{2,3})+))",
        r"(?i)Capital Sum Insured[^\d]{1,30}([1-9](?:\d{4,9}|\d{0,2}(?:,\d{2,3})+))",
    ]
    for pat in si_patterns:
        m = re.search(pat, pdf_text)
        if m:
            data["sum_insured"] = clean_amount(m.group(1))
            break

    m = re.search(r"(?i)Policy Effective from.*?on\s*(\d{2}/\d{2}/\d{4})", pdf_text)
    if m:
        data["start_dt"] = parse_any_date(m.group(1))

    m = re.search(r"(?i)to\s*midnight\s*of\s*(\d{2}/\d{2}/\d{4})", pdf_text)
    if m:
        data["end_dt"] = parse_any_date(m.group(1))

    m_blk = re.search(r"(?i)Previous Policy Number[\s\S]{1,600}?(?:\(|\*सरकारी)", pdf_text)
    if m_blk:
        m_pyp = re.search(r"(\d{15,20})[^\n\r]*[\r\n]+\s*(?:\(|\*सरकारी)", m_blk.group(0))
        if m_pyp:
            data["pyp_number"] = m_pyp.group(1).strip()
        else:
            all_pyps = re.findall(r"\b\d{15,20}\b", m_blk.group(0))
            if all_pyps:
                data["pyp_number"] = all_pyps[-1]

    return data
