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


def is_aditya_birla_activ_health(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)Activ\s+Health\s*[\-\s]*Policy\s+Schedule", pdf_text)
        or re.search(r"(?i)Product\s*Name\s*[\r\n]+\s*Activ\s+Health\b", pdf_text)
        or re.search(r"(?i)Activ\s+Health\s*,?\s*(?:Product\s*)?UIN\s*[:\-]?\s*ADIHLIP", pdf_text)
        or re.search(r"(?i)ADIHLIP26042V", pdf_text)
    )


def parse_aditya_birla_activ_health(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "ACTIV HEALTH"
    data["sub_type"] = "MEDICLAIM"

    # 1. Policy Number
    for pat in [
        r"(?i)Policy\s*Number\s*[:\-]?\s*[\r\n\s]*([0-9]{2}\-[0-9]{2}\-[0-9A-Z\-]{6,22})",
        r"(?i)POLICY\s*NO\.?\s*[:\-]?\s*([0-9]{2}\-[0-9]{2}\-[0-9A-Z\-]{6,22})",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            data["policy_number"] = m_pol.group(1).strip()
            break

    # 2. Client Name
    for pat in [
        r"(?i)Policyholder\s*Name\s*[\r\n]+\s*([^\r\n]{3,80})",
        r"(?i)Proposer\s*Name\s*[:\-]\s*[\r\n\s]*([^\r\n]{3,80})",
        r"(?i)Dear\s+([^\r\n,]{3,80})",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1))
            if cand and len(cand) >= 3:
                data["client_name"] = cand
                break

    # 3. Previous Policy Number
    m_pyp = re.search(
        r"(?i)Previous\s*Policy\s*Number\s*[\r\n]+\s*([0-9A-Z/\-]{8,30})",
        pdf_text,
    )
    if m_pyp and re.search(r"\d{4,}", m_pyp.group(1)) and m_pyp.group(1).strip().upper() != "NA":
        data["pyp_number"] = m_pyp.group(1).strip()

    # 4. Agency
    m_ag = re.search(
        r"(?i)Intermediary\s*[\r\n]+\s*Name\s*[\r\n]+\s*([^\r\n]{3,80})",
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
    for pat in [
        rf"(?i)Start\s*Date\s*of\s*Policy(?:\s*&\s*Time)?\s*[:\-]?\s*[\r\n\s]*(?:[\d:]+\s*hrs?\s*on\s*)?{date_tok}",
        rf"(?i)Policy\s*Start\s*Date\s*[:\-]?\s*[\r\n\s]*(?:[\d:]+\s*hrs?\s*on\s*)?{date_tok}",
    ]:
        m_st = re.search(pat, pdf_text)
        if m_st:
            data["start_dt"] = parse_any_date(m_st.group(1))
            if data["start_dt"]:
                break

    for pat in [
        rf"(?i)Expiry\s*Date\s*(?:&\s*Time\s*)?of\s*Policy\s*[:\-]?\s*[\r\n\s]*(?:[\d:]+\s*hrs?\s*on\s*)?{date_tok}",
        rf"(?i)Policy\s*End\s*Date\s*[:\-]?\s*[\r\n\s]*(?:[\d:]+\s*hrs?\s*on\s*)?{date_tok}",
    ]:
        m_en = re.search(pat, pdf_text)
        if m_en:
            data["end_dt"] = parse_any_date(m_en.group(1))
            if data["end_dt"]:
                break

    # 6. Base Sum Insured (handles Family Floater & Individual tables with wrapped dates like "23/08/20\n26")
    m_cov_sec = re.search(
        r"(?i)Applicability\s+of\s+Chronic\s+Management\s+Program([\s\S]{0,1600}?)(?:Inbuilt\s+Premiere|Optional\s+Covers|$)",
        pdf_text,
    )
    if m_cov_sec:
        sec_joined = re.sub(r"(\d{2}/\d{2}/\d{2})\s*[\r\n]+\s*(\d{2})\b", r"\1\2", m_cov_sec.group(1))
        for pat in [
            r"([\d,]{5,15})\s*[\r\n]+\s*Zone\s*(?:I{1,3}V?|\d)",
            r"\d{2}/\d{2}/\d{4}\s*[\r\n]+\s*([\d,]{5,15})",
        ]:
            m_si = re.search(pat, sec_joined, re.I)
            if m_si:
                amt = clean_amount(m_si.group(1))
                if amt.isdigit() and int(amt) >= 50000:
                    data["sum_insured"] = amt
                    break

    if not data["sum_insured"]:
        m_si_fl = re.search(r"(?i)Family\s*Floater\s*Sum\s*Insured[\s\S]{0,80}?[\r\n]+\s*([\d,]{5,15})", pdf_text)
        if m_si_fl:
            amt = clean_amount(m_si_fl.group(1))
            if amt.isdigit() and int(amt) >= 50000:
                data["sum_insured"] = amt

    # 7. Total Premium
    for pat in [
        r"(?i)receipt\s+of\s+premium\s+amount\s+of\s*(?:INR|Rs\.?|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Total\s*Premium\s*Paid[\s\S]{0,120}?([\d,]+(?:\.\d+)?)\s*[\r\n]+\s*0\s*[\r\n]+\s*Mode\s*of\s*Premium",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break
    if not data["premium"]:
        m_tbl = re.search(r"(?i)VIII\.\s*Premium\s*Details([\s\S]{0,400}?)(?:GST\s*Registration|$)", pdf_text)
        if m_tbl:
            nums = re.findall(r"\b(\d[\d,]*\.\d{2})\b", m_tbl.group(1))
            if nums:
                data["premium"] = clean_amount(nums[-1])

    # 8. DOB (Oldest Insured Person)
    dobs = []
    m_ins = re.search(r"(?i)III\.\s*Insured\s*Person'?s\s*Details([\s\S]{0,2000}?)(?:Applicability\s+of\s+Chronic|Inbuilt\s+Premiere|$)", pdf_text)
    if m_ins:
        for m_d in re.finditer(r"(?:Male|Female|Other)\s*[\r\n\s]+(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-](?:19|20)\d{2})", m_ins.group(1), re.I):
            dt = parse_any_date(m_d.group(1))
            if dt and dt.year >= 1920:
                dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    # 9. Premium Mode
    data["premium_mode"] = extract_premium_mode(pdf_text)
    return data
