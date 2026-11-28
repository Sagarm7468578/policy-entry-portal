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


def is_care_supreme(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)\bCare\s+Supreme\b", pdf_text)
        or re.search(r"(?i)CHIHLIP23128V|CHIHLIP25047V", pdf_text)
    )


def _extract_care_portability_pyp(pdf_text: str, current_pol: str) -> str:
    m_port = re.search(
        r"(?i)Portability\s+Details\s+of\s+the\s+Insured([\s\S]{0,1600}?)(?:For\s+Care\s+Health|Premium\s+Acknowledgement|Date\s+of\s+Issue|$)",
        pdf_text,
    )
    if not m_port:
        return ""
    blk = m_port.group(1)

    # Row structure: Name -> First Policy Number -> Expiry Policy Number -> Date of First Enrollment (DD-Mon-YYYY)
    # Handles BOTH slash formats ("P/201115/01/2023/018658") AND spaced numeric formats ("2805 2035 4927 4303 001")
    for m_row in re.finditer(
        r"(?m)^([A-Z0-9][A-Z0-9/\-\s]{7,34})\r?\n\s*\d{2}\-[A-Za-z]{3}\-(?:19|20)\d{2}\b",
        blk,
        re.I,
    ):
        cand = m_row.group(1).strip()
        if re.search(r"(?i)\b(?:Expiry|Policy|Number|Date|First|Insurer|Enrollment)\b", cand):
            continue
        cand = re.sub(r"\s+", "", cand)
        if re.search(r"\d{6,}", cand) and cand != current_pol:
            return cand

    return ""


def parse_care_supreme(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "CARE SUPREME"
    data["sub_type"] = "MEDICLAIM"

    # 1. Policy Number
    for pat in [
        r"(?i)Policy\s*No\.?\s*[:\-]?\s*[\r\n\s]*([0-9]{7,18})\b",
        r"(?i)Policy\s*Number\s*[:\-]?\s*[\r\n\s]*([0-9]{7,18})\b",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            data["policy_number"] = m_pol.group(1).strip()
            break

    # 2. Client Name
    for pat in [
        r"(?i)Dear\s+([^\r\n,]{3,80})",
        r"(?i)Policyholder\s*[\r\n]+\s*(?:Gender\s*[\r\n]+\s*)?Date\s*Of\s*Birth\s*[\r\n]+\s*Client\s*ID\s*[\r\n]+\s*([^\r\n]{3,80})",
        r"(?i)Policy\s*Certificate\s*[\r\n]+\s*([^\r\n]{3,80})",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1))
            if cand and len(cand) >= 3 and cand not in ("CUSTOMER", "SIR", "MADAM"):
                data["client_name"] = cand
                break

    # 3. Agency (Intermediary Details -> Name -> Code -> Contact Details -> SONAL LADDHA)
    m_ag = re.search(
        r"(?i)Intermediary\s*Details\s*[\r\n]+\s*Name\s*[\r\n]+\s*Code\s*[\r\n]+\s*Contact\s*Details\s*[\r\n]+\s*([^\r\n]{2,80})",
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
    m_st = re.search(rf"(?i)Policy\s*Period\s*[\-\u2013]\s*Start\s*Date[\s\S]{{0,45}}?{date_tok}", pdf_text)
    m_en = re.search(rf"(?i)Policy\s*Period\s*[\-\u2013]\s*End\s*Date[\s\S]{{0,45}}?{date_tok}", pdf_text)
    if m_st:
        data["start_dt"] = parse_any_date(m_st.group(1))
    if m_en:
        data["end_dt"] = parse_any_date(m_en.group(1))
    if not data["start_dt"] or not data["end_dt"]:
        m_ack = re.search(rf"(?i){date_tok}\s+to\s+{date_tok}", pdf_text)
        if m_ack:
            data["start_dt"] = data["start_dt"] or parse_any_date(m_ack.group(1))
            data["end_dt"] = data["end_dt"] or parse_any_date(m_ack.group(2))

    # 5. Sum Insured
    for pat in [
        r"(?i)\b1\s*[\r\n]+\s*Sum\s*Insured\s*[\r\n]+\s*(?:Rs\.?|INR|₹)?\s*([\d,]{5,15}(?:\.\d{2})?)\b",
        r"(?i)Sum\s*Insured\s*[:\-]?\s*[\r\n]+\s*(?:Rs\.?|INR|₹)?\s*([\d,]{5,15}(?:\.\d{2})?)\b",
    ]:
        m_si = re.search(pat, pdf_text)
        if m_si:
            amt = clean_amount(m_si.group(1))
            if amt.isdigit() and int(amt) >= 100000:
                data["sum_insured"] = amt
                break

    # 6. Total Premium (with GST)
    for pat in [
        r"(?i)Premium\s*Paid\s*[\r\n]+\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)rounded\s+off\s+to\s+the\s+nearest\s+rupee\.?\s*[\r\n]+\s*([\d,]+(?:\.\d+)?)\s*[\r\n]+\s*Total\b",
        r"(?i)Total\s*Premium\s*[:\-]?\s*[\r\n\s]*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            amt = clean_amount(m_p.group(1))
            if amt.isdigit() and int(amt) > 0:
                data["premium"] = amt
                break

    # 7. Previous Policy Number (from Portability Details table OR Previous Policy No.)
    port_pyp = _extract_care_portability_pyp(pdf_text, data["policy_number"])
    if port_pyp:
        data["pyp_number"] = port_pyp
    else:
        m_pyp = re.search(r"(?i)Previous\s*Policy\s*(?:No\.?|Number)\s*[:\-]?\s*[\r\n\s]*([A-Z0-9/\-]{7,30})\b", pdf_text)
        if m_pyp and re.search(r"\d{6,}", m_pyp.group(1)) and m_pyp.group(1).strip() != data["policy_number"]:
            data["pyp_number"] = m_pyp.group(1).strip()

    # 8. DOB (Oldest Insured Person from Details of Insured Person)
    dobs = []
    m_ins = re.search(
        r"(?i)Details\s+of\s+Insured\s+Person([\s\S]{0,2200}?)(?:Medical\s+History|Nominee\s+Details|Contact\s+details|Intermediary\s+Details|$)",
        pdf_text,
    )
    if m_ins:
        for m_d in re.finditer(
            r"(?i)(?:MEMBER|SELF|SPOUSE|FATHER|MOTHER|SON|DAUGHTER|BROTHER|SISTER)\s*[\r\n]+\s*(\d{2}\-[A-Za-z]{3}\-(?:19|20)\d{2})",
            m_ins.group(1),
        ):
            dt = parse_any_date(m_d.group(1))
            if dt and dt.year >= 1920:
                dobs.append(dt)
    if not dobs:
        for m_d in re.finditer(r"(\d{2}\-[A-Za-z]{3}\-(?:19|20)\d{2})\s*[\r\n]+\s*(?:MEMBER|SELF|SPOUSE|FATHER|MOTHER|SON|DAUGHTER)\b", pdf_text, re.I):
            dt = parse_any_date(m_d.group(1))
            if dt and dt.year >= 1920:
                dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    # 9. Premium Mode
    data["premium_mode"] = extract_premium_mode(pdf_text)
    return data
