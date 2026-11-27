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


def is_icici_lombard_group_health(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)Group\s+Health\s*(?:\(Floater\))?\s*Insurance", pdf_text)
        and (
            re.search(r"(?i)ICICI\s+Lombard", pdf_text)
            or re.search(r"(?i)ICIHLGP\d+V", pdf_text)
        )
    )


def parse_icici_lombard_group_health(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "GROUP HEALTH"
    data["sub_type"] = "MEDICLAIM"

    # Isolate the actual Policy Schedule section (skips "a. Policy schedule" references inside Page 1 CIS)
    m_sched = re.search(
        r"(?i)a\.\s*POLICY\s+SCHEDULE\s*[\r\n]+\s*(?:Insured\s+Detail|Policy\s+Number)([\s\S]{0,2800})",
        pdf_text,
    )
    if not m_sched:
        m_sched = re.search(r"(?i)Policy\s+Details\s*[\r\n]+\s*Period\s+of\s+Insurance([\s\S]{0,2200})", pdf_text)
    sched_text = m_sched.group(0) if m_sched else pdf_text

    # 1. Policy Number (supports alphanumeric slash format like 4016/X/307240960/02/000 & 4016/307240960/01/000)
    for pat in [
        r"(?i)Policy\s*Number\s*[\r\n\s]*[:\-]?\s*[\r\n\s]*([0-9]{4}/(?:[A-Za-z0-9]+/)?[0-9]{6,14}/[0-9]{2}/[0-9]{3})\b",
        r"\b([0-9]{4}/(?:[A-Za-z0-9]+/)?[0-9]{6,14}/[0-9]{2}/[0-9]{3})\b",
        r"(?i)Policy\s*(?:No\.?|Number)\s*[\r\n\s]*[:\-]\s*[\r\n\s]*([A-Z0-9/\-]{10,32})",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol and re.search(r"\d{6,}", m_pol.group(1)):
            data["policy_number"] = m_pol.group(1).strip()
            break

    # 2. Client Name
    for pat in [
        r"(?i)Name\s*of\s*the\s*Insured\s*[\r\n\s]*[:\-]\s*[\r\n\s]*([^\r\n]{2,100})",
        r"(?i)Policyholder\s*Name\s*[\r\n\s]*[:\-]\s*[\r\n\s]*([^\r\n]{2,100})",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1).lstrip(" :-\t"))
            if cand and len(cand) >= 2:
                data["client_name"] = cand
                break

    # 3. Agency (normalizes ICICI typo "KRITI LADDHA" -> "KIRTI LADDHA")
    for pat in [
        r"(?i)Agency\s*/\s*Broker\s*Name\s*[\r\n\s]*[:\-]\s*([^\r\n]{2,90})",
        r"(?i)Intermediary\s*Name\s*[\r\n\s]*[:\-]\s*([^\r\n]{2,90})",
    ]:
        m_ag = re.search(pat, pdf_text)
        if m_ag:
            cand = shorten_agency_name(clean_person_name(m_ag.group(1).lstrip(" :-\t")))
            cand = re.sub(r"\bKRITI\s+LADDHA\b", "KIRTI LADDHA", cand)
            if cand:
                data["agency"] = cand
                break

    # 4. Inception & Expiry Dates (handles BOTH "Sep 18, 2025" AND "18/09/2025" / "18-Sep-2025")
    date_tok = r"(\d{1,2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})"
    m_per = re.search(
        rf"(?i)Period\s*of\s*Insurance[\s\S]{{0,80}}?From\s*[:\-]?\s*(?:[\d:]+\s*(?:Hours|Hrs)\.?\s*(?:of|on)?\s*)?{date_tok}"
        rf"[\s\S]{{0,50}}?To\s*[:\-]?\s*(?:(?:Midnight|[\d:]+\s*(?:Hours|Hrs)\.?)\s*(?:of|on)?\s*)?{date_tok}",
        pdf_text,
    )
    if m_per:
        data["start_dt"] = parse_any_date(m_per.group(1))
        data["end_dt"] = parse_any_date(m_per.group(2))

    # 5. Sum Insured (Policy Schedule Total Sum Insured, e.g. 48,00,000.00; avoids CIS per-family SI)
    for src in (sched_text, pdf_text):
        m_si = re.search(
            r"(?i)Total\s+Lives\s+Insured[\s\S]{0,120}?Sum\s*Insured\s*[\r\n\s]*[:\-]\s*(?:Rs\.?|INR|₹|`)?\s*([\d,]+(?:\.\d+)?)",
            src,
        )
        if not m_si:
            m_si = re.search(
                r"(?i)Sum\s*Insured\s*[\r\n\s]*[:\-]\s*(?:Rs\.?|INR|₹|`)?\s*([\d,]+(?:\.\d+)?)",
                src,
            )
        if m_si:
            amt = clean_amount(m_si.group(1))
            if amt.isdigit() and int(amt) >= 50000:
                data["sum_insured"] = amt
                break

    # 6. Total Premium (inclusive of taxes)
    for src in (sched_text, pdf_text):
        for pat in [
            r"(?i)\*?Total\s*Premium\s*[\r\n\s]*[:\-]\s*(?:Rs\.?|INR|₹|`)?\s*([\d,]+(?:\.\d+)?)",
            r"(?i)Gross\s*Premium\s*[\r\n\s]*[:\-]\s*(?:Rs\.?|INR|₹|`)?\s*([\d,]+(?:\.\d+)?)",
        ]:
            m_p = re.search(pat, src)
            if m_p:
                amt = clean_amount(m_p.group(1))
                if amt.isdigit() and int(amt) > 0:
                    data["premium"] = amt
                    break
        if data["premium"]:
            break

    # 7. PYP Number
    m_pyp = re.search(r"(?i)Previous\s*Policy\s*(?:No\.?|Number)\s*[:\-]\s*([A-Z0-9/\-]{8,32})", pdf_text)
    if m_pyp and re.search(r"\d{6,}", m_pyp.group(1)):
        data["pyp_number"] = m_pyp.group(1).strip()
    else:
        data["pyp_number"] = "FILL MANUAL"

    # 8. Corporate Group Policy -> no individual DOB
    data["dob"] = "GROUP POLICY"
    data["skip_dob_fallback"] = True

    # 9. Premium Mode
    data["premium_mode"] = extract_premium_mode(pdf_text)
    return data
