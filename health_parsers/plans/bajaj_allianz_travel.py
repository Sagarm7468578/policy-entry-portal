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


def is_bajaj_allianz_travel(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)Travel\s+Companion\s+Certificate\s+cum\s+Policy\s+Schedule", pdf_text)
        or re.search(r"(?i)Transcript\s+of\s+Proposal\s+for\s+INDIVIDUAL\s+TRAVEL", pdf_text)
        or re.search(r"(?i)BAJTIOP\d+", pdf_text)
    )


def parse_bajaj_allianz_travel(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "TRAVEL"
    data["sub_type"] = "TRAVEL INSURANCE"

    # 1. Policy Number
    for pat in [
        r"(?i)Policy\s*No\.?\s*[:\-]?\s*([0-9]{2}\-[0-9]{4}\-[0-9]{8,12}\-[0-9]{2})",
        r"\b([0-9]{2}\-[0-9]{4}\-[0-9]{8,12}\-[0-9]{2})\b",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            data["policy_number"] = m_pol.group(1).strip()
            break

    # 2. Client Name
    for pat in [
        r"(?i)Proposer\s*Name\s*[:\-]\s*([^\r\n]{3,80})",
        r"(?i)Received\s+with\s+thanks\s+from\s*[\r\n]+\s*([^\r\n]{3,80})",
        r"(?i)Dear\s+([^\r\n,]{3,80})",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1))
            if cand and len(cand) >= 3 and cand not in ("CUSTOMER", "SIR", "MADAM"):
                data["client_name"] = cand
                break

    # 3. Agency ("Code: 47139004| Name: GIRNAR INSURANCE BROKERS PVT LTD|Contact No.:...")
    m_ag = re.search(r"(?i)Code\s*:\s*[A-Z0-9]+\s*\|\s*Name\s*:\s*([^|\r\n]{2,90})", pdf_text)
    if m_ag:
        raw_ag = clean_person_name(m_ag.group(1))
        if raw_ag:
            ag_short = shorten_agency_name(raw_ag)
            if "GIRNAR" in ag_short:
                ag_short = "GIRNAR"
            data["agency"] = ag_short

    # 4. Inception & Expiry Dates
    date_tok = r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})"
    m_eff = re.search(rf"(?i)Eff\s*Dt\s*:\s*{date_tok}\s*[\r\n\s]*To\s*:\s*{date_tok}", pdf_text)
    if m_eff:
        data["start_dt"] = parse_any_date(m_eff.group(1))
        data["end_dt"] = parse_any_date(m_eff.group(2))
    if not data["start_dt"] or not data["end_dt"]:
        m_per = re.search(
            rf"(?i)Period\s*of[\r\n\s]*Insurance[\s\S]{{0,30}}?From\s*:\s*{date_tok}[\s\S]{{0,40}}?:\s*{date_tok}",
            pdf_text,
        )
        if m_per:
            data["start_dt"] = data["start_dt"] or parse_any_date(m_per.group(1))
            data["end_dt"] = data["end_dt"] or parse_any_date(m_per.group(2))
    if not data["start_dt"]:
        m_dep = re.search(rf"(?i)Departure\s*Date\s*[\r\n\s]*:\s*{date_tok}", pdf_text)
        if m_dep:
            data["start_dt"] = parse_any_date(m_dep.group(1))
    if not data["end_dt"]:
        m_ret = re.search(rf"(?i)Return\s*Date\s*[\r\n\s]*:\s*{date_tok}", pdf_text)
        if m_ret:
            data["end_dt"] = parse_any_date(m_ret.group(1))

    # 5. Sum Insured (Medical Expenses / Travel Elite USD)
    for pat in [
        r"(?i)Medical\s*Expenses,\s*Evacuation\s*and\s*[\r\n\s]*Repatriation\s*[\r\n\s]*(?:USD|\$)\s*([\d,]{4,12})",
        r"(?i)Travel\s*Elite[^\r\n]{0,40}?(?:USD|\$)\s*([\d,]{4,12})",
    ]:
        m_si = re.search(pat, pdf_text)
        if m_si:
            data["sum_insured"] = f"USD {clean_amount(m_si.group(1))}"
            break

    # 6. Total Premium (inclusive of GST — avoids picking IGST amount)
    for pat in [
        r"(?i)(?:Rs\.?|INR|₹)\s*([\d,]+(?:\.\d+)?)\s*[\r\n]+\s*Total\s*Premium\b",
        r"(?i)receipt\s*Amount\s*(?:Rs\.?|INR|₹)\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Total\s*Amount\s*[\r\n]+\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    # 7. Premium Mode
    m_pm = re.search(r"(?i)Payment\s*Mode\s*:\s*([^\r\n|]{2,40})", pdf_text)
    if m_pm:
        seg = m_pm.group(1)
        if re.search(r"(?i)\b(?:Online|UPI|NEFT|RTGS|IMPS|Card|PG|Gateway)\b", seg):
            data["premium_mode"] = "ONLINE"
        elif re.search(r"(?i)\b(?:Cheque|Chq\.?|DD)\b", seg):
            data["premium_mode"] = "CHEQUE"
        elif re.search(r"(?i)\bCash\b", seg):
            data["premium_mode"] = "CASH"
    if not data["premium_mode"]:
        data["premium_mode"] = extract_premium_mode(pdf_text)

    # 8. DOB
    m_dob = re.search(r"(?i)Date\s*of\s*Birth\s*[\r\n]+\s*(\d{2}/\d{2}/(?:19|20)\d{2})", pdf_text)
    if not m_dob:
        m_dob = re.search(r"(?i)Member\s*DOB\s*:\s*[\r\n\s]*(\d{2}/\d{2}/(?:19|20)\d{2})", pdf_text)
    if m_dob:
        dt = parse_any_date(m_dob.group(1))
        if dt:
            data["dob"] = fmt_date(dt)

    # 9. Travel policies are single-trip Fresh policies
    data["pyp_number"] = "FRESH"
    return data
