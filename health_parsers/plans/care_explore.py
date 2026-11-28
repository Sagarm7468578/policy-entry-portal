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


def is_care_explore(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)Policy\s+Certificate\s*[\-\u2013]\s*EXPLORE|Datasheet\s*[\-\u2013]\s*['\"]?EXPLORE", pdf_text)
        or re.search(r"(?i)RHITIOP\d+V|CHITIOP\d+V|CHITIOA\d+V", pdf_text)
        or (re.search(r"(?i)Care\s+Health\s+Insurance", pdf_text) and re.search(r"(?i)\bExplore\s+(?:Gold|Silver|Platinum|Asia|Canada|Europe|WW)\b", pdf_text))
    )


def parse_care_explore(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "EXPLORE"
    data["sub_type"] = "TRAVEL INSURANCE"

    # 1. Policy / Certificate Of Insurance No.
    for pat in [
        r"(?i)Certificate\s*Of\s*Insurance\s*No\.?\s*[:\-]?\s*[\r\n\s]*([A-Z0-9/\-]{6,24})\b",
        r"(?i)Policy\s*No\.?\s*[:\-]?\s*[\r\n\s]*([A-Z0-9/\-]{6,24})\b",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol and re.search(r"\d{6,}", m_pol.group(1)):
            data["policy_number"] = m_pol.group(1).strip()
            break

    # 2. Client Name
    for pat in [
        r"(?i)Dear\s+([^\r\n,]{3,80})",
        r"(?i)Policy\s+Certificate\s*[\-\u2013]\s*EXPLORE[\s\S]{0,450}?\r?\n((?:MR|MRS|MS|MISS|DR|SMT|SHRI)\.?\s+[A-Za-z .]{3,70})\r?\n",
        r"(?i)Details\s+of\s+Insured[\s\S]{0,180}?\r?\n([A-Za-z][A-Za-z .]{2,60})\r?\n(?:MEMBER|SELF|PROPOSER)\b",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1))
            if cand and len(cand) >= 3 and cand not in ("CUSTOMER", "SIR", "MADAM"):
                data["client_name"] = cand
                break

    # 3. Agency (Intermediary Details -> Name / Code / Contact Details -> TANISHQ KHETPAL)
    m_ag = re.search(
        r"(?i)Intermediary\s*Details\s*[\r\n]+\s*Name\s*[\r\n]+\s*Code\s*[\r\n]+\s*Contact\s*Details\s*[\r\n]+\s*([^\r\n]{2,80})",
        pdf_text,
    )
    if not m_ag:
        m_ag = re.search(r"(?i)Intermediary\s*Name\s*[:\-]\s*([^\r\n]{2,80})", pdf_text)
    if m_ag:
        cand = shorten_agency_name(clean_person_name(m_ag.group(1)))
        if cand:
            data["agency"] = cand

    # 4. Inception & Expiry Dates
    date_tok = r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})"
    m_st = re.search(rf"(?i)Policy\s*Period\s*[\-\u2013]\s*Start\s*Date[\s\S]{{0,45}}?{date_tok}", pdf_text)
    m_en = re.search(rf"(?i)Policy\s*Period\s*[\-\u2013]\s*End\s*Date[\s\S]{{0,45}}?{date_tok}", pdf_text)
    if m_st:
        data["start_dt"] = parse_any_date(m_st.group(1))
    if m_en:
        data["end_dt"] = parse_any_date(m_en.group(1))
    if not data["start_dt"] or not data["end_dt"]:
        m_per = re.search(rf"(?i)From\s+{date_tok}\s+to\s+{date_tok}", pdf_text)
        if m_per:
            data["start_dt"] = data["start_dt"] or parse_any_date(m_per.group(1))
            data["end_dt"] = data["end_dt"] or parse_any_date(m_per.group(2))

    # 5. Sum Insured (Currency-aware: USD 50000 / EUR 50000 / INR 500000)
    m_si = re.search(
        r"(?i)Sum\s*Insured\s*[\r\n\s]*[:\-]?\s*(USD|EUR|GBP|CAD|AUD|SGD|INR|US\s*\$|\$)\s*([\d,]+(?:\.\d{2})?)",
        pdf_text,
    )
    if m_si:
        curr = re.sub(r"\s+", "", m_si.group(1).upper())
        if curr in ("$", "US$"):
            curr = "USD"
        amt = clean_amount(m_si.group(2))
        if amt.isdigit() and int(amt) > 0:
            data["sum_insured"] = amt if curr == "INR" else f"{curr} {amt}"

    # 6. Total Premium (INR)
    for pat in [
        r"(?i)Premium\s*Paid\s*[\r\n\s]*[:\-]?\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Total\s*Premium\s*[\r\n\s]*[:\-]?\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            amt = clean_amount(m_p.group(1))
            if amt.isdigit() and int(amt) > 0:
                data["premium"] = amt
                break

    # 7. DOB (Oldest Insured Person from Details of Insured)
    dobs = []
    for m_d in re.finditer(r"(\d{2}\-[A-Za-z]{3}\-(?:19|20)\d{2})\s*[\r\n\s]+(?:Male|Female)\b", pdf_text, re.I):
        dt = parse_any_date(m_d.group(1))
        if dt and dt.year >= 1920:
            dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    # 8. Premium Mode & Fresh Travel status
    data["premium_mode"] = extract_premium_mode(pdf_text)
    data["pyp_number"] = "FRESH"
    return data
