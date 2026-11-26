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
        or re.search(r"(?i)TATTIOP\d+", pdf_text)
        or re.search(r"(?i)(?:Overseas\s+Travel|Travel\s+Guard|Travel\s+Insurance\s*-\s*Student)", pdf_text)
    )


def parse_tata_aig_travel(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "TRAVEL"
    data["sub_type"] = "TRAVEL INSURANCE"

    for pat in [
        r"(?i)Policy\s*(?:Certificate\s*)?Number\s*[:\-]\s*([A-Z0-9/\-]{6,30})",
        r"(?i)Policy\s*No\.?\s*[:\-]\s*([A-Z0-9/\-]{6,30})",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            data["policy_number"] = m_pol.group(1).strip()
            break

    for pat in [
        r"(?i)Policy\s*Holder\s*Name\s*[\r\n]+\s*([^\r\n]{3,80})",
        r"(?i)Proposer\s*Name\s*[:\-]\s*([^\r\n]{3,80})",
        r"(?i)Insured\s*Name\s*-\s*1\s*[:\-]\s*([^\r\n]{3,80})",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1))
            if cand and len(cand) >= 3:
                data["client_name"] = cand
                break

    for pat in [
        r"(?i)Agent\s*/\s*Intermediary\s*Name\s*[\r\n]+\s*([^\r\n]{3,90})",
        r"(?i)Producer\s*Name\s*[:\-]\s*([^\r\n]{3,90})",
        r"(?i)Name\s*&\s*Signature\s*of\s*agent\s*/\s*intermediary\s*[:\-]\s*([^\r\n]{3,90})",
    ]:
        m_ag = re.search(pat, pdf_text)
        if m_ag:
            cand = clean_person_name(m_ag.group(1))
            if cand and len(cand) >= 2:
                data["agency"] = shorten_agency_name(cand)
                break

    date_tok = r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})"
    m_td = re.search(
        rf"(?i)Travel\s*Dates[\s\S]{{0,40}}?From\s*[:\-]?\s*{date_tok}[\s\S]{{0,25}}?To\s*[:\-]?\s*[\r\n\s]*{date_tok}",
        pdf_text,
    )
    if m_td:
        data["start_dt"] = parse_any_date(m_td.group(1))
        data["end_dt"] = parse_any_date(m_td.group(2))
    if not data["start_dt"]:
        m_dep = re.search(rf"(?i)Departure\s*Date\s*[:\-]\s*{date_tok}", pdf_text)
        if m_dep:
            data["start_dt"] = parse_any_date(m_dep.group(1))
    if not data["end_dt"]:
        m_dur = re.search(rf"(?i)Duration\s*plan\s*required\s*for\s*[:\-]\s*{date_tok}", pdf_text)
        if m_dur:
            data["end_dt"] = parse_any_date(m_dur.group(1))

    for pat in [
        r"(?i)Total\s*Premium\s*[\r\n\s]*(?:INR|Rs\.?|₹)?\s*[\r\n\s]*([\d,]+(?:\.\d+)?)",
        r"(?i)Premium\s*Amount\s*\(in\s*Rs\.?\)\s*[:\-]\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    # Primary Medical Sum Insured (handles USD "$5,00,000" & skips "$null")
    for pat in [
        r"(?i)Accident\s*&\s*Sickness\s*Medical\s*Expenses\s*[\r\n\s]*(?:\$|USD|EUR|€|INR|Rs\.?|₹)?\s*([\d,]{4,15})",
        r"(?i)Medical\s*Expenses[\s\S]{0,40}?[\r\n\s]*(?:\$|USD|EUR|€|INR|Rs\.?|₹)\s*([\d,]{4,15})",
        r"(?i)Sum\s*Insured\s*[:\-]\s*(?:\$|USD|EUR|€|INR|Rs\.?|₹)?\s*([\d,]{4,15})",
    ]:
        m_si = re.search(pat, pdf_text)
        if m_si:
            data["sum_insured"] = clean_amount(m_si.group(1))
            break

    # Insured Person DOB only (never picks Sponsor DOB)
    dobs = []
    m_tbl = re.search(r"(?i)Sr\.No[\s\S]{0,1200}?(?:Agent/Intermediary|TATA\s+AIG\s+GSTIN|$)", pdf_text)
    if m_tbl:
        for m_d in re.finditer(
            r"(?i)(?:Male|Female|Other)\s*[\r\n]+\s*(\d{2}[/\-]\d{2}[/\-](?:19|20)\d{2})\s*[\r\n]+\s*\d{1,3}\s*[\r\n]+\s*Years?",
            m_tbl.group(0),
        ):
            dt = parse_any_date(m_d.group(1))
            if dt and dt.year >= 1920:
                dobs.append(dt)
    if not dobs:
        m_prop = re.search(
            r"(?i)Personal\s+Details\s+of\s+person\s+proposed([\s\S]{0,600}?)(?:Sponsor\s+Details|Nominee\s+Details|$)",
            pdf_text,
        )
        if m_prop:
            m_d = re.search(r"(?i)Date\s*Of\s*Birth\s*[:\-]?\s*[\r\n\s]*(\d{2}[/\-]\d{2}[/\-](?:19|20)\d{2})", m_prop.group(1))
            if m_d:
                dt = parse_any_date(m_d.group(1))
                if dt:
                    dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    if re.search(r"(?i)paymentLink\w*", pdf_text):
        data["premium_mode"] = "ONLINE"
    else:
        data["premium_mode"] = extract_premium_mode(pdf_text)

    return data
