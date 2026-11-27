import re
from health_parsers.common import (
    default_extracted_data,
    parse_any_date,
    fmt_date,
    clean_amount,
    clean_person_name,
    shorten_agency_name,
    extract_premium_mode,
)


def is_new_india_yuva_bharat(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)Yuva\s+Bharat\s+Health\s+Policy", pdf_text)
        or re.search(r"(?i)NIAHLIP25043V", pdf_text)
    )


def parse_new_india_yuva_bharat(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "YUVA BHARAT"
    data["sub_type"] = "MEDICLAIM"

    for pat in [
        r"(?i)Current\s*Policy\s*No\.?\s*[\r\n\s]*[:\-]?\s*([0-9]{15,24})",
        r"(?i)Policy\s*No\.?\s*[:\-]\s*([0-9]{15,24})",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            data["policy_number"] = m_pol.group(1).strip()
            break

    for pat in [
        r"(?i)Policyholder\s*Name\s*[\r\n]+\s*([^\r\n]{3,80})",
        r"(?i)certify\s+that\s+Mr\.?/Mrs\.?\s+([^\r\n]{3,80}?)\s+has\s+paid",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1))
            if cand and len(cand) >= 3:
                data["client_name"] = cand
                break

    m_ag = re.search(
        r"(?i)Name\s*of\s*the\s*[\r\n\s]*Agent/Intermediary/CPSC\s*[\r\n\s]*User\s*[\r\n]+\s*([^\r\n(]{3,80})",
        pdf_text,
    )
    if m_ag:
        cand = clean_person_name(m_ag.group(1))
        if cand and len(cand) >= 2:
            data["agency"] = shorten_agency_name(cand)

    m_pyp = re.search(r"(?i)Previous\s*Policy\s*No\.?\s*[\r\n]+\s*([0-9A-Z/\-]{8,28})", pdf_text)
    if m_pyp and re.search(r"\d{6,}", m_pyp.group(1)):
        data["pyp_number"] = m_pyp.group(1).strip()

    date_tok = r"(\d{2}[/\-]\d{2}[/\-]\d{2,4})"
    m_per = re.search(
        rf"(?i)Current\s*Policy\s*Period[\s\S]{{0,30}}?From\s*[:\-]?\s*{date_tok}[\s\S]{{0,30}}?To\s*[:\-]?\s*{date_tok}",
        pdf_text,
    )
    if m_per:
        data["start_dt"] = parse_any_date(m_per.group(1))
        data["end_dt"] = parse_any_date(m_per.group(2))

    m_si = re.search(r"(?i)Floater\s*Sum\s*Insured\s*[\r\n]+\s*([\d,]{5,15})", pdf_text)
    if m_si:
        data["sum_insured"] = clean_amount(m_si.group(1))

    m_p = re.search(r"(?i)Net\s*Premium\s*\(With\s*[\r\n\s]*GST\)\s*[\r\n]+\s*([\d,]+(?:\.\d+)?)", pdf_text)
    if m_p:
        data["premium"] = clean_amount(m_p.group(1))

    dobs = []
    m_ins = re.search(r"(?i)Insured\s+Persons\s+details([\s\S]{0,1800}?)(?:Floater\s+Sum\s+Insured|Premium\s+Details|$)", pdf_text)
    if m_ins:
        for m_d in re.finditer(r"(\d{2}/\d{2}/(?:19|20)\d{2})\s*\(\d{1,3}\)", m_ins.group(1)):
            dt = parse_any_date(m_d.group(1))
            if dt and dt.year >= 1920:
                dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    data["premium_mode"] = extract_premium_mode(pdf_text)
    return data
