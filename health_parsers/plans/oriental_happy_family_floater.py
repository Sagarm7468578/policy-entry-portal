import re
from health_parsers.common import (
    default_extracted_data,
    parse_any_date,
    fmt_date,
    clean_amount,
    clean_person_name,
    shorten_agency_name,
)


def is_oriental_happy_family_floater(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)HAPPY\s+FAMILY\s+FLOATER", pdf_text)
        or re.search(r"(?i)OICHLIP25046V", pdf_text)
    )


def parse_oriental_happy_family_floater(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "HAPPY FAMILY FLOATER"
    data["sub_type"] = "MEDICLAIM"

    for pat in [
        r"(?i)forming\s+part\s+of\s+policy\s+number\s*[:\-]?\s*([0-9]{6}/[0-9]{2}/[0-9]{4}/[0-9]+)",
        r"\b([0-9]{6}/48/[0-9]{4}/[0-9]+)\b",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            data["policy_number"] = m_pol.group(1).strip()
            break

    m_nm = re.search(r"(?i)([^\r\n]{3,80}?)\s*(?:\(GSTIN[^)]*\))?\s*[\r\n]+\s*Insured\s*Name\b", pdf_text)
    if not m_nm:
        m_nm = re.search(r"(?i)Insured\s*Name\s*[:\-]\s*([^\r\n]{3,80})", pdf_text)
    if m_nm:
        raw = re.sub(r"(?i)\(GSTIN[^)]*\)", "", m_nm.group(1))
        cand = clean_person_name(raw)
        if cand and len(cand) >= 3:
            data["client_name"] = cand

    m_pyp = re.search(r"(?i)([0-9]{6}/[0-9]{2}/[0-9]{4}/[0-9]+)\s*[\r\n]+\s*Prev\.?\s*Policy\s*No\.?", pdf_text)
    if not m_pyp:
        m_pyp = re.search(r"(?i)Prev\.?\s*Policy\s*No\.?\s*[:\-]\s*([0-9A-Z/\-]{8,30})", pdf_text)
    if m_pyp:
        data["pyp_number"] = m_pyp.group(1).strip()

    m_ag = re.search(r"(?i)Agent/Broker\s*Details\s*[\r\n]+\s*([^\r\n]{4,80})\s*[\r\n]+\s*Agent/Broker\b", pdf_text)
    if not m_ag:
        m_ag = re.search(r"(?i)\b(?:BA|AG|IM|DB)[0-9]{6,}\s+([A-Za-z][A-Za-z .&\-]{2,60})\s*[\r\n]+\s*Agent/Broker\b", pdf_text)
    if m_ag:
        raw = re.sub(r"^[A-Z]{2}\d{6,}\s+", "", m_ag.group(1).strip())
        cand = clean_person_name(raw)
        if cand and len(cand) >= 2:
            data["agency"] = shorten_agency_name(cand)

    date_tok = r"(\d{2}[/\-]\d{2}[/\-]\d{2,4})"
    m_per = re.search(
        rf"(?i)FROM\s+[\d:]+\s+ON\s+{date_tok}\s+TO\s+(?:MIDNIGHT\s+OF\s+)?{date_tok}",
        pdf_text,
    )
    if m_per:
        data["start_dt"] = parse_any_date(m_per.group(1))
        data["end_dt"] = parse_any_date(m_per.group(2))

    m_si = re.search(r"(?i)Sum\s*Insured\s+([\d,]{5,15})\b", pdf_text)
    if m_si:
        data["sum_insured"] = clean_amount(m_si.group(1))

    for pat in [
        r"(?i)([\d,]+(?:\.\d+)?)\s*[\r\n]+\s*Gross\s*Premium\b",
        r"(?i)([\d,]+(?:\.\d+)?)\s*[\r\n]+\s*Stamp\s*Duty\s*:\s*[\r\n]+\s*Total\s*:",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    m_ch = re.search(
        r"(?i)1\.?\s*Online[\s\S]{0,60}?2\.?\s*Fresh[\s\S]{0,60}?3\.?\s*Renewal\s*[\r\n]+\s*(YES|NO)\b",
        pdf_text,
    )
    if m_ch and m_ch.group(1).upper() == "YES":
        data["premium_mode"] = "ONLINE"

    dobs = []
    m_dob = re.search(r"(?i)Date\s*of\s*[\r\n\s]*Birth([\s\S]{0,300}?)(?:Total\s+Premium|PA\s+Capital|$)", pdf_text)
    if m_dob:
        for m_d in re.finditer(r"\b(\d{2}/\d{2}/(?:19|20)\d{2})\b", m_dob.group(1)):
            dt = parse_any_date(m_d.group(1))
            if dt and dt.year >= 1920:
                dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    return data
