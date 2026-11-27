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


def is_hdfc_group_health(pdf_text: str) -> bool:
    if re.search(r"(?i)Endorsement\s*(?:No\.?|Number|Schedule)", pdf_text):
        return False
    return bool(
        re.search(r"(?i)HDFC\s+ERGO\s+Group\s+Health\s+Insurance", pdf_text)
        or re.search(r"(?i)HDFHLGP24095V|HDFHLGP21\d+V|HDFHLGP22\d+V|HDFHLGP23\d+V", pdf_text)
    )


def parse_hdfc_group_health(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "GROUP HEALTH"
    data["sub_type"] = "MEDICLAIM"

    # 1. Policy Number (clean digits, no leading punctuation)
    for pat in [
        r"(?i)Policy\s*No\.?[ \t]*[:\-]?[ \t]*([\d \t]{15,26})",
        r"(?i)Policy\s*Number[ \t]*[:\-]?[ \t]*([\d \t]{15,26})",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            digits = re.sub(r"\s+", "", m_pol.group(1))
            if len(digits) >= 15:
                data["policy_number"] = digits
                break

    # 2. Client Name (Policyholder company name — avoids "Dear Customer")
    for pat in [
        r"(?i)Item\s*1\.\s*Name\s*of\s*the\s*Policyholder\s*[\r\n\s]*[:\-]\s*[\r\n\s]*([^\r\n]{2,100})",
        r"(?i)Name\s*(?:&\s*Address\s*)?of\s*the\s*Policyholder\s*[\r\n\s]*[:\-]?\s*[\r\n\s]*([^\r\n]{2,100})",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1))
            if cand and len(cand) >= 2 and cand not in ("CUSTOMER", "SIR", "MADAM", "POLICYHOLDER"):
                data["client_name"] = cand
                break

    # 3. Agency
    for pat in [
        r"(?i)Item\s*2\.\s*Intermediary\s*Name\s*[\r\n\s]*[:\-]\s*[\r\n\s]*([^\r\n]{2,90})",
        r"(?i)Intermediary\s*Name\s*[:\-]\s*[\r\n\s]*([^\r\n]{2,90})",
        r"(?i)Broker\s*Name\s*[:\-]\s*[\r\n\s]*([^\r\n]{2,90})",
    ]:
        m_ag = re.search(pat, pdf_text)
        if m_ag:
            raw = re.sub(r"(?i)^\s*(?:AGENT|BROKER|POSP|IMD|DIRECT)\s*[:\-]\s*", "", m_ag.group(1).strip())
            cand = shorten_agency_name(clean_person_name(raw))
            if cand:
                data["agency"] = cand
                break

    # 4. Inception & Expiry Dates ("Item 8. Policy Period : From 00:01 hours :May 04, 2025 To (Midnight) :May 03, 2026")
    date_tok = r"(\d{2}[/\-]\d{2}[/\-]\d{2,4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})"
    m_per = re.search(
        rf"(?i)Policy\s*Period[\s\S]{{0,80}}?From(?:\s*[\d:]+\s*hours)?\s*[:\-]?\s*{date_tok}[\s\S]{{0,60}}?To(?:\s*\(?Midnight\)?)?\s*[:\-]?\s*{date_tok}",
        pdf_text,
    )
    if m_per:
        data["start_dt"] = parse_any_date(m_per.group(1))
        data["end_dt"] = parse_any_date(m_per.group(2))

    # 5. Sum Insured ("Summary of Lives Covered")
    m_lives = re.search(
        r"(?i)Summary\s+of\s+Lives\s+Covered([\s\S]{0,600}?)(?:Grand\s+Total|12\.3\s+Details|$)",
        pdf_text,
    )
    if m_lives:
        amts = [clean_amount(a) for a in re.findall(r"\b\d{1,3}(?:,\d{2,3})+\b", m_lives.group(1))]
        amts = [int(a) for a in amts if a.isdigit() and int(a) >= 50000]
        if amts:
            data["sum_insured"] = str(max(amts))

    # 6. Total Premium (inclusive of GST)
    for pat in [
        r"(?i)Total\s*Amount\s*Payable\s*[\r\n\s]*(?:Rs\.?|INR|₹)?\s*[\r\n\s]*([\d,]+(?:\.\d+)?)",
        r"(?i)Item\s*11\.\s*Annual\s*Premium\s*[\r\n\s]*[:\-]\s*[\r\n\s]*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Net\s*Premium\s*[\r\n\s]*(?:Rs\.?|INR|₹)?\s*[\r\n\s]*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    # 7. PYP Number (handles "Policy No. EXPIRING_2999204113232904000")
    m_pyp = re.search(
        r"(?i)renewal\s+for\s+Policy\s*No\.?\s*[:\-]?\s*(?:EXPIRING_)?([0-9]{15,22})\b",
        pdf_text,
    )
    if m_pyp:
        data["pyp_number"] = m_pyp.group(1).strip()

    # 8. Corporate Group Policy -> no individual DOB
    data["dob"] = "GROUP POLICY"
    data["skip_dob_fallback"] = True

    # 9. Premium Mode
    data["premium_mode"] = extract_premium_mode(pdf_text)
    return data
