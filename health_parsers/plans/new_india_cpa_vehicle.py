import re
from health_parsers.common import (
    default_extracted_data,
    parse_any_date,
    clean_amount,
    clean_person_name,
    extract_premium_mode,
)


def is_new_india_cpa_vehicle(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)Standalone\s+Compulsory\s+Personal\s+Accident\s*\(\s*CPA\s*\)", pdf_text)
        or re.search(r"(?i)IRDAN190RP0058V", pdf_text)
    )


def _extract_cpa_agency(pdf_text: str) -> str:
    # Matches "Agent/Bancassurance/CPSC\nUser\nMrs. SONAL  LADDHA   (NIAAG00134008)"
    patterns = [
        r"(?i)Agent\s*/\s*Bancassurance\s*/\s*CPSC[\r\n\s]*(?:User)?[\r\n\s]*[:\-]?\s*([^\r\n]{3,90})",
        r"(?i)Name\s+of\s+the\s+Agent[\s\S]{0,40}?User\s*[\r\n]+\s*([^\r\n]{3,90})",
    ]
    for pat in patterns:
        m = re.search(pat, pdf_text)
        if m:
            raw = re.sub(r"\([^)]*\)", "", m.group(1))
            cand = clean_person_name(raw)
            if cand and len(cand) >= 3 and cand.split()[0].lower() not in {"prev", "phone", "client", "user"}:
                return cand
    return ""


def parse_new_india_cpa_vehicle(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "CPA VEHICLE"
    data["sub_type"] = "PERSONAL ACCIDENT"
    data["skip_dob_fallback"] = True  # New India CPA PDF only prints Age, not DOB

    # 1. Policy Number
    for pat in [
        r"(?i)Policy\s*Number\s*[\r\n]+\s*([A-Z0-9/\-]{10,30})",
        r"(?i)Policy\s*No\.?\s*[:\-]\s*([A-Z0-9/\-]{10,30})",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            data["policy_number"] = m_pol.group(1).strip()
            break

    # 2. Client Name
    m_nm = re.search(r"(?i)Insured\s*Name\s*[\r\n]+\s*([^\r\n]{3,80})", pdf_text)
    if m_nm:
        data["client_name"] = clean_person_name(m_nm.group(1))

    # 3. Agency
    data["agency"] = _extract_cpa_agency(pdf_text)

    # 4. Policy Period
    date_tok = r"(\d{2}[/\-]\d{2}[/\-]\d{2,4})"
    m_per = re.search(
        rf"(?i)Period\s*of\s*Insurance[\s\S]{{0,60}}?{date_tok}[\s\S]{{0,30}}?to[\s\S]{{0,20}}?{date_tok}",
        pdf_text,
    )
    if m_per:
        data["start_dt"] = parse_any_date(m_per.group(1))
        data["end_dt"] = parse_any_date(m_per.group(2))

    # 5. PYP Number (must contain digits so next-line label "Phone No" is never captured)
    m_pyp = re.search(r"(?i)Prev\.?\s*Policy\s*no\.?\s*[:\-]?\s*[\r\n]*([^\r\n]{1,40})", pdf_text)
    if m_pyp:
        cand_pyp = m_pyp.group(1).strip()
        if re.search(r"\d{6,}", cand_pyp) and not re.search(r"(?i)\b(?:Phone|Fax|Email|Client)\b", cand_pyp):
            data["pyp_number"] = cand_pyp

    # 6. Total Premium (from Premium / GST / Total block)
    m_tot = re.search(
        r"(?i)Total\s*\(\s*`?\s*\)[\s\S]{0,120}?`\s*[\d,]+\s*[\r\n]+\s*`\s*[\d,]+\s*[\r\n]+\s*`\s*([\d,]+)",
        pdf_text,
    )
    if m_tot:
        data["premium"] = clean_amount(m_tot.group(1))
    else:
        m_bp = re.search(r"(?i)Premium\s*[\r\n]+\s*`\s*([\d,]+)", pdf_text)
        m_sg = re.search(r"(?i)SGST\s*[\r\n]+\s*\d+\s*[\r\n]+\s*([\d,]+)", pdf_text)
        m_cg = re.search(r"(?i)CGST\s*[\r\n]+\s*\d+\s*[\r\n]+\s*([\d,]+)", pdf_text)
        if m_bp:
            tot = int(clean_amount(m_bp.group(1)))
            tot += int(clean_amount(m_sg.group(1))) if m_sg else 0
            tot += int(clean_amount(m_cg.group(1))) if m_cg else 0
            data["premium"] = str(tot)

    # 7. Sum Insured
    m_si = re.search(r"(?i)SELF\s*[\r\n]+\s*([\d,]{5,12})", pdf_text)
    if not m_si:
        m_si = re.search(r"(?i)Commercial\s+Vehicles\s*[\r\n]+\s*([\d,]{5,12})", pdf_text)
    if m_si:
        data["sum_insured"] = clean_amount(m_si.group(1))

    # 8. Premium Mode
    data["premium_mode"] = extract_premium_mode(pdf_text)

    return data
