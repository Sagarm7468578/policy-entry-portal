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


def is_hdfc_sarv_suraksha_plus_group(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)Sarv\s+Suraksha\s+Plus\s*\(\s*Group\s*\)", pdf_text)
        or re.search(r"(?i)HDFHLGP24020V|HDFHLGP21002V", pdf_text)
    )


def parse_hdfc_sarv_suraksha_plus_group(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "SARV SURAKSHA PLUS (GROUP)"
    data["sub_type"] = "PERSONAL ACCIDENT"

    # 1. Certificate / Policy Number
    for pat in [
        r"(?i)Certificate\s*No\.?\s*[\r\n\s]*[:\-]\s*([0-9][0-9 \t]{14,24})",
        r"(?i)policy\s+reference\s+no\.?\s*([0-9]{15,20})\b",
        r"(?i)Policy\s*No\.?\s*[:\-]\s*([0-9]{15,20})\b",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            digits = re.sub(r"\s+", "", m_pol.group(1))
            if 15 <= len(digits) <= 22:
                data["policy_number"] = digits
                break

    # 2. Client Name (Proposer Name — strips leading ":" before clean_person_name)
    for pat in [
        r"(?i)Proposer\s*Name\s*[\r\n]*\s*[:\-]\s*([^\r\n]{3,80})",
        r"(?i)Dear\s+([^\r\n,]{3,80})",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1).lstrip(" :-\t"))
            if cand and len(cand) >= 3 and cand not in ("CUSTOMER", "SIR", "MADAM"):
                data["client_name"] = cand
                break

    # 3. Agency (Broker Name / Intermediary Name)
    for pat in [
        r"(?i)Broker\s*Name\s*[:\-]\s*([^\r\n]{2,90})",
        r"(?i)Intermediary\s*Name\s*[:\-]\s*([^\r\n]{2,90})",
        r"(?i)Master\s*Policy\s*Holder\s*[\r\n\s]*Name\s*[\r\n\s]*[:\-]\s*([^\r\n]{2,90})",
    ]:
        m_ag = re.search(pat, pdf_text)
        if m_ag:
            cand = shorten_agency_name(clean_person_name(m_ag.group(1).lstrip(" :-\t")))
            if cand:
                data["agency"] = cand
                break

    # 4. Inception & Expiry Dates
    date_tok = r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})"
    m_per = re.search(
        rf"(?i)Period\s*of\s*Insurance\s*[\r\n\s]*[:\-]?\s*From\s*{date_tok}[\s\S]{{0,35}}?To\s*{date_tok}",
        pdf_text,
    )
    if m_per:
        data["start_dt"] = parse_any_date(m_per.group(1))
        data["end_dt"] = parse_any_date(m_per.group(2))

    # 5. Sum Insured (Self / highest Sum Insured in Insured Person Details table)
    m_ins = re.search(
        r"(?i)Insured\s+Person\s+Details([\s\S]{0,1800}?)(?:Nominee\s+Details|Schedule\s+of\s+Coverage|$)",
        pdf_text,
    )
    if m_ins:
        amts = [
            int(clean_amount(m.group(1)))
            for m in re.finditer(r"(?:\d{2}/\d{2}/\d{4})\s*[\r\n]+\s*([\d,]{5,12})\s*[\r\n]+\s*(?:YES|NO)\b", m_ins.group(1), re.I)
            if clean_amount(m.group(1)).isdigit()
        ]
        amts = [a for a in amts if a >= 50000]
        if amts:
            data["sum_insured"] = str(max(amts))

    # 6. Total Premium (Grand Total - Premium including GST)
    for pat in [
        r"(?i)Grand\s*Total\s*[\-\s]*Premium\s*including\s*GST\s*(?:\([^)]+\))?\s*[\r\n\s]*(?:Rs\.?|INR|₹|`)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Total\s*Premium\s*including\s*GST\s*[\r\n\s]*(?:Rs\.?|INR|₹|`)?\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            amt = clean_amount(m_p.group(1))
            if amt.isdigit() and int(amt) > 0:
                data["premium"] = amt
                break

    # 7. DOB (Oldest Insured Person)
    dobs = []
    if m_ins:
        for m_d in re.finditer(r"(?i)(?:Male|Female)\s*[\r\n\s]+(\d{2}/\d{2}/(?:19|20)\d{2})", m_ins.group(1)):
            dt = parse_any_date(m_d.group(1))
            if dt and dt.year >= 1920:
                dobs.append(dt)
    if not dobs:
        for m_d in re.finditer(r"(\d{2}/\d{2}/(?:19|20)\d{2})\s*[\r\n\s]+(?:Male|Female)\b", pdf_text, re.I):
            dt = parse_any_date(m_d.group(1))
            if dt and dt.year >= 1920:
                dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    # 8. Premium Mode
    data["premium_mode"] = extract_premium_mode(pdf_text)
    return data
