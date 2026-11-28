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
        re.search(r"(?i)Travel\s+Guard|Tata\s+AIG[\s\S]{0,200}?Travel|TATTIOP\d+V", pdf_text)
    )


def parse_tata_aig_travel(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "TRAVEL"
    data["sub_type"] = "TRAVEL INSURANCE"

    # 1. Policy / Schedule Number
    for pat in [
        r"(?i)Schedule\s*Number\s*[:\-]\s*[\r\n\s]*([A-Z0-9/\-]{8,24})\b",
        r"(?i)Policy\s*/\s*Schedule\s*No\.?\s*[:\-]\s*[\r\n\s]*([A-Z0-9/\-]{8,24})\b",
        r"(?i)Policy\s*(?:No\.?|Number)\s*[:\-]\s*[\r\n\s]*([A-Z0-9/\-]{8,24})\b",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol and re.search(r"\d{6,}", m_pol.group(1)):
            data["policy_number"] = m_pol.group(1).strip()
            break

    # 2. Client Name (prefers single-line Insured Name-1 / multi-line Applicant Name before Duration)
    for pat in [
        r"(?i)Insured\s*Name[\-\s]*1\s*[\s\xa0]*[:\-]\s*[\s\xa0]*([^\r\n]{3,80})",
        r"(?i)Applicant\s*Name\s*[:\-]\s*[\r\n\s]*([\s\S]{3,70}?)(?=\r?\n\s*(?:Duration|Applicant\s*Address|Zone|Travel\s*Dates|Customer\s*GSTIN)\b)",
        r"(?i)Proposer\s*Name\s*[\r\n]+\s*([\s\S]{3,70}?)(?=\r?\n\s*(?:Personal\s*Details|Person\s*Name|Date\s*of\s*Birth)\b)",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1))
            if cand and len(cand) >= 3:
                data["client_name"] = cand
                break

    # 3. Agency (Agent/Broker Name or Producer Name)
    for pat in [
        r"(?i)Agent\s*/\s*Broker\s*[\r\n\s]*Name\s*[:\-]\s*[\r\n\s]*([\s\S]{2,90}?)(?=\r?\n\s*Agent\s*/\s*Broker\s*(?:License|Code|Contact)|$)",
        r"(?i)Producer\s*Name\s*[\r\n]+\s*([\s\S]{2,90}?)(?=\r?\n\s*Producer\s*Code|$)",
    ]:
        m_ag = re.search(pat, pdf_text)
        if m_ag:
            cand = shorten_agency_name(clean_person_name(m_ag.group(1)))
            if cand:
                data["agency"] = cand
                break

    # 4. Inception & Expiry Dates (handles Travel Dates with non-breaking spaces/newlines + Departure/Return fallback)
    date_tok = r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})"
    for pat in [
        rf"(?i)Travel\s*Dates?\s*[:\-]?\s*[\s\xa0]*From\s*[:\-]?\s*{date_tok}[\s\xa0]+To\s*[:\-]?\s*{date_tok}",
        rf"(?i)Policy\s*Period\s*[:\-]?\s*[\s\xa0]*From\s*[:\-]?\s*{date_tok}[\s\xa0]+To\s*[:\-]?\s*{date_tok}",
        rf"(?i)Departure\s+from\s*[\r\n\s]+India\s*[\r\n\s]+{date_tok}[\s\S]{{0,80}}?Return\s+to\s*[\r\n\s]+India\s*[\r\n\s]+{date_tok}",
    ]:
        m_per = re.search(pat, pdf_text)
        if m_per:
            data["start_dt"] = parse_any_date(m_per.group(1))
            data["end_dt"] = parse_any_date(m_per.group(2))
            if data["start_dt"] and data["end_dt"]:
                break

    # 5. Sum Insured (USD medical expense coverage)
    for pat in [
        r"(?i)Sum\s*Insured[\s\xa0]*[:\-][\s\xa0]*(?:USD\s*)?\$\s*([\d,]+)",
        r"(?i)Accident\s*&\s*Sickness\s*Medical\s*Expense\s*Reimbursement[\s\r\n]+(?:USD\s*)?\$\s*([\d,]+)",
    ]:
        m_si = re.search(pat, pdf_text)
        if m_si:
            amt = clean_amount(m_si.group(1))
            if amt.isdigit() and int(amt) > 0:
                data["sum_insured"] = f"USD {amt}"
                break

    # 6. Total Premium (INR)
    for pat in [
        r"(?i)TOTAL\s*PREMIUM\s*[\r\n\s]*(?:INR|Rs\.?|₹)?\s*[\r\n\s]*([\d,]+(?:\.\d+)?)",
        r"(?i)Premium\s*Amount\s*\(in\s*Rs\.?\)\s*[\r\n\s]*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            amt = clean_amount(m_p.group(1))
            if amt.isdigit() and int(amt) > 0:
                data["premium"] = amt
                break

    # 7. DOB (Oldest Insured Person)
    dobs = []
    for m_d in re.finditer(r"(?i)(?:Male|Female)\s*[\r\n\s]+(\d{2}/\d{2}/(?:19|20)\d{2})", pdf_text):
        dt = parse_any_date(m_d.group(1))
        if dt and dt.year >= 1920:
            dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    # 8. Premium Mode (checks Instrument type before generic proposal cheque footnote)
    if re.search(r"(?i)Instrument\s*type\s*[:\-]\s*(?:PaymentLink|Online|UPI|Card|NetBanking|PG)", pdf_text):
        data["premium_mode"] = "ONLINE"
    else:
        data["premium_mode"] = extract_premium_mode(pdf_text)

    data["pyp_number"] = "FRESH"
    return data
