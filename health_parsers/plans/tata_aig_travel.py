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

    for pat in [
        r"(?i)Policy\s*(?:Certificate\s*)?No\.?\s*[:\-]?\s*[\r\n\s]*([0-9]{8,16})\b",
        r"(?i)Policy\s*Number\s*[:\-]?\s*[\r\n\s]*([A-Z0-9/\-]{8,24})",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol and re.search(r"\d{6,}", m_pol.group(1)):
            data["policy_number"] = m_pol.group(1).strip()
            break

    for pat in [
        r"(?i)Policyholder\s*[\r\n\s]+Name\s*[:\-]?\s*[\r\n\s]*([^\r\n]{3,80})",
        r"(?i)Proposer\s*Name\s*[:\-]?\s*[\r\n\s]*([^\r\n]{3,80})",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1))
            if cand and len(cand) >= 3 and "CONTACT" not in cand:
                data["client_name"] = cand
                break

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
        m_ag_in = re.search(r"(?i)(?:Intermediary|Agent)\s*Name\s*[:\-]\s*([^\r\n]{3,80})", pdf_text)
        if m_ag_in and not re.search(r"(?i)License|Code|Contact", m_ag_in.group(1)):
            cand = clean_person_name(m_ag_in.group(1))
            if cand and len(cand) >= 2:
                data["agency"] = shorten_agency_name(cand)

    date_tok = r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})"
    for pat in [
        rf"(?i)Policy\s*Period\s*Start\s*Date\s*[:\-]?\s*[\r\n\s]*{date_tok}",
        rf"(?i)Trip\s*Duration\s*[\r\n\s]*From\s*[:\-]?\s*[\r\n\s]*{date_tok}",
        rf"(?i)Departure\s*from\s*India\s*[:\-]\s*{date_tok}",
    ]:
        m_st = re.search(pat, pdf_text)
        if m_st:
            data["start_dt"] = parse_any_date(m_st.group(1))
            if data["start_dt"]:
                break

    for pat in [
        rf"(?i)Policy\s*Period\s*End\s*Date\s*[:\-]?\s*[\r\n\s]*{date_tok}",
        rf"(?i)Trip\s*Duration[\s\S]{{0,40}}?To\s*[:\-]?\s*[\r\n\s]*{date_tok}",
        rf"(?i)Return\s*to\s*India\s*[:\-]\s*{date_tok}",
    ]:
        m_en = re.search(pat, pdf_text)
        if m_en:
            data["end_dt"] = parse_any_date(m_en.group(1))
            if data["end_dt"]:
                break

    for pat in [
        r"(?i)Medical\s*Sum\s*Insured\s*[\r\n\s]*(?:USD|\$)\s*([\d,]{4,12})",
        r"(?i)Unlimited\s*Sum\s*Insured\s*with\s*(?:USD|\$)\s*([\d,]{4,12})",
        r"(?i)Medical\s*Expenses[\s\S]{0,80}?(?:USD|\$)\s*([\d,]{4,12})",
    ]:
        m_si = re.search(pat, pdf_text)
        if m_si:
            data["sum_insured"] = f"USD {clean_amount(m_si.group(1))}"
            break

    for pat in [
        r"(?i)Final\s*Premium\s*[:\-]?\s*[\r\n\s]*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Total\s*Premium\s*(?:Payable|Paid)?\s*[:\-]?\s*[\r\n\s]*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Premium\s*:\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    dobs = []
    m_ins = re.search(r"(?i)Insured\s+Person\s+Details\s*:?([\s\S]{0,900}?)(?:Nominee\s+Details|$)", pdf_text)
    if m_ins:
        for m_d in re.finditer(r"(?:Male|Female)\s*[\r\n\s]+(\d{2}[/\-]\d{2}[/\-](?:19|20)\d{2})", m_ins.group(1), re.I):
            dt = parse_any_date(m_d.group(1))
            if dt and dt.year >= 1920:
                dobs.append(dt)
    if not dobs:
        m_prop_dob = re.search(r"(?i)Date\s*of\s*Birth\s*[\r\n\s]+(\d{2}[/\-]\d{2}[/\-](?:19|20)\d{2})", pdf_text)
        if m_prop_dob:
            dt = parse_any_date(m_prop_dob.group(1))
            if dt:
                dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    data["premium_mode"] = extract_premium_mode(pdf_text)
    data["pyp_number"] = "FRESH"
    return data
