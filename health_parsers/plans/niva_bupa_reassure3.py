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


def is_niva_bupa_reassure3(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)ReAssure\s*3\.0", pdf_text)
        or re.search(r"(?i)NBHHLIP26047V", pdf_text)
    )


def parse_niva_bupa_reassure3(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "REASSURE 3.0"
    data["sub_type"] = "MEDICLAIM"

    # 1. Policy Number
    for pat in [
        r"(?i)Policy\s*Number\s*[:\-]?\s*[\r\n\s]*([0-9]{10,20})",
        r"(?i)Policy\s*No\.?\s*[:\-]?\s*([0-9]{10,20})",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            data["policy_number"] = m_pol.group(1).strip()
            break

    # 2. Client Name
    for pat in [
        r"(?i)Policyholder\s*Name\s*[:\-]?\s*[\r\n\s]*([^\r\n]{3,80})",
        r"(?i)Dear\s+([^\r\n,]{3,80})",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1))
            if cand and len(cand) >= 3:
                data["client_name"] = cand
                break

    # 3. Portability / Previous Policy Number
    for pat in [
        r"(?i)intimate\s+you\s+that\s+your\s+policy\s*[\r\n\s]+([A-Z0-9/\-]{6,35})\s+of\b",
        r"(?i)Previous\s*Policy\s*(?:No\.?|Number)\s*[:\-]?\s*([A-Z0-9/\-]{6,35})",
    ]:
        m_pyp = re.search(pat, pdf_text)
        if m_pyp and re.search(r"\d{4,}", m_pyp.group(1)):
            data["pyp_number"] = m_pyp.group(1).strip()
            break

    # 4. Agency
    m_ag = re.search(
        r"(?i)Intermediary\s*Name\s*[\r\n]+\s*Intermediary\s*Code\s*[\r\n]+\s*Intermediary\s*Contact\s*No\.?\s*[\r\n]+\s*([^\r\n]{3,80})",
        pdf_text,
    )
    if not m_ag:
        m_ag = re.search(r"(?i)Intermediary\s*Name\s*[:\-]\s*([^\r\n]{3,80})", pdf_text)
    if m_ag:
        cand = clean_person_name(m_ag.group(1))
        if cand and len(cand) >= 2:
            data["agency"] = shorten_agency_name(cand)

    # 5. Inception & Expiry Dates
    date_tok = r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})"
    m_st = re.search(rf"(?i)Policy\s*Commencement\s*Date(?:\s*and\s*Time)?\s*#?\s*[\r\n\s]*(?:From\s*)?{date_tok}", pdf_text)
    if m_st:
        data["start_dt"] = parse_any_date(m_st.group(1))
    m_en = re.search(rf"(?i)Policy\s*Expiry\s*Date(?:\s*and\s*Time)?\s*[\r\n\s]*(?:To\s*)?{date_tok}", pdf_text)
    if m_en:
        data["end_dt"] = parse_any_date(m_en.group(1))

    # 6. Sum Insured ("Unlimited" or numeric INR amount)
    m_si = re.search(r"(?i)Base\s*Sum\s*Insured\s*[\r\n\s]*(Unlimited|(?:INR|Rs\.?|₹)?\s*[\d,]{5,15})", pdf_text)
    if m_si:
        val_si = m_si.group(1).strip()
        data["sum_insured"] = "UNLIMITED" if val_si.lower() == "unlimited" else clean_amount(re.sub(r"(?i)(?:INR|Rs\.?|₹)", "", val_si))

    # 7. Gross Premium
    for pat in [
        r"(?i)Gross\s*Premium\s*(?:\(INR\)|\(Rs\.?\))?\s*[\r\n]+\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Net\s*Premium\s*/\s*Taxable\s*value\s*\(Rs\.?\)\s*[\r\n]+\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    # 8. DOB (Oldest Insured Person)
    dobs = []
    m_ins = re.search(r"(?i)Insured\s+Person\s+Details([\s\S]{0,1600}?)(?:Permanent\s+Exclusion|Pre\s*-\s*Existing|$)", pdf_text)
    if m_ins:
        for m_d in re.finditer(r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-](?:19|20)\d{2})\s*[\r\n\s]+(?:Male|Female|Other)", m_ins.group(1), re.I):
            dt = parse_any_date(m_d.group(1))
            if dt and dt.year >= 1920:
                dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    # 9. Premium Mode
    data["premium_mode"] = extract_premium_mode(pdf_text)
    return data
