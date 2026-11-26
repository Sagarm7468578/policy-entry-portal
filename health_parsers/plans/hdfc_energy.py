import re
from health_parsers.common import (
    default_extracted_data,
    parse_any_date,
    fmt_date,
    clean_amount,
    clean_person_name,
    extract_premium_mode,
)


def is_hdfc_energy(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)Energy\s*\(\s*(?:Silver|Gold)\s*\)", pdf_text)
        or re.search(r"(?i)Policy\s*Schedule\s*[-–]\s*Energy", pdf_text)
        or re.search(r"(?i)HDFHLIP26048V", pdf_text)
    )


def parse_hdfc_energy(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["sub_type"] = "MEDICLAIM"

    m_var = re.search(r"(?i)Energy\s*\(\s*(Silver|Gold)\s*\)", pdf_text)
    data["plan_name"] = f"ENERGY ({m_var.group(1).upper()})" if m_var else "ENERGY"

    # 1. Policy Number
    for pat in [
        r"(?i)Policy\s*No\.?\s*[:\-]\s*([\d\s]{12,30})",
        r"(?i)Policy\s*Number\s*[\r\n]+\s*([\d\s]{12,30})",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            digits = re.sub(r"\s+", "", m_pol.group(1))
            if len(digits) >= 12:
                data["policy_number"] = digits
                break

    # 2. Client Name
    for pat in [
        r"(?i)Policy\s*Holder[’'`]?s\s*Name\s*[\r\n]+\s*([^\r\n]{3,80})",
        r"(?i)Dear\s+([^\r\n,]{3,80})",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1))
            if cand and len(cand) >= 3:
                data["client_name"] = cand
                break

    # 3. Agency ("AGENT : Suresh Kumar Chinchani")
    for pat in [
        r"(?i)Intermediary\s*Name\s*[\r\n]+\s*(?:(?:AGENT|BROKER|POSP|IMD|DIRECT|ADVISOR)\s*[:\-]\s*)?([^\r\n]{3,80})",
        r"(?i)(?:AGENT|BROKER|POSP|IMD)\s*[:\-]\s*([A-Za-z][A-Za-z .&/\-]{2,65})",
    ]:
        m_ag = re.search(pat, pdf_text)
        if m_ag:
            raw = re.sub(r"(?i)^\s*(?:AGENT|BROKER|POSP|IMD|DIRECT|ADVISOR)\s*[:\-]\s*", "", m_ag.group(1).strip())
            cand = clean_person_name(raw)
            if cand and len(cand) >= 3 and cand.split()[0].lower() not in {"intermediary", "code", "contact"}:
                data["agency"] = cand
                break

    # 4. Policy Period
    date_tok = r"(\d{2}[/\-]\d{2}[/\-]\d{2,4})"
    m_per = re.search(
        rf"(?i)Policy\s*Period[\s\S]{{0,100}}?From[\s\S]{{0,35}}?{date_tok}[\s\S]{{0,45}}?To[\s\S]{{0,35}}?{date_tok}",
        pdf_text,
    )
    if not m_per:
        m_per = re.search(rf"(?i)for\s+period\s+of\s+{date_tok}\s+to\s+{date_tok}", pdf_text)
    if m_per:
        data["start_dt"] = parse_any_date(m_per.group(1))
        data["end_dt"] = parse_any_date(m_per.group(2))

    # 5. Sum Insured
    for pat in [
        r"(?i)Sum\s*Insured\s*opted\s*[:\-]?\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)\(\s*\d{1,2}\s*[\r\n]*\d?\s*\)\s*[\r\n]+\s*([\d,]{5,12})",
    ]:
        m_si = re.search(pat, pdf_text)
        if m_si:
            data["sum_insured"] = clean_amount(m_si.group(1))
            break

    # 6. Premium
    for pat in [
        r"(?i)Gross\s*Premium\s*[\r\n]+\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)has\s+paid\s+Rs\.?\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    # 7. DOB
    m_ins = re.search(
        r"(?i)Insured\s+Persons\s+Details([\s\S]{0,1200}?)(?:Nominee\s+Details|Premium\s+Calculation|$)",
        pdf_text,
    )
    dobs = []
    if m_ins:
        for d_str in re.findall(r"\b\d{2}[/\-]\d{2}[/\-](?:19|20)\d{2}\b", m_ins.group(1)):
            dt = parse_any_date(d_str)
            if dt and dt.year >= 1920:
                dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    # 8. PYP Number (if present)
    m_pyp = re.search(r"(?i)Previous\s*Policy\s*(?:No\.?|Number)?\s*[:\-]\s*([A-Z0-9/\-]{8,30})", pdf_text)
    if m_pyp and re.search(r"\d{5,}", m_pyp.group(1)):
        data["pyp_number"] = m_pyp.group(1).strip()

    # 9. Premium Mode
    data["premium_mode"] = extract_premium_mode(pdf_text)
    return data
