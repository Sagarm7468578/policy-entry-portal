import re
from health_parsers.common import (
    default_extracted_data,
    parse_any_date,
    fmt_date,
    clean_amount,
    clean_person_name,
    extract_premium_mode,
)


def is_iffco_tokio_fhp(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)Family\s+Health\s+Protector", pdf_text)
        or re.search(r"(?i)IFFHLIP26042V", pdf_text)
    )


def _extract_iffco_agency(pdf_text: str) -> str:
    m_block = re.search(
        r"(?i)Intermediary\s*Details\s*[\r\n]+\s*Name\s*[\r\n]+\s*Intermediary\s*Code\s*[\r\n]+\s*Contact\s*No\.?\s*[\r\n]+\s*([^\r\n]{3,80})",
        pdf_text,
    )
    if m_block:
        raw = m_block.group(1).strip()
        # Convert "HEDA, PRITI" -> "PRITI HEDA"
        if "," in raw:
            parts = [p.strip() for p in raw.split(",", 1)]
            if len(parts) == 2 and parts[0] and parts[1]:
                raw = f"{parts[1]} {parts[0]}"
        cand = clean_person_name(raw)
        if cand and len(cand) >= 3:
            return cand
    return ""


def parse_iffco_tokio_fhp(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "FHP"
    data["sub_type"] = "MEDICLAIM"

    m_pol = re.search(r"(?i)Policy\s*No\.?\s*[\r\n\s]*[:\-]?\s*([A-Z0-9/\-]{6,25})", pdf_text)
    if m_pol:
        data["policy_number"] = m_pol.group(1).strip()

    m_nm = re.search(r"(?i)Proposer\s*Name\s*[\r\n]+\s*([^\r\n]{3,80})", pdf_text)
    if m_nm:
        data["client_name"] = clean_person_name(m_nm.group(1))

    data["agency"] = _extract_iffco_agency(pdf_text)

    date_tok = r"(\d{2}[/\-]\d{2}[/\-]\d{2,4})"
    m_st = re.search(rf"(?i)Start\s*date\s*[\r\n]+\s*From\s*[\r\n]+\s*{date_tok}", pdf_text)
    m_en = re.search(rf"(?i)End\s*date\s*[\r\n]+\s*(?:Till\s*Midnight\s*on\s*[\r\n]+\s*)?{date_tok}", pdf_text)
    if m_st:
        data["start_dt"] = parse_any_date(m_st.group(1))
    if m_en:
        data["end_dt"] = parse_any_date(m_en.group(1))

    m_si = re.search(r"(?i)Basic\s*Sum\s*Insured\s*(?:For\s*Family)?\s*[\r\n]+\s*([\d,]+(?:\.\d+)?)", pdf_text)
    if m_si:
        data["sum_insured"] = clean_amount(m_si.group(1))

    for pat in [
        r"(?i)Total\s*Value\s*[\r\n]+\s*([\d,]+(?:\.\d+)?)",
        r"(?i)received\s+an\s+amount\s+of\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    m_prev = re.search(
        r"(?i)Insured\s+Previous\s+Policy\s+Details([\s\S]{0,600}?)(?:Intermediary\s+Details|$)",
        pdf_text,
    )
    if m_prev:
        m_pno = re.search(r"(?i)LTD\s*[\r\n]+\s*([A-Z0-9/\-]{6,25})\s*[\r\n]+\s*\d{2}/\d{2}/\d{4}", m_prev.group(1))
        if m_pno:
            data["pyp_number"] = m_pno.group(1).strip()

    m_ins = re.search(r"(?i)Insured\s+Details([\s\S]{0,1800}?)(?:CoPayment|Net\s+Premium|$)", pdf_text)
    if m_ins:
        dobs = [
            dt for d_str in re.findall(r"\b\d{2}/\d{2}/(?:19|20)\d{2}\b", m_ins.group(1))
            if (dt := parse_any_date(d_str)) and dt.year >= 1920
        ]
        if dobs:
            data["dob"] = fmt_date(min(dobs))

    data["premium_mode"] = extract_premium_mode(pdf_text)
    return data
