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


def is_manipal_cigna_super_top_up(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)ManipalCigna\s+Super\s+Top\s+Up", pdf_text)
        or re.search(r"(?i)MCIHLIP23022V", pdf_text)
    )


def parse_manipal_cigna_super_top_up(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["sub_type"] = "TOP UP"
    if re.search(r"(?i)Super\s+Top\s+Up\s*[\-\s]*Select", pdf_text):
        data["plan_name"] = "SUPER TOP UP SELECT"
    else:
        data["plan_name"] = "SUPER TOP UP PLUS"

    # 1. Policy Number
    for pat in [
        r"(?i)Policy\s*Number\s*[:\-]\s*([A-Z0-9]{10,22})",
        r"(?i)Policy\s*Number\s*[\r\n]+\s*([A-Z0-9]{10,22})",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            data["policy_number"] = m_pol.group(1).strip()
            break

    # 2. Client Name
    for pat in [
        r"(?i)POLICYHOLDER\s*DETAILS\s*:?[\s\S]{0,60}?Name\s*[:\-]\s*([^\r\n]{3,80})",
        r"(?i)Dear\s+([^\r\n,]{3,80})",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1))
            if cand and len(cand) >= 3:
                data["client_name"] = cand
                break

    # 3. Agency (normalizes ManipalCigna typo "Chinchini" -> "CHINCHANI")
    m_ag = re.search(r"(?i)Intermediary\s*Name\s*[:\-]\s*([^\r\n]{3,80})", pdf_text)
    if m_ag:
        cand = shorten_agency_name(clean_person_name(m_ag.group(1)))
        cand = re.sub(r"\bCHINCHINI\b", "CHINCHANI", cand)
        data["agency"] = cand

    # 4. Inception & Expiry Dates
    date_tok = r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})"
    m_st = re.search(rf"(?i)Cover\s*Start\s*Date\s*[\r\n]+\s*{date_tok}", pdf_text)
    if not m_st:
        m_st = re.search(rf"(?i)Policy\s*Period\s*:?[\s\S]{{0,60}}?From\s*:?[\s\S]{{0,30}}?{date_tok}", pdf_text)
    if m_st:
        data["start_dt"] = parse_any_date(m_st.group(1))

    m_en = re.search(rf"(?i)Cover\s*End\s*Date\s*[\r\n]+\s*{date_tok}", pdf_text)
    if not m_en:
        m_en = re.search(rf"(?i)To\s*:\s*[\d:]+\s*hrs\s*on\s*{date_tok}", pdf_text)
    if m_en:
        data["end_dt"] = parse_any_date(m_en.group(1))

    # 5. Sum Insured
    for pat in [
        r"(?i)Sum\s*Insured\s*\(in\s*Rs\.?\)[\s\S]{0,120}?[\r\n]+\s*([\d,]{5,15})",
        r"(?i)Waiting\s*Period\s*Start\s*Date[\s\S]{0,120}?[\r\n]+\s*([\d,]{5,15})(?:\.\d+)?",
    ]:
        m_si = re.search(pat, pdf_text)
        if m_si:
            amt = clean_amount(m_si.group(1))
            if amt.isdigit() and int(amt) >= 100000:
                data["sum_insured"] = amt
                break

    # 6. Total Premium
    for pat in [
        r"(?i)paid\s+the\s+premium\s+of\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Total\s*premium\s*paid\s*\(A\+B\+C\)\s*[\r\n]+\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    # 7. Premium Mode (DIRECTDEBIT -> ONLINE)
    m_pm = re.search(
        r"(?i)Payment\s*Mode\s*[\r\n]+[\s\S]{0,160}?\b(DIRECT\s*DEBIT|ONLINE|UPI|NEFT|RTGS|IMPS|CARD|CHEQUE|CHQ|DD|CASH|ECS|NACH)\b",
        pdf_text,
    )
    if m_pm:
        tok = re.sub(r"\s+", "", m_pm.group(1).upper())
        if tok in ("CHEQUE", "CHQ", "DD"):
            data["premium_mode"] = "CHEQUE"
        elif tok == "CASH":
            data["premium_mode"] = "CASH"
        elif tok in ("ECS", "NACH"):
            data["premium_mode"] = "AUTO DEBIT"
        else:
            data["premium_mode"] = "ONLINE"
    else:
        data["premium_mode"] = extract_premium_mode(pdf_text)

    # 8. DOB (Oldest Insured Member)
    dobs = []
    m_card = re.search(r"(?i)Customer\s*ID\s*[\r\n]+\s*DOB([\s\S]{0,800}?)(?:Valid\s+From|Claims:|$)", pdf_text)
    if m_card:
        for m_d in re.finditer(r"\b(\d{2}\-[A-Za-z]{3}\-(?:19|20)\d{2})\b", m_card.group(1)):
            dt = parse_any_date(m_d.group(1))
            if dt and dt.year >= 1920:
                dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    # 9. PYP Number (ManipalCigna renewals continue with the SAME policy number)
    if data["policy_number"] and re.search(r"(?i)(?:Policy\s*Category\s*[:\-]?\s*[\r\n\s]*Renewal|\bRenewals\b)", pdf_text):
        data["pyp_number"] = data["policy_number"]

    return data
