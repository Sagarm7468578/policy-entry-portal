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


def is_new_india_floater_mediclaim(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)New\s+India\s+Floater\s+Mediclaim", pdf_text)
        or re.search(r"(?i)NIAHLIP25039V|NIAHLIP22026V|NIAHLIP23\d+V", pdf_text)
    )


def parse_new_india_floater_mediclaim(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "NEW INDIA FLOATER MEDICLAIM"
    data["sub_type"] = "MEDICLAIM"

    # 1. Policy Number
    for pat in [
        r"(?i)Current\s*Policy\s*No\.?\s*[\r\n\s]*[:\-]?\s*([0-9]{16,24})\b",
        r"(?i)Policy\s*No\.?\s*[:\-]\s*([0-9]{16,24})\b",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            data["policy_number"] = m_pol.group(1).strip()
            break

    # 2. Client Name
    for pat in [
        r"(?i)Policyholder\s*Name\s*[\r\n]+\s*([^\r\n]{3,80})",
        r"(?i)certify\s+that\s+(?:Mr\.?/Mrs\.?|Mr\.?|Mrs\.?|Ms\.?)\s*([A-Za-z .]{3,80}?)\s+has\s+paid\b",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1))
            if cand and len(cand) >= 3:
                data["client_name"] = cand
                break

    # 3. Agency ("Name of the\nAgent/Intermediary\nMrs. SONAL LADDHA\n(NIAAG00134008)")
    m_ag = re.search(
        r"(?i)Name\s+of\s+the\s*[\r\n\s]+Agent/Intermediary\s*[\r\n]+\s*([^\r\n(]{3,80})",
        pdf_text,
    )
    if m_ag:
        cand = shorten_agency_name(clean_person_name(m_ag.group(1)))
        if cand:
            data["agency"] = cand

    # 4. Inception & Expiry Dates
    date_tok = r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})"
    m_per = re.search(
        rf"(?i)Current\s*Policy\s*Period\s*[\r\n\s]*From\s*:\s*{date_tok}[\s\S]{{0,40}}?To\s*:\s*{date_tok}",
        pdf_text,
    )
    if not m_per:
        m_per = re.search(rf"(?i)for\s+the\s*[\r\n\s]*period\s+{date_tok}[\s\S]{{0,30}}?to\s+{date_tok}", pdf_text)
    if m_per:
        data["start_dt"] = parse_any_date(m_per.group(1))
        data["end_dt"] = parse_any_date(m_per.group(2))

    # 5. Sum Insured
    for pat in [
        r"(?i)Floater\s*Sum\s*Insured\s*[\r\n]+\s*(?:Rs\.?|INR|₹)?\s*([\d,]{5,15})\b",
        r"(?i)Sum\s*Insured\s*[:\-]?\s*[\r\n\s]*(?:Rs\.?|INR|₹)?\s*([\d,]{5,15})\b",
    ]:
        m_si = re.search(pat, pdf_text)
        if m_si:
            amt = clean_amount(m_si.group(1))
            if amt.isdigit() and int(amt) >= 50000:
                data["sum_insured"] = amt
                break

    # 6. Total Premium (Net Premium With GST)
    for pat in [
        r"(?i)Net\s*Premium\s*\(\s*With\s*[\r\n\s]*GST\s*\)\s*[\r\n\s]*([\d,]+(?:\.\d+)?)",
        r"(?i)has\s+paid\s*[`₹Rs.\s]*([\d,]+(?:\.\d+)?)\s+towards\s+premium",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    # 7. PYP Number (Page 1 "Previous Policy No" if not "none", else Page 2 "Previous Year Policy Details")
    m_pyp1 = re.search(r"(?i)Previous\s*Policy\s*No\.?\s*[\r\n]+\s*([A-Z0-9/\-]{6,30})\b", pdf_text)
    if m_pyp1 and re.search(r"\d{6,}", m_pyp1.group(1)):
        data["pyp_number"] = m_pyp1.group(1).strip()

    if not data["pyp_number"]:
        m_prev_tbl = re.search(
            r"(?i)Previous\s+Year\s+Policy\s+Details([\s\S]{0,800}?)(?:Total\s+Gross|Net\s+Premium|$)",
            pdf_text,
        )
        if m_prev_tbl:
            m_pyp2 = re.search(r"\b(\d{10,24})\b", m_prev_tbl.group(1))
            if m_pyp2:
                data["pyp_number"] = m_pyp2.group(1).strip()

    # 8. DOB (Oldest Insured Person)
    dobs = []
    m_ins = re.search(
        r"(?i)Insured\s+Persons?\s+details([\s\S]{0,1600}?)(?:Floater\s+Sum\s+Insured|Optional\s+Cover|$)",
        pdf_text,
    )
    if m_ins:
        for m_d in re.finditer(r"(\d{2}/\d{2}/(?:19|20)\d{2})\s*\(\s*\d{1,3}\s*\)", m_ins.group(1)):
            dt = parse_any_date(m_d.group(1))
            if dt and dt.year >= 1920:
                dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    # 9. Premium Mode
    data["premium_mode"] = extract_premium_mode(pdf_text)
    if not data["premium_mode"] and re.search(r"(?i)QR_RENEWAL|ONLINE|UPI|PORTAL", pdf_text):
        data["premium_mode"] = "ONLINE"
    return data
