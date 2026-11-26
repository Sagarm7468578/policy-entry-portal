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


def is_hdfc_optima_secure(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)my\s*:\s*Optima\s+Secure", pdf_text)
        or re.search(r"(?i)HDFHLIP25041V", pdf_text)
        or re.search(r"(?i)HDFHLIP26058V", pdf_text)
    )


def parse_hdfc_optima_secure(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "OS"
    data["sub_type"] = "MEDICLAIM"

    # 1. Policy Number
    for pat in [
        r"(?i)Policy\s*Number\s*[\r\n\s]*[:\-]?\s*([\d\s]{15,28})",
        r"(?i)policy\s*reference\s*no\.?\s*([\d]{15,22})",
        r"(?i)Policy\s*No\.?\s*[:\-]\s*([\d\s]{15,28})",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            digits = re.sub(r"\s+", "", m_pol.group(1))
            if len(digits) >= 15:
                data["policy_number"] = digits
                break

    # 2. Client Name
    for pat in [
        r"(?i)Policyholder\s*Name\s*[\r\n\s]*[:\-]?\s*([^\r\n]{3,80})",
        r"(?i)Dear\s+([^\r\n,]{3,80})",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1))
            if cand and len(cand) >= 3:
                data["client_name"] = cand
                break

    # 3. Previous Policy Number
    m_pyp = re.search(r"(?i)Previous\s*Policy\s*[:\-]\s*([\d\s]{12,28})", pdf_text)
    if m_pyp:
        pyp_digits = re.sub(r"\s+", "", m_pyp.group(1))
        if len(pyp_digits) >= 12:
            data["pyp_number"] = pyp_digits

    # 4. Agency
    m_ag = re.search(
        r"(?i)Intermediary\s*Name\s*[\r\n]+\s*Intermediary\s*Code\s*[\r\n]+\s*Intermediary\s*Contact\s*Number\s*[\r\n]+\s*([^\r\n]{3,80})",
        pdf_text,
    )
    if not m_ag:
        m_ag = re.search(r"(?i)Intermediary\s*Name\s*[:\-]\s*([^\r\n]{3,80})", pdf_text)
    if m_ag:
        raw = re.sub(r"(?i)^\s*(?:AGENT|BROKER|POSP|IMD|DIRECT)\s*[:\-]\s*", "", m_ag.group(1).strip())
        cand = clean_person_name(raw)
        if cand and len(cand) >= 2:
            data["agency"] = shorten_agency_name(cand)

    # 5. Inception & Expiry Dates
    date_tok = r"(\d{2}[/\-]\d{2}[/\-]\d{2,4})"
    m_per = re.search(
        rf"(?i)Period\s*of\s*Insurance[\s\S]{{0,40}}?From\s+{date_tok}[\s\S]{{0,40}}?to\s+{date_tok}",
        pdf_text,
    )
    if not m_per:
        m_per = re.search(rf"(?i)for\s+the\s+period\s+{date_tok}\s+to\s+{date_tok}", pdf_text)
    if m_per:
        data["start_dt"] = parse_any_date(m_per.group(1))
        data["end_dt"] = parse_any_date(m_per.group(2))

    # 6. Base Sum Insured
    for pat in [
        r"(?i)Sum\s*Insured\s*opted\s*[:\-]\s*(?:Rs\.?|INR|₹)?\s*([\d,]{5,15})",
        r"(?i)Base\s*Sum\s*Insured\s*per\s*Insured\s*Person[\s\S]{0,60}?[\r\n]+\s*([\d,]{5,15})",
        r"(?i)Base\s*Sum\s*Insured\s*(?:\([₹`]\))?\s*[:\-]?\s*[\r\n]+\s*([\d,]{5,15})",
    ]:
        m_si = re.search(pat, pdf_text)
        if m_si:
            data["sum_insured"] = clean_amount(m_si.group(1))
            break

    # 7. Total Premium
    for pat in [
        r"(?i)received\s+an\s+amount\s+of\s*[\r\n\s]*(?:₹|`|Rs\.?|INR)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Total\s*Premium\s*\(E-F\)\s*[\r\n]+\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    # 8. DOB (Oldest Insured Person)
    dobs = []
    for m_sec in re.finditer(
        r"(?i)(?:Insured\s+Person[’'`]?s\s+Premium\s+Details|Insured\s+Person[’'`]?s\s+Details\s+and\s+Sum\s+Insured|Insured\s+Name\s*[\r\n]+\s*Member\s+ID)([\s\S]{0,1600})",
        pdf_text,
    ):
        for m_d in re.finditer(
            r"(?i)(?:Male|Female|Other)\s*[\r\n\s]+(\d{2}[/\-]\d{2}[/\-](?:19|20)\d{2})"
            r"|(\d{2}[/\-]\d{2}[/\-](?:19|20)\d{2})\s*[\r\n\s]+(?:Male|Female|Other)",
            m_sec.group(1),
        ):
            dt = parse_any_date(m_d.group(1) or m_d.group(2))
            if dt and dt.year >= 1920:
                dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    # 9. Premium Mode
    data["premium_mode"] = extract_premium_mode(pdf_text)
    return data
