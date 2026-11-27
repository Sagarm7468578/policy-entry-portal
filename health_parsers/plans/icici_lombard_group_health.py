import re
from health_parsers.common import (
    default_extracted_data,
    parse_any_date,
    clean_amount,
    clean_person_name,
    shorten_agency_name,
    extract_premium_mode,
)


def is_icici_lombard_group_health(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)Group\s+Health\s*(?:\(Floater\)\s*)?Insurance", pdf_text)
        and re.search(r"(?i)ICICI\s+Lombard|ICIHLGP", pdf_text)
    )


def parse_icici_lombard_group_health(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "GROUP HEALTH"
    data["sub_type"] = "MEDICLAIM"

    m_pol = re.search(r"(?i)Policy\s*Number\s*[\r\n\s]*:?\s*[\r\n\s]*(\d{10,16})\b", pdf_text)
    if m_pol:
        data["policy_number"] = m_pol.group(1).strip()

    for pat in [
        r"(?i)Name\s*of\s*the\s*Insured\s*[\r\n\s]*:\s*[\r\n\s]*([^\r\n]{3,80})",
        r"(?i)Name\s*of\s*the\s*Customer\s*:\s*[\r\n\s]*([^\r\n]{3,80})",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1))
            if cand and len(cand) >= 3:
                data["client_name"] = cand
                break

    m_ag = re.search(r"(?i)Agency/Broker\s*Name\s*[\r\n\s]*:\s*[\r\n\s]*([^\r\n]{3,80})", pdf_text)
    if m_ag:
        cand = shorten_agency_name(clean_person_name(m_ag.group(1)))
        cand = re.sub(r"\bKRITI\s+LADDHA\b", "KIRTI LADDHA", cand)
        data["agency"] = cand

    date_tok = r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})"
    m_per = re.search(
        rf"(?i)Period\s*of\s*Insurance[\s\S]{{0,50}}?From\s*:\s*[\d:]+\s*Hours\s*of\s*{date_tok}\s*To\s*(?:Midnight\s*)?{date_tok}",
        pdf_text,
    )
    if m_per:
        data["start_dt"] = parse_any_date(m_per.group(1))
        data["end_dt"] = parse_any_date(m_per.group(2))

    m_si = re.search(r"(?i)Total\s*Lives\s*Insured[\s\S]{0,60}?Sum\s*Insured\s*[\r\n\s]*:\s*[\r\n\s]*[`₹Rs.\s]*([\d,]+(?:\.\d+)?)", pdf_text)
    if m_si:
        data["sum_insured"] = clean_amount(m_si.group(1))

    for pat in [
        r"(?i)\*Total\s*Premium\s*[\r\n\s]*:\s*[\r\n\s]*[`₹Rs.\s]*([\d,]+(?:\.\d+)?)",
        r"(?i)Total\s*Premium\s*inclusive\s*Tax\s*\([`₹Rs.]*\)\s*[\r\n\s]*([\d,]+(?:\.\d+)?)",
        r"(?i)Basic\s*Premium\s*[\r\n\s]*:\s*[\r\n\s]*[`₹Rs.\s]*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    data["premium_mode"] = extract_premium_mode(pdf_text) or "FILL MANUAL"
    data["pyp_number"] = "FILL MANUAL"
    data["dob"] = "GROUP POLICY"
    return data
