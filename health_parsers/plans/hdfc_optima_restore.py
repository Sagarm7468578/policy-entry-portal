import re
from health_parsers.common import (
    default_extracted_data,
    parse_any_date,
    fmt_date,
    clean_amount,
    clean_person_name,
    extract_premium_mode,
)


def is_hdfc_optima_restore(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)Optima\s+Restore", pdf_text)
        or re.search(r"(?i)HDFHLIP25012V", pdf_text)
    )


def parse_hdfc_optima_restore(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "OPTIMA RESTORE"
    data["sub_type"] = "MEDICLAIM"

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

    for pat in [
        r"(?i)Base\s*Sum\s*Insured\s*(?:\(\s*`?\s*\))?\s*[\r\n]+\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Sum\s*Insured\s*opted\s*[:\-]?\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_si = re.search(pat, pdf_text)
        if m_si:
            data["sum_insured"] = clean_amount(m_si.group(1))
            break

    for pat in [
        r"(?i)Gross\s*Premium\s*[\r\n]+\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)has\s+paid\s+Rs\.?\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    m_ins = re.search(
        r"(?i)Insured\s+Person\s+Details([\s\S]{0,1400}?)(?:Nominee\s+Details|Premium\s+Calculation|$)",
        pdf_text,
    )
    if m_ins:
        dobs = [
            dt for d_str in re.findall(r"\b\d{2}[/\-]\d{2}[/\-](?:19|20)\d{2}\b", m_ins.group(1))
            if (dt := parse_any_date(d_str)) and dt.year >= 1920
        ]
        if dobs:
            data["dob"] = fmt_date(min(dobs))

    m_pyp = re.search(r"(?i)Previous\s*Policy\s*(?:No\.?|Number)?\s*[:\-]\s*([A-Z0-9/\-]{8,30})", pdf_text)
    if m_pyp and re.search(r"\d{5,}", m_pyp.group(1)):
        data["pyp_number"] = m_pyp.group(1).strip()

    data["premium_mode"] = extract_premium_mode(pdf_text)
    return data
