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
        or re.search(r"(?i)Health\s+Protector\s+Assure", pdf_text)
        or re.search(r"(?i)Product\s*Code\s*[\r\n\s]*[:\-]?\s*(?:FHP|HPA)\b", pdf_text)
        or re.search(r"(?i)IFFHLIP\d+V", pdf_text)
    )


def _format_iffco_agency(raw_name: str) -> str:
    s = re.sub(r"\s+", " ", str(raw_name or "")).strip()
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
        r"(?i)Policy\s*No\.?\s*[\r\n\s]*[:\-]?\s*([A-Z]\d{6,14})\b",
        r"(?i)forming\s+part\s+of\s+Policy\s*No\.?\s*[:\-]\s*([A-Z0-9/\-]{6,24})",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            data["policy_number"] = m_pol.group(1).strip()
            break

    # 2. Client Name
    for pat in [
        r"(?i)Proposer\s*Name\s*[\r\n]+\s*([^\r\n]{3,80})",
        r"(?i)from\s+Proposer\s+([A-Za-z .]{3,80}?)\s+towards\b",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1))
            if cand and len(cand) >= 3:
                data["client_name"] = cand
                break

    # 3. Agency ("HEDA, PRITI" -> "PRITI HEDA")
    m_ag = re.search(
        r"(?i)Intermediary\s*Details\s*[\r\n]+\s*Name\s*[\r\n]+\s*Intermediary\s*Code\s*[\r\n]+\s*Contact\s*No\.?\s*[\r\n]+\s*([^\r\n]{2,80})",
        pdf_text,
    )
    if not m_ag:
        m_ag = re.search(r"(?i)Intermediary\s*Name\s*[:\-]\s*([^\r\n]{2,80})", pdf_text)
    if m_ag:
        data["agency"] = _format_iffco_agency(m_ag.group(1))

    # 4. Inception & Expiry Dates
    date_tok = r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})"
    m_st = re.search(rf"(?i)Start\s*date\s*[\r\n\s]*(?:From\s*)?[\r\n\s]*{date_tok}", pdf_text)
    if m_st:
        data["start_dt"] = parse_any_date(m_st.group(1))
    m_en = re.search(rf"(?i)End\s*date\s*[\r\n\s]*(?:Till\s*Midnight\s*on\s*)?[\r\n\s]*{date_tok}", pdf_text)
    if m_en:
        data["end_dt"] = parse_any_date(m_en.group(1))

    # 5. Sum Insured (handles both Floater FHP & Individual HPA table with US/Indian commas)
    m_si_lbl = re.search(
        r"(?i)(?:Floater|Basic)?\s*Sum\s*Insured\s*(?:\(Rs\.?\))?\s*[:\-]?\s*[\r\n\s]*(?:Rs\.?|INR|₹)?\s*([\d,]{6,15}(?:\.\d{2})?)\b",
        pdf_text,
    )
    if m_si_lbl:
        amt = clean_amount(m_si_lbl.group(1))
        if amt.isdigit() and int(amt) >= 50000:
            data["sum_insured"] = amt

    m_ins_sec = re.search(
        r"(?i)Insured\s+Details([\s\S]{0,3500}?)(?:ABHA\s+Details|CoPayment\s+Option|Total\s+Premium\s+payable|$)",
        pdf_text,
    )
    if not data["sum_insured"] and m_ins_sec:
        m_rel_si = re.search(
            r"(?i)\b(?:SELF|SPOUSE|SON|DAUGHTER|FATHER|MOTHER|WIFE|HUSBAND|CHILD)\s*[\r\n]+\s*([\d,]{5,15}(?:\.\d{2})?)\b",
            m_ins_sec.group(1),
        )
        if m_rel_si:
            amt = clean_amount(m_rel_si.group(1))
            if amt.isdigit() and int(amt) >= 50000:
                data["sum_insured"] = amt

    if not data["sum_insured"]:
        m_prev_si = re.search(
            r"(?i)Insured\s+Previous\s+Policy\s+Details[\s\S]{0,600}?(?:Individual|Floater)\s*[\r\n]+\s*([\d,]{5,15}(?:\.\d{2})?)\b",
            pdf_text,
        )
        if m_prev_si:
            amt = clean_amount(m_prev_si.group(1))
            if amt.isdigit() and int(amt) >= 50000:
                data["sum_insured"] = amt

    # 6. Total Premium
    for pat in [
        r"(?i)Total\s*Value\s*[\r\n]+\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)received\s+an\s+amount\s+of\s+(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Total\s*Premium\s*[\r\n\s]*[:\-]?\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    # 7. PYP Number (First row in "Insured Previous Policy Details")
    m_prev_sec = re.search(
        r"(?i)Insured\s+Previous\s+Policy\s+Details([\s\S]{0,1200}?)(?:Intermediary\s+Details|Policy\s+Servicing|$)",
        pdf_text,
    )
    if m_prev_sec:
        m_pyp = re.search(
            r"\b([A-Z0-9/\-]{6,28})\s*[\r\n]+\s*\d{2}/\d{2}/\d{4}\s*[\r\n]+\s*\d{2}/\d{2}/\d{4}",
            m_prev_sec.group(1),
        )
        if m_pyp and re.search(r"\d{5,}", m_pyp.group(1)):
            data["pyp_number"] = m_pyp.group(1).strip()

    # 8. DOB (Oldest Insured Person)
    dobs = []
    if m_ins_sec:
        for m_d in re.finditer(
            r"(?i)(?:Male|Female|Other)\s*[\r\n\s]+(\d{2}/\d{2}/(?:19|20)\d{2})",
            m_ins_sec.group(1),
        ):
            dt = parse_any_date(m_d.group(1))
            if dt and dt.year >= 1920:
                dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    # 9. Premium Mode
    data["premium_mode"] = extract_premium_mode(pdf_text)
    return data
