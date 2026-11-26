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


def is_iffco_tokio_fhp(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)Family\s+Health\s+Protector", pdf_text)
        or re.search(r"(?i)IFFHLIP\d+", pdf_text)
        or re.search(r"(?i)Product\s*Code\s*[\r\n]+\s*FHP\b", pdf_text)
    )


def _normalize_iffco_agency(raw: str) -> str:
    s = re.sub(r"\s+", " ", str(raw or "")).strip(" .:-_")
    if "," in s:
        parts = [p.strip() for p in s.split(",") if p.strip()]
        if len(parts) == 2:
            s = f"{parts[1]} {parts[0]}"
    return shorten_agency_name(clean_person_name(s))


def parse_iffco_tokio_fhp(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "FHP"
    data["sub_type"] = "MEDICLAIM"

    # 1. Policy Number
    for pat in [
        r"(?i)Policy\s*No\.?\s*[\r\n]+\s*([A-Z0-9/\-]{6,25})",
        r"(?i)forming\s+part\s+of\s+Policy\s*No\.?\s*[:\-]\s*([A-Z0-9/\-]{6,25})",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            data["policy_number"] = m_pol.group(1).strip()
            break

    # 2. Client Name
    for pat in [
        r"(?i)Proposer\s*Name\s*[\r\n]+\s*([^\r\n]{3,80})",
        r"(?i)from\s+Proposer\s+([A-Za-z][A-Za-z .]{2,70}?)\s+towards",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1))
            if cand and len(cand) >= 3:
                data["client_name"] = cand
                break

    # 3. Agency
    m_ag = re.search(
        r"(?i)Intermediary\s*Details\s*[\r\n]+\s*Name\s*[\r\n]+\s*Intermediary\s*Code\s*[\r\n]+\s*Contact\s*No\.?\s*[\r\n]+\s*([^\r\n]{3,80})",
        pdf_text,
    )
    if m_ag:
        data["agency"] = _normalize_iffco_agency(m_ag.group(1))

    # 4. Inception & Expiry Dates
    date_tok = r"(\d{2}[/\-]\d{2}[/\-]\d{2,4})"
    m_per = re.search(
        rf"(?i)Start\s*date[\s\S]{{0,30}}?From[\s\S]{{0,20}}?{date_tok}[\s\S]{{0,60}}?End\s*date[\s\S]{{0,40}}?{date_tok}",
        pdf_text,
    )
    if m_per:
        data["start_dt"] = parse_any_date(m_per.group(1))
        data["end_dt"] = parse_any_date(m_per.group(2))

    # 5. Sum Insured
    for pat in [
        r"(?i)Basic\s*Sum\s*Insured\s*For\s*Family\s*[\r\n]+\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Basic\s*Sum\s*Insured\s*[:\-]?\s*[\r\n\s]*([\d,]+(?:\.\d+)?)",
    ]:
        m_si = re.search(pat, pdf_text)
        if m_si:
            data["sum_insured"] = clean_amount(m_si.group(1))
            break

    # 6. Total Premium
    for pat in [
        r"(?i)Total\s*Value\s*[\r\n]+\s*([\d,]+(?:\.\d+)?)",
        r"(?i)received\s+an\s+amount\s+of\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    # 7. PYP Number (from Insured Previous Policy Details table)
    m_prev_sec = re.search(
        r"(?i)Insured\s+Previous\s+Policy\s+Details([\s\S]{0,1800}?)(?:Intermediary\s+Details|Policy\s+Servicing|$)",
        pdf_text,
    )
    if m_prev_sec:
        m_pyp = re.search(
            r"\b([A-Z0-9/\-]{6,25})\s*[\r\n]+\s*\d{2}/\d{2}/\d{4}\s*[\r\n]+\s*\d{2}/\d{2}/\d{4}",
            m_prev_sec.group(1),
        )
        if m_pyp and re.search(r"\d{4,}", m_pyp.group(1)):
            data["pyp_number"] = m_pyp.group(1).strip()

    if not data["pyp_number"] and data["policy_number"] and re.search(r"(?i)ITGI[\r\n\s]+RENEWAL", pdf_text):
        data["pyp_number"] = data["policy_number"]

    # 8. DOB (Oldest Insured Person)
    dobs = []
    m_ins = re.search(
        r"(?i)Insured\s+Person\(s\)([\s\S]{0,2000}?)(?:ABHA\s+Details|Premium\s+Details|$)",
        pdf_text,
    )
    if m_ins:
        for m_d in re.finditer(r"(\d{2}/\d{2}/(?:19|20)\d{2})\s*[\r\n\s]+(?:Male|Female|Other)", m_ins.group(1), re.I):
            dt = parse_any_date(m_d.group(1))
            if dt and dt.year >= 1920:
                dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    # 9. Premium Mode
    data["premium_mode"] = extract_premium_mode(pdf_text)
    return data
