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


def is_hdfc_optima_secure(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)(?:my\s*:\s*)?Optima\s*(?:Super\s*)?Secure", pdf_text)
        or re.search(r"(?i)HDFHLIP25041V|HDFHLIP23127V|HDFHLIP22036V", pdf_text)
    )


def parse_hdfc_optima_secure(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "OS"
    data["sub_type"] = "MEDICLAIM"

    # 1. Policy Number (handles spaced & wrapped 19-digit numbers)
    for pat in [
        r"\*([0-9]{15,20})\*",
        r"(?i)Policy\s*No\.?\s*[:\-]\s*([0-9][0-9 \t]{14,24})",
        r"(?i)Policy\s*Number\s*[\r\n\s]*[:\-]?\s*([0-9][0-9 \t\r\n]{14,26})",
        r"(?i)reference\s+no\.?\s*([0-9]{15,20})\b",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            digits = re.sub(r"\s+", "", m_pol.group(1))
            if 15 <= len(digits) <= 22:
                data["policy_number"] = digits
                break

    # 2. Client Name (strips leading ":" BEFORE clean_person_name so "MR." / "MISS." prefixes are cleanly removed)
    for pat in [
        r"(?i)Policyholder\s*Name\s*[\r\n]*\s*[:\-]?\s*([^\r\n]{3,80})",
        r"(?i)Policy\s*Holder['’]?s?\s*Name\s*[\r\n]*\s*[:\-]?\s*([^\r\n]{3,80})",
        r"(?i)Dear\s+([^\r\n,]{3,80})",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            raw_nm = m_nm.group(1).lstrip(" :-\t")
            cand = clean_person_name(raw_nm)
            if cand and len(cand) >= 3 and cand not in ("CUSTOMER", "SIR", "MADAM"):
                data["client_name"] = cand
                break

    # 3. Agency
    m_ag = re.search(
        r"(?i)Intermediary\s*Name\s*[\r\n]+\s*Intermediary\s*Code\s*[\r\n]+\s*Intermediary\s*Contact\s*(?:Number|No\.?)\s*[\r\n]+\s*([^\r\n]{3,80})",
        pdf_text,
    )
    if not m_ag:
        m_ag = re.search(r"(?i)Intermediary\s*Name\s*[:\-]?\s*[\r\n]+\s*([^\r\n]{3,80})", pdf_text)
    if m_ag:
        raw_ag = re.sub(r"(?i)^\s*(?:AGENT|BROKER|POSP|IMD)\s*[:\-]\s*", "", m_ag.group(1).lstrip(" :-\t"))
        cand = shorten_agency_name(clean_person_name(raw_ag))
        if cand and "CODE" not in cand:
            data["agency"] = cand

    # 4. Inception & Expiry Dates
    date_tok = r"(\d{1,2}[/\-][A-Za-z0-9]{1,3}[/\-]\d{2,4})"
    m_per = re.search(
        rf"(?i)Period\s*of\s*Insurance\s*[\r\n\s]*[:\-]?\s*From\s*(?:[\d:]+\s*hrs\s*on\s*)?{date_tok}[\s\S]{{0,40}}?to\s*(?:[\d:]+\s*hrs\s*on\s*)?{date_tok}",
        pdf_text,
    )
    if m_per:
        data["start_dt"] = parse_any_date(m_per.group(1))
        data["end_dt"] = parse_any_date(m_per.group(2))
    if not data["start_dt"] or not data["end_dt"]:
        m_vf = re.search(rf"(?i)Valid\s*From\s*:\s*{date_tok}\s+Renewal\s*Date\s*:\s*{date_tok}", pdf_text)
        if m_vf:
            data["start_dt"] = data["start_dt"] or parse_any_date(m_vf.group(1))
            data["end_dt"] = data["end_dt"] or parse_any_date(m_vf.group(2))
    if not data["start_dt"] or not data["end_dt"]:
        m_80d_per = re.search(rf"(?i)for\s+the\s+period\s+{date_tok}\s+to\s+{date_tok}", pdf_text)
        if m_80d_per:
            data["start_dt"] = data["start_dt"] or parse_any_date(m_80d_per.group(1))
            data["end_dt"] = data["end_dt"] or parse_any_date(m_80d_per.group(2))

    # 5. Base Sum Insured
    for pat in [
        r"(?i)Base\s*Sum\s*Insured\s*per\s*Insured\s*Person[\s\S]{0,60}?[\r\n]+\s*([\d,]{5,15})\b",
        r"(?i)Sum\s*Insured\s*opted\s*:\s*([\d,]{5,15})\b",
        r"(?i)Base\s*Sum\s*Insured\s*(?:\(Rs\.?\)|\(₹\)|\(`?\))?\s*[:\-]?\s*[\r\n\s]*([\d,]{5,15})\b",
    ]:
        m_si = re.search(pat, pdf_text)
        if m_si:
            amt = clean_amount(m_si.group(1))
            if amt.isdigit() and int(amt) >= 100000:
                data["sum_insured"] = amt
                break

    # 6. Total Premium (inclusive of GST — handles ₹, Rs., INR, & backtick "`" Rupee font + multiline 80D text)
    for pat in [
        r"(?i)received\s+an\s+amount\s+of\s*[\r\n\s]*(?:₹|Rs\.?|INR|`)?\s*([\d,]+(?:\.\d+)?)\s*[\r\n\s]*towards\s+premium",
        r"(?i)totalling\s+to\s*[\r\n\s]*(?:₹|Rs\.?|INR|`)?\s*([\d,]+(?:\.\d+)?)\s*[\r\n\s]*towards\s+premium",
        r"(?i)has\s+paid\s*[\r\n\s]*(?:₹|Rs\.?|INR|`)\s*([\d,]+(?:\.\d+)?)\s*(?:\([^)]+\))?\s*towards\s+premium",
        r"(?i)Total\s*Premium\s*(?:Payable|Paid)\s*[:\-]?\s*[\r\n\s]*(?:₹|Rs\.?|INR|`)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Gross\s*Premium\s*[\r\n]+\s*(?:₹|Rs\.?|INR|`)?\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            amt = clean_amount(m_p.group(1))
            if amt.isdigit() and int(amt) > 0:
                data["premium"] = amt
                break

    if not data["premium"]:
        m_tpg = re.search(
            r"(?i)(?:Total\s*)?Premium\s*including\s*(?:applicable\s*)?GST\s*[\r\n]+([\d,.\r\n \t]+?)(?:Payment\s*Details|Page\s+\d+|HDFC\s+ERGO|$)",
            pdf_text,
        )
        if m_tpg:
            nums = [
                float(x.replace(",", ""))
                for x in re.findall(r"\b\d{1,3}(?:,\d{2,3})+(?:\.\d+)?\b|\b\d{4,7}(?:\.\d+)?\b", m_tpg.group(1))
            ]
            if nums:
                data["premium"] = str(int(round(sum(nums))))

    # 7. PYP Number (supports 19-digit HDFC, 14-digit Star Health, slash-format Oriental/National, etc.)
    m_pyp = re.search(
        r"(?i)Previous\s*Policy\s*(?:No\.?|Number)?\s*[\r\n]*\s*[:\-]\s*([A-Z0-9/\-]{8,30})\b",
        pdf_text,
    )
    if m_pyp and re.search(r"\d{6,}", m_pyp.group(1)):
        data["pyp_number"] = m_pyp.group(1).strip()

    # 8. DOB (Oldest Insured Person)
    dobs = []
    for m_sec in re.finditer(
        r"(?i)(?:Insured\s+Person['’]?s?\s+Details\s+and\s+Sum\s+Insured|Insured\s+Name\s*[\r\n]+\s*(?:Member\s+ID|Date\s+Of\s+Birth))([\s\S]{0,2200})",
        pdf_text,
    ):
        for m_d in re.finditer(
            r"(?i)(?:Male|Female)\s*[\r\n\s]+(?:\d{1,3}\s*[\r\n\s]+)?(\d{2}[/\-]\d{2}[/\-](?:19|20)\d{2})"
            r"|(\d{2}[/\-]\d{2}[/\-](?:19|20)\d{2})\s*[\r\n\s]+(?:Male|Female|M|F)\b",
            m_sec.group(1),
        ):
            dt = parse_any_date(m_d.group(1) or m_d.group(2))
            if dt and dt.year >= 1920:
                dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    # 9. Premium Mode
    data["premium_mode"] = extract_premium_mode(pdf_text)
    return data
