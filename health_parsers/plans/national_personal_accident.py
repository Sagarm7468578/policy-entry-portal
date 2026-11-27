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


def is_national_personal_accident(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)Policy\s*Schedule\s*\-\s*Personal\s+Accident", pdf_text)
        or re.search(r"(?i)NICPAIP\d+", pdf_text)
    )


def parse_national_personal_accident(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "PERSONAL ACCIDENT"
    data["sub_type"] = "PERSONAL ACCIDENT"

    for pat in [
        r"(?i)Policy\s*Number\s*[:\-]\s*[\r\n\s]*([0-9]{15,24})",
        r"(?i)Policy\s*No\.?\s*[:\-]?\s*[\r\n\s]*([0-9]{15,24})",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            data["policy_number"] = m_pol.group(1).strip()
            break

    for pat in [
        r"(?i)Customer\s*Name\s*[:\-]\s*([^\r\n]{3,80})",
        r"(?i)Details\s*Of\s*Receiver\s*[:\-]\s*([^\r\n]{3,80})",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            raw = re.sub(r"^[\s_.]+", "", m_nm.group(1))
            cand = clean_person_name(raw)
            if cand and len(cand) >= 3:
                data["client_name"] = cand
                break

    m_sc = re.search(r"(?i)Sales\s*Channel\s*Details([\s\S]{0,350})", pdf_text)
    if m_sc:
        m_ag = re.search(r"(?i)Name\s*[:\-]\s*([^\r\n]{3,80})", m_sc.group(1))
        if m_ag:
            raw = re.split(r"(?i)(?:संपकर|Contact\s*Number|Mobile|Phone|Code)", m_ag.group(1))[0]
            cand = clean_person_name(raw)
            if cand and len(cand) >= 2:
                data["agency"] = shorten_agency_name(cand)

    date_tok = r"(\d{2}[/\-]\d{2}[/\-]\d{2,4})"
    m_per = re.search(
        rf"(?i)Policy\s*Effective\s*from\s*:?[\s\S]{{0,30}}?{date_tok}[\s\S]{{0,30}}?to\s*(?:midnight\s*of\s*)?{date_tok}",
        pdf_text,
    )
    if m_per:
        data["start_dt"] = parse_any_date(m_per.group(1))
        data["end_dt"] = parse_any_date(m_per.group(2))

    m_si = re.search(
        r"(?i)(?:24\s*Hours\s*Coverage|Table\s*[I1V]+)[\s\S]{0,80}?[`₹Rs.\s]+([\d,]{5,15}(?:\.\d+)?)",
        pdf_text,
    )
    if m_si:
        data["sum_insured"] = clean_amount(m_si.group(1))

    for pat in [
        r"(?i)Total\s*Amount\s*[\r\n]+\s*[`₹Rs.\s]*([\d,]+(?:\.\d+)?)",
        r"(?i)Total\s*Premium\s*[\r\n]+\s*[`₹Rs.\s]*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    m_prev = re.search(
        r"(?i)Previous\s*Policy\s*Number\s*and[\s\S]{0,40}?Expiry\s*Date([\s\S]{0,1000}?)(?:Rupees|Government\s+Subsidy|Details\s+of\s+the\s+Persons|$)",
        pdf_text,
    )
    if m_prev:
        prev_pols = re.findall(r"\b(\d{15,24})\b", m_prev.group(1))
        if prev_pols:
            data["pyp_number"] = prev_pols[-1]

    dobs = []
    m_mem = re.search(r"(?i)Details\s+of\s+the\s+Persons\s+insured([\s\S]{0,1200}?)(?:Assignment:|$)", pdf_text)
    if m_mem:
        for m_d in re.finditer(r"\b(\d{2}/\d{2}/(?:19|20)\d{2})\s*[\r\n]+\s*\d{1,3}\s*[\r\n]+\s*(?:M|F|Male|Female)\b", m_mem.group(1), re.I):
            dt = parse_any_date(m_d.group(1))
            if dt and dt.year >= 1920:
                dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    data["premium_mode"] = extract_premium_mode(pdf_text)
    return data
