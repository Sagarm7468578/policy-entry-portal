import re
from health_parsers.common import (
    default_extracted_data,
    parse_any_date,
    fmt_date,
    clean_amount,
    clean_person_name,
    extract_premium_mode,
)


def is_hdfc_koti_suraksha(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)Koti\s+Suraksha", pdf_text)
        or re.search(r"(?i)HDFHLIP21131V", pdf_text)
    )


def _extract_koti_payment_mode(pdf_text: str) -> str:
    # Matches "Payment Details : 000245, Bank Name:Bank of Baroda" (6-digit cheque) or BizDirect/Online ref
    m_pd = re.search(r"(?i)Payment\s*Details\s*[:\-]\s*([^\r\n]{3,120})", pdf_text)
    if m_pd:
        seg = m_pd.group(1)
        if re.search(r"(?i)\b(?:BizDirect|Online|UPI|NEFT|RTGS|IMPS|IPG|EPG|PG|Card|OPS[A-Z0-9]{6,})\b", seg):
            return "ONLINE"
        if re.search(r"(?i)\b(?:Cheque|Chq|DD)\b", seg):
            return "CHEQUE"
        if re.search(r"(?<!\d)\d{12,24}(?!\d)", seg):
            return "ONLINE"
        if re.search(r"(?<!\d)\d{6}(?!\d)", seg):
            return "CHEQUE"
    return extract_premium_mode(pdf_text)


def parse_hdfc_koti_suraksha(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "KOTI SURAKSHA"
    data["sub_type"] = "PERSONAL ACCIDENT"

    for pat in [
        r"(?i)Policy\s*No\.?\s*[\r\n\s]*[:\-]\s*([\d\s]{12,30})",
        r"(?i)Policy\s*no\s+([\d]{12,22})",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            digits = re.sub(r"\s+", "", m_pol.group(1))
            if len(digits) >= 12:
                data["policy_number"] = digits
                break

    for pat in [
        r"(?i)Proposer\s*Name\s*[\r\n\s]*[:\-]\s*([^\r\n]{3,80})",
        r"(?i)Dear\s+([^\r\n,]{3,80})",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1))
            if cand and len(cand) >= 3:
                data["client_name"] = cand
                break

    m_ag = re.search(r"(?i)Agent\s*Name\s*[:\-]\s*([^\r\n]{3,70})", pdf_text)
    if m_ag:
        data["agency"] = clean_person_name(m_ag.group(1))

    date_tok = r"(\d{2}[/\-]\d{2}[/\-]\d{2,4})"
    m_per = re.search(
        rf"(?i)Period\s*of\s*Insurance[\s\S]{{0,80}}?From\s*{date_tok}[\s\S]{{0,40}}?To\s*{date_tok}",
        pdf_text,
    )
    if m_per:
        data["start_dt"] = parse_any_date(m_per.group(1))
        data["end_dt"] = parse_any_date(m_per.group(2))

    for pat in [
        r"(?i)Sum\s*Insured\s*opted\s*[:\-]?\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Accidental\s*Death\s*[\r\n]+\s*([\d,]+)(?:/[\d,]+)?",
    ]:
        m_si = re.search(pat, pdf_text)
        if m_si:
            data["sum_insured"] = clean_amount(m_si.group(1))
            break

    for pat in [
        r"(?i)Gross\s*Premium\s*(?:\([^)]*\))?\s*[\r\n]+\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Net\s*Premium\s*(?:\([^)]*\))?\s*[\r\n]+\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    cleaned_dob = re.sub(r"(\b\d{2}[/\-]\d{2}[/\-](?:19|20))[\r\n\s]+(\d{2})\b", r"\1\2", pdf_text)
    m_ins = re.search(
        r"(?i)Insured\s*Person[’'`]?s\s*Details([\s\S]{0,1000}?)(?:Schedule\s*of\s*Coverage|$)",
        cleaned_dob,
    )
    if m_ins:
        dobs = [
            dt for d_str in re.findall(r"\b\d{2}[/\-]\d{2}[/\-](?:19|20)\d{2}\b", m_ins.group(1))
            if (dt := parse_any_date(d_str)) and 1920 <= dt.year <= 2020
        ]
        if dobs:
            data["dob"] = fmt_date(min(dobs))

    data["premium_mode"] = _extract_koti_payment_mode(pdf_text)
    return data
