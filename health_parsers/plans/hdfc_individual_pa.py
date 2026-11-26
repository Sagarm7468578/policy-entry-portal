import re
from health_parsers.common import (
    default_extracted_data,
    parse_any_date,
    fmt_date,
    clean_amount,
    clean_person_name,
    extract_premium_mode,
)


def is_hdfc_individual_pa(pdf_text: str) -> bool:
    # Ignore Optima Restore / Optima Secure PDFs that only mention "Individual Personal Accident Rider" in footnotes
    if re.search(r"(?i)(?:Optima\s+Restore|Optima\s+(?:Super\s+)?Secure|Koti\s+Suraksha)", pdf_text):
        return False
    return bool(
        re.search(r"(?i)HDHHLIP21346V", pdf_text)
        or re.search(
            r"(?i)(?:Policy\s*Schedule\s*[-–]\s*|Renewal\s+of\s+Your\s+)Individual\s+Personal\s+Accident",
            pdf_text,
        )
    )


def _extract_hdfc_ipa_agency(pdf_text: str) -> str:
    patterns = [
        r"(?i)Intermediary\s*Name\s*[\r\n]+\s*(?:(?:AGENT|BROKER|POSP|IMD|DIRECT|ADVISOR)\s*[:\-]\s*)?([^\r\n]{3,80})",
        r"(?i)(?:AGENT|BROKER|POSP|IMD)\s*[:\-]\s*([A-Za-z][A-Za-z .&/\-]{2,65})",
    ]
    bad_starts = {"intermediary", "code", "contact", "mobile", "phone", "number", "no"}
    for pat in patterns:
        for m in re.finditer(pat, pdf_text):
            raw = m.group(1).strip()
            raw = re.sub(r"(?i)^\s*(?:AGENT|BROKER|POSP|IMD|DIRECT|ADVISOR)\s*[:\-]\s*", "", raw)
            cand = clean_person_name(raw)
            if cand and len(cand) >= 3 and cand.split()[0].lower() not in bad_starts:
                return cand
    return ""


def parse_hdfc_individual_pa(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "PERSONAL ACCIDENT"
    data["sub_type"] = "PERSONAL ACCIDENT"

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

    data["agency"] = _extract_hdfc_ipa_agency(pdf_text)

    date_tok = r"(\d{2}[/\-]\d{2}[/\-]\d{2,4})"
    m_per = re.search(
        rf"(?i)Policy\s*Period[\s\S]{{0,100}}?From[\s\S]{{0,35}}?{date_tok}[\s\S]{{0,45}}?To[\s\S]{{0,35}}?{date_tok}",
        pdf_text,
    )
    if m_per:
        data["start_dt"] = parse_any_date(m_per.group(1))
        data["end_dt"] = parse_any_date(m_per.group(2))

    for pat in [
        r"(?i)Sum\s*Insured\s*opted\s*[:\-]?\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Total\s*Temporary\s*Disablement\s*[\r\n]+\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_si = re.search(pat, pdf_text)
        if m_si:
            data["sum_insured"] = clean_amount(m_si.group(1))
            break

    for pat in [
        r"(?i)Gross\s*Premium\s*[\r\n]+\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Net\s*Premium\s*[\r\n]+\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    m_ins = re.search(
        r"(?i)Insured\s+Persons\s+Details([\s\S]{0,1200}?)(?:Nominee\s+Details|Premium\s+Calculation|$)",
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
