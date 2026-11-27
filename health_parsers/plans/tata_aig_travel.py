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


def is_tata_aig_travel(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)TATA\s+AIG\s+Travel\s+Insurance", pdf_text)
        or re.search(r"(?i)TATTIO[PA]\d+", pdf_text)
    )


def parse_tata_aig_travel(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "TRAVEL"
    data["sub_type"] = "TRAVEL INSURANCE"

    # 1. Policy Number (International Plus + Student Travel)
    for pat in [
        r"(?i)Policy\s*(?:Certificate\s*)?(?:No\.?|Number)\s*[:\-]?\s*[\r\n\s]*([0-9]{8,16})\b",
        r"(?i)Policy\s*Number\s*[:\-]?\s*[\r\n\s]*([A-Z0-9/\-]{8,24})",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol and re.search(r"\d{6,}", m_pol.group(1)):
            data["policy_number"] = m_pol.group(1).strip()
            break

    # 2. Client Name (Policyholder / Policy Holder / Proposer Name)
    for pat in [
        r"(?i)Policy\s*Holder\s*[\r\n\s]+Name\s*[:\-]?\s*[\r\n\s]*([^\r\n]{3,80})",
        r"(?i)Proposer\s*Name\s*[:\-]?\s*[\r\n\s]*([^\r\n]{3,80})",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1))
            if cand and len(cand) >= 3 and "CONTACT" not in cand:
                data["client_name"] = cand
                break

    # 3. Agency (International Plus 3-col table + Student Travel)
    m_ag_tbl = re.search(
        r"(?i)Agent\s*/\s*Intermediary\s*Name\s*[\r\n]+\s*Agent\s*/\s*Intermediary\s*License[\r\n\s]*Code\s*[\r\n]+\s*Agent\s*/\s*Intermediary\s*Contact\s*No\.?\s*[\r\n]+\s*([^\r\n]{3,80})",
        pdf_text,
    )
    if not m_ag_tbl:
        m_ag_tbl = re.search(
            r"(?i)Intermediary\s*/\s*Agent\s*Name\s*[\r\n]+\s*Intermediary\s*/\s*Agent\s*Code\s*[\r\n]+\s*Intermediary\s*/\s*Agent\s*Contact\s*No\.?\s*[\r\n]+\s*([^\r\n]{3,80})",
            pdf_text,
        )
    if m_ag_tbl:
        cand = clean_person_name(m_ag_tbl.group(1))
        if cand and len(cand) >= 2:
            data["agency"] = shorten_agency_name(cand)
    else:
        for pat in [
            r"(?i)Agent\s*/\s*Intermediary\s*Name\s*[:\-]?\s*[\r\n]+\s*([^\r\n]{3,80})",
            r"(?i)Producer\s*Name\s*[:\-]\s*([^\r\n]{3,80})",
            r"(?i)(?:Intermediary|Agent)\s*Name\s*[:\-]\s*([^\r\n]{3,80})",
        ]:
            m_ag = re.search(pat, pdf_text)
            if m_ag and not re.search(r"(?i)License|Code|Contact", m_ag.group(1)):
                cand = clean_person_name(m_ag.group(1))
                if cand and len(cand) >= 2:
                    data["agency"] = shorten_agency_name(cand)
                    break

    # 4. Inception & Expiry Dates (International Plus + Student Travel)
    date_tok = r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})"
    m_td = re.search(
        rf"(?i)Travel\s*Dates\s*[\r\n\s]*From\s*[:\-]?\s*[\r\n\s]*{date_tok}[\s\S]{{0,30}}?To\s*[:\-]?\s*[\r\n\s]*{date_tok}",
        pdf_text,
    )
    if m_td:
        data["start_dt"] = parse_any_date(m_td.group(1))
        data["end_dt"] = parse_any_date(m_td.group(2))

    if not data["start_dt"]:
        for pat in [
            rf"(?i)Policy\s*Period\s*Start\s*Date\s*[:\-]?\s*[\r\n\s]*{date_tok}",
            rf"(?i)Trip\s*Duration\s*[\r\n\s]*From\s*[:\-]?\s*[\r\n\s]*{date_tok}",
            rf"(?i)Departure\s*(?:from\s*India|Date)\s*[:\-]\s*[\r\n\s]*{date_tok}",
        ]:
            m_st = re.search(pat, pdf_text)
            if m_st:
                data["start_dt"] = parse_any_date(m_st.group(1))
                if data["start_dt"]:
                    break

    if not data["end_dt"]:
        for pat in [
            rf"(?i)Policy\s*Period\s*End\s*Date\s*[:\-]?\s*[\r\n\s]*{date_tok}",
            rf"(?i)Trip\s*Duration[\s\S]{{0,40}}?To\s*[:\-]?\s*[\r\n\s]*{date_tok}",
            rf"(?i)(?:Return\s*to\s*India|Duration\s*plan\s*required\s*for)\s*[:\-]\s*[\r\n\s]*{date_tok}",
        ]:
            m_en = re.search(pat, pdf_text)
            if m_en:
                data["end_dt"] = parse_any_date(m_en.group(1))
                if data["end_dt"]:
                    break

    # 5. Sum Insured
    for pat in [
        r"(?i)(?:Medical\s*)?Sum\s*Insured\s*[:\-]?\s*[\r\n\s]*(?:USD|\$)\s*([\d,]{4,12})",
        r"(?i)Unlimited\s*Sum\s*Insured\s*with\s*(?:USD|\$)\s*([\d,]{4,12})",
        r"(?i)(?:Accident\s*&\s*Sickness\s*)?Medical\s*Expenses[\s\S]{0,80}?(?:USD|\$)\s*([\d,]{4,12})",
    ]:
        m_si = re.search(pat, pdf_text)
        if m_si:
            data["sum_insured"] = f"USD {clean_amount(m_si.group(1))}"
            break

    # 6. Total Premium
    for pat in [
        r"(?i)Final\s*Premium\s*[:\-]?\s*[\r\n\s]*(?:Rs\.?|INR|₹)?\s*[\r\n\s]*([\d,]+(?:\.\d+)?)",
        r"(?i)Total\s*Premium\s*(?:Payable|Paid)?\s*[:\-]?\s*[\r\n\s]*(?:Rs\.?|INR|₹)?\s*[\r\n\s]*([\d,]+(?:\.\d+)?)",
        r"(?i)Premium\s*:\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    # 7. DOB (Insured Person DOB — ignores Sponsor DOB on Student Travel)
    dobs = []
    m_ins = re.search(r"(?i)Insured\s+Person\s+Details\s*:?([\s\S]{0,900}?)(?:Nominee\s+Details|$)", pdf_text)
    if m_ins:
        for m_d in re.finditer(r"(?:Male|Female)\s*[\r\n\s]+(\d{2}[/\-]\d{2}[/\-](?:19|20)\d{2})", m_ins.group(1), re.I):
            dt = parse_any_date(m_d.group(1))
            if dt and dt.year >= 1920:
                dobs.append(dt)
    if not dobs:
        m_stu = re.search(
            r"(?i)Student\s*Name\s*[:\-][\s\S]{0,120}?Date\s*Of\s*Birth\s*[:\-]\s*[\r\n\s]*(\d{2}[/\-]\d{2}[/\-](?:19|20)\d{2})",
            pdf_text,
        )
        if m_stu:
            dt = parse_any_date(m_stu.group(1))
            if dt:
                dobs.append(dt)
    if not dobs:
        m_gen_dob = re.search(r"(?i)(?:Male|Female)\s*[\r\n\s]+(\d{2}[/\-]\d{2}[/\-](?:19|20)\d{2})\s*[\r\n\s]+\d{1,3}\s*[\r\n\s]*Years", pdf_text)
        if m_gen_dob:
            dt = parse_any_date(m_gen_dob.group(1))
            if dt:
                dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    # 8. Premium Mode & PYP
    data["premium_mode"] = extract_premium_mode(pdf_text)
    data["pyp_number"] = "FRESH"
    return data
