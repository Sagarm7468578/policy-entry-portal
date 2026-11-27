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


def is_niva_bupa_personal_accident(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)Product\s*Name\s*:\s*Personal\s+Accident\s+Plan", pdf_text)
        or re.search(r"(?i)Personal\s+Accident\s+Plan\s+Policy\s+Schedule", pdf_text)
        or re.search(r"(?i)NBHPAIP\d+V", pdf_text)
    )


def parse_niva_bupa_personal_accident(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "PERSONAL ACCIDENT"
    data["sub_type"] = "PERSONAL ACCIDENT"

    # 1. Policy Number
    for pat in [
        r"(?i)Policy\s*Number\s*[:\-]?\s*[\r\n\s]*([0-9]{10,18})\b",
        r"(?i)Policy\s*No\.?\s*[:\-]?\s*[\r\n\s]*([0-9]{10,18})\b",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            data["policy_number"] = m_pol.group(1).strip()
            break

    # 2. Client Name
    for pat in [
        r"(?i)Policyholder\s*Name\s*[:\-]\s*([^\r\n]{3,80})",
        r"(?i)Policyholder\s*Name\s*[\r\n]+\s*([^\r\n]{3,80})",
        r"(?i)Dear\s+([^\r\n,]{3,80})",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1).lstrip(" :-\t"))
            if cand and len(cand) >= 3 and cand not in ("CUSTOMER", "SIR", "MADAM"):
                data["client_name"] = cand
                break

    # 3. Agency ("Intermediary Details -> Intermediary Name -> Intermediary Code -> Intermediary Contact No. -> Kirti Laddha")
    m_ag = re.search(
        r"(?i)Intermediary\s*Details\s*[\r\n]+\s*Intermediary\s*Name\s*[\r\n]+\s*Intermediary\s*Code\s*[\r\n]+\s*Intermediary\s*Contact\s*No\.?\s*[\r\n]+\s*([^\r\n]{2,80})",
        pdf_text,
    )
    if not m_ag:
        m_ag = re.search(r"(?i)Intermediary\s*Name\s*[:\-]\s*([^\r\n]{2,80})", pdf_text)
    if m_ag:
        cand = shorten_agency_name(clean_person_name(m_ag.group(1)))
        if cand:
            data["agency"] = cand

    # 4. Inception & Expiry Dates
    date_tok = r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})"
    m_st = re.search(
        rf"(?i)Policy\s*Commencement\s*Date\s*(?:and\s*[\r\n\s]*Time)?\s*#?\s*[:\-]?\s*[\r\n\s]*{date_tok}",
        pdf_text,
    )
    if m_st:
        data["start_dt"] = parse_any_date(m_st.group(1))

    m_en = re.search(
        rf"(?i)Policy\s*Expiry\s*Date\s*(?:and\s*[\r\n\s]*Time)?\s*[:\-]?\s*[\r\n\s]*{date_tok}",
        pdf_text,
    )
    if m_en:
        data["end_dt"] = parse_any_date(m_en.group(1))

    # 5. Base Sum Insured
    for pat in [
        r"(?i)Base\s*Benefits[\s\S]{0,120}?[\r\n]+\s*([\d,]{5,15})\b",
        r"(?i)Applicant\s*[\r\n]+\s*([\d,]{5,15})\b",
        r"(?i)Sum\s*Insured\s*[\r\n]+\s*INR\s*([\d,]{5,15})\b",
    ]:
        m_si = re.search(pat, pdf_text)
        if m_si:
            amt = clean_amount(m_si.group(1))
            if amt.isdigit() and int(amt) >= 50000:
                data["sum_insured"] = amt
                break

    # 6. Total Premium (Gross Premium Rs.)
    for pat in [
        r"(?i)Gross\s*Premium\s*\(Rs\.?\)\s*[\r\n]+\s*([\d,]+(?:\.\d+)?)\b",
        r"(?i)Gross\s*Premium\s*\(Rs\.?\)\s*\(in\s*words\)\s*[\r\n]+[\s\S]{0,120}?([\d,]+\.\d{2})\s*[\r\n]+[A-Za-z ]+Only\b",
        r"(?i)Premium\s*of\s*Plan\s*Opted\s*\(INR\)\s*[\r\n]+\s*([\d,]+(?:\.\d+)?)\b",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            amt = clean_amount(m_p.group(1))
            if amt.isdigit() and int(amt) > 0:
                data["premium"] = amt
                break

    # 7. DOB (Oldest Insured Person)
    dobs = []
    for m_d in re.finditer(
        r"(\d{2}/\d{2}/(?:19|20)\d{2})\s*[\r\n\s]+(?:\d{1,3}\s*[\r\n\s]+)?(?:Male|Female|M|F)\b",
        pdf_text,
        re.I,
    ):
        dt = parse_any_date(m_d.group(1))
        if dt and dt.year >= 1920:
            dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    # 8. Premium Mode (if absent, verified_defaults marks FILL MANUAL)
    data["premium_mode"] = extract_premium_mode(pdf_text)
    return data
