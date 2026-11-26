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


def is_national_mediclaim(pdf_text: str) -> bool:
    if re.search(r"(?i)Parivar\s+Mediclaim", pdf_text):
        return False
    return bool(
        re.search(r"(?i)National\s+Mediclaim\s+Policy", pdf_text)
        or re.search(r"(?i)NICHLIP25036V", pdf_text)
    )


def parse_national_mediclaim(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "MEDICLAIM"
    data["sub_type"] = "MEDICLAIM"

    # 1. Policy Number
    for pat in [
        r"(?i)Policy\s*Number\s*[:\-]\s*[\r\n\s]*([0-9]{15,24})",
        r"(?i)Policy\s*No\.?\s*[:\-]?\s*[\r\n\s]*([0-9]{15,24})",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            data["policy_number"] = m_pol.group(1).strip()
            break

    # 2. Client Name (strips leading "_" like "_ PRAKASH  SURYAVANSHI")
    for pat in [
        r"(?i)Customer\s*Name\s*[:\-]\s*([^\r\n]{3,80})",
        r"(?i)Details\s*Of\s*Receiver\s*[:\-]\s*([^\r\n]{3,80})",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            raw = re.sub(r"^[\s_.]+", "", m_nm.group(1))
            cand = clean_person_name(raw)
            if cand and len(cand) >= 3:
                data["client_name"] = cand
                break

    # 3. Agency (bilingual Sales Channel Details -> "नाम /Name: Mr Sumit Maheshwari")
    m_sc = re.search(r"(?i)Sales\s*Channel\s*Details([\s\S]{0,350})", pdf_text)
    if m_sc:
        m_ag = re.search(r"(?i)Name\s*[:\-]\s*([^\r\n]{3,80})", m_sc.group(1))
        if m_ag:
            raw = re.split(r"(?i)(?:संपकर|Contact\s*Number|Mobile|Phone|Code)", m_ag.group(1))[0]
            cand = clean_person_name(raw)
            if cand and len(cand) >= 2:
                data["agency"] = shorten_agency_name(cand)

    # 4. Inception & Expiry Dates
    date_tok = r"(\d{2}[/\-]\d{2}[/\-]\d{2,4})"
    m_per = re.search(
        rf"(?i)Policy\s*Effective\s*from\s*:?[\s\S]{{0,30}}?{date_tok}[\s\S]{{0,30}}?to\s*(?:midnight\s*of\s*)?{date_tok}",
        pdf_text,
    )
    if not m_per:
        m_per = re.search(rf"(?i)for\s+the\s+period\s+from\s+{date_tok}\s+to\s+{date_tok}", pdf_text)
    if m_per:
        data["start_dt"] = parse_any_date(m_per.group(1))
        data["end_dt"] = parse_any_date(m_per.group(2))

    # 5. Sum Insured
    m_cis = re.search(r"(?i)Name\s+of\s+the\s+Insured\s+Person\s*[\r\n]+\s*Sum\s+Insured[\s\S]{0,120}?[\r\n]+\s*([\d,]{5,15})", pdf_text)
    if m_cis:
        data["sum_insured"] = clean_amount(m_cis.group(1))
    else:
        m_ins_si = re.search(r"(?i)(?:Male|Female)\s*[\r\n]+\s*([\d,]{5,15})", pdf_text)
        if m_ins_si:
            data["sum_insured"] = clean_amount(m_ins_si.group(1))

    # 6. Total Premium
    for pat in [
        r"(?i)Total\s*Amount\s*[\r\n]+\s*[`₹Rs.\s]*([\d,]+(?:\.\d+)?)",
        r"(?i)Total\s*Premium\s*[\r\n]+\s*[`₹Rs.\s]*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    # 7. PYP Number (latest policy from Previous Policy Number list)
    m_prev_sec = re.search(
        r"(?i)Previous\s*Policy\s*Number\s*and[\s\S]{0,40}?Expiry\s*Date([\s\S]{0,1000}?)(?:Rupees|Government\s+Subsidy|Details\s+of\s+Insured|$)",
        pdf_text,
    )
    if m_prev_sec:
        prev_pols = re.findall(r"\b(\d{15,24})\b", m_prev_sec.group(1))
        if prev_pols:
            data["pyp_number"] = prev_pols[-1]

    # 8. DOB (Oldest Insured Person)
    dobs = []
    for m_d in re.finditer(r"\b(\d{2}/\d{2}/(?:19|20)\d{2})\-\d{1,3}\b", pdf_text):
        dt = parse_any_date(m_d.group(1))
        if dt and dt.year >= 1920:
            dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    # 9. Premium Mode
    data["premium_mode"] = extract_premium_mode(pdf_text)
    return data
