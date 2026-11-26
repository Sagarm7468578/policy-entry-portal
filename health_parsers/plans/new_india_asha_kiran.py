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


def is_new_india_asha_kiran(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)New\s+India\s+Asha\s+Kiran", pdf_text)
        or re.search(r"(?i)NIAHLIP25047V", pdf_text)
    )


def _clean_nia_person_name(raw: str) -> str:
    s = clean_person_name(raw)
    m_rel = re.match(r"^([A-Z]+)\s+(?:S/O|W/O|D/O|C/O)\s+(?:(?:MR|MRS|MS|SHRI|SMT|LATE)\.?\s+)*[A-Z]+\s+([A-Z]+)$", s)
    if m_rel:
        return f"{m_rel.group(1)} {m_rel.group(2)}"
    return s


def parse_new_india_asha_kiran(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "ASHA KIRAN"
    data["sub_type"] = "MEDICLAIM"

    # 1. Policy Number
    for pat in [
        r"(?i)Policy\s*Number\s*[\r\n\s]*[:\-]\s*([0-9]{15,24})",
        r"(?i)Policy\s*No\.?\s*[:\-]\s*([0-9]{15,24})",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            data["policy_number"] = m_pol.group(1).strip()
            break

    # 2. Client Name
    for pat in [
        r"(?i)Insured\s*Name\s*[\r\n\s]*[:\-]\s*([^\r\n]{3,80})",
        r"(?i)certify\s+that\s+Mr\.?/Mrs\.?\s+([^\r\n]{3,80}?)\s+has\s+paid",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = _clean_nia_person_name(m_nm.group(1))
            if cand and len(cand) >= 3:
                data["client_name"] = cand
                break

    # 3. Agency
    for pat in [
        r"(?i)Agent\s*/\s*Bancassurance\s*/\s*Spe[\r\n\s]*cified\s*Person\s*[\r\n\s]*[:\-]\s*([^\r\n(]{3,80})",
        r"(?i)Agent\s*/\s*Broker\s*(?:Name)?\s*[:\-]\s*([^\r\n(]{3,80})",
    ]:
        m_ag = re.search(pat, pdf_text)
        if m_ag:
            cand = clean_person_name(m_ag.group(1))
            if cand and len(cand) >= 2:
                data["agency"] = shorten_agency_name(cand)
                break

    # 4. Previous Policy Number
    m_pyp = re.search(r"(?i)Prev\.?\s*Policy\s*no\.?\s*[\r\n\s]*[:\-]\s*([0-9A-Z/\-]{8,28})", pdf_text)
    if m_pyp and re.search(r"\d{6,}", m_pyp.group(1)):
        data["pyp_number"] = m_pyp.group(1).strip()

    # 5. Inception & Expiry Dates
    date_tok = r"(\d{2}[/\-]\d{2}[/\-]\d{2,4})"
    m_per = re.search(
        rf"(?i)Period\s*of\s*Insurance[\s\S]{{0,40}}?From\s*[:\-]?\s*{date_tok}[\s\S]{{0,40}}?To\s*[:\-]?\s*{date_tok}",
        pdf_text,
    )
    if m_per:
        data["start_dt"] = parse_any_date(m_per.group(1))
        data["end_dt"] = parse_any_date(m_per.group(2))

    # 6. Sum Insured
    for pat in [
        r"(?i)Total\s*Sum\s*Insured\s*[\r\n]+\s*([\d,]{5,15})",
        r"(?i)Floater\s*Sum\s*Insured\s*[\r\n]+\s*([\d,]{5,15})",
    ]:
        m_si = re.search(pat, pdf_text)
        if m_si:
            data["sum_insured"] = clean_amount(m_si.group(1))
            break

    # 7. Total Premium
    for pat in [
        r"(?i)Net\s*Premium\s*\(With\s*GST\)\s*[\r\n]+\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Total\s*Gross\s*Premium\s*\(Without\s*GST\)\s*[\r\n]+\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    # 8. DOB (Oldest Insured Member)
    dobs = []
    m_mem = re.search(r"(?i)Member\s+Details([\s\S]{0,1800}?)(?:Total\s+Sum\s+Insured|COVERAGE|$)", pdf_text)
    if m_mem:
        for m_d in re.finditer(r"(\d{2}/\d{2}/(?:19|20)\d{2})\s*[\r\n]+\s*\d{1,3}\s*[\r\n]+\s*(?:M|F|Male|Female)\b", m_mem.group(1), re.I):
            dt = parse_any_date(m_d.group(1))
            if dt and dt.year >= 1920:
                dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    # 9. Premium Mode
    data["premium_mode"] = extract_premium_mode(pdf_text)
    return data
