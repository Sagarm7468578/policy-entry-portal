import re
from health_parsers.common import (
    default_extracted_data,
    parse_any_date,
    fmt_date,
    clean_amount,
    clean_person_name,
    extract_premium_mode,
)


def is_aditya_birla_activ_one(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)Product\s*Name\s*[:\-]?\s*[\r\n\s]*Activ\s+One", pdf_text)
        or re.search(r"(?i)ADIHLIP24097V", pdf_text)
        or re.search(r"(?i)Activ\s+One\s*[-–]?\s*(?:MAX|NXT|VYTL|SAVR|VIP)", pdf_text)
    )


def parse_aditya_birla_activ_one(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "ACTIV ONE"
    data["sub_type"] = "MEDICLAIM"

    m_pol = re.search(r"(?i)Policy\s*Number\s*[:\-]?\s*[\r\n\s]*([A-Z0-9\-]{10,25})", pdf_text)
    if m_pol:
        data["policy_number"] = m_pol.group(1).strip()

    for pat in [
        r"(?i)Policyholder\s*Name\s*[\r\n]+\s*([^\r\n]{3,80})",
        r"(?i)Proposer\s*Name\s*[:\-]?\s*[\r\n]+\s*([^\r\n]{3,80})",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1))
            if cand and len(cand) >= 3:
                data["client_name"] = cand
                break

    m_ag = re.search(r"(?i)Intermediary\s*Name\s*[\r\n]+\s*([^\r\n]{3,70})", pdf_text)
    if m_ag:
        data["agency"] = clean_person_name(m_ag.group(1))

    date_tok = r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})"
    for pat in [
        rf"(?i)Start\s*Date\s*of\s*Policy\s*&\s*Time[\s\S]{{0,50}}?{date_tok}",
        rf"(?i)Policy\s*Start\s*Date\s*[:\-]?[\s\S]{{0,50}}?{date_tok}",
    ]:
        m_st = re.search(pat, pdf_text)
        if m_st:
            data["start_dt"] = parse_any_date(m_st.group(1))
            break

    for pat in [
        rf"(?i)Expiry\s*Date\s*&\s*Time\s*of\s*Policy[\s\S]{{0,50}}?{date_tok}",
        rf"(?i)Policy\s*End\s*Date\s*[:\-]?[\s\S]{{0,50}}?{date_tok}",
    ]:
        m_en = re.search(pat, pdf_text)
        if m_en:
            data["end_dt"] = parse_any_date(m_en.group(1))
            break

    m_pyp = re.search(r"(?i)Previous\s*Policy\s*Number\s*[\r\n]+\s*([A-Z0-9\-]{8,25})", pdf_text)
    if m_pyp and re.search(r"\d{4,}", m_pyp.group(1)):
        data["pyp_number"] = m_pyp.group(1).strip()

    m_si = re.search(
        r"(?i)Base\s*Sum\s*Insured[\s\S]{0,160}?Super\s*Credit\s*%[\r\n\s]+([\d,]{5,12})",
        pdf_text,
    )
    if m_si:
        data["sum_insured"] = clean_amount(m_si.group(1))

    for pat in [
        r"(?i)receipt\s+of\s+premium\s+amount\s+of\s*(?:INR|Rs\.?|₹)\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Total\s*Premium\s*Paid[\s\S]{0,120}?([\d,]+(?:\.\d+)?)\s*[\r\n]+\s*(\d+)\s*[\r\n]+",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    dobs = []
    for m_d in re.finditer(r"(?i)(?:Male|Female|Other)\s*[\r\n]+\s*(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-](?:19|20)\d{2})", pdf_text):
        dt = parse_any_date(m_d.group(1))
        if dt and dt.year >= 1920:
            dobs.append(dt)
    if not dobs:
        for m_d in re.finditer(r"\bPT\d{6,12}\s*[\r\n]+\s*(\d{2}[/\-][A-Za-z]{3}[/\-](?:19|20)\d{2})", pdf_text):
            dt = parse_any_date(m_d.group(1))
            if dt and dt.year >= 1920:
                dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    data["premium_mode"] = extract_premium_mode(pdf_text)
    return data
