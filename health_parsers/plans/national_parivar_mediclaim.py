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


def is_national_parivar_mediclaim(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)(?:New\s+)?National\s+Parivar\s+Mediclaim", pdf_text)
        or re.search(r"(?i)NICHLIP23033V|NICHLIP21\d+V|NICHLIP22\d+V", pdf_text)
    )


def _clean_nic_relation_name(raw_name: str) -> str:
    """
    Cleans National Insurance relation-embedded names:
      - 'PHOOL GIRI SO MR KASHI GIRI' -> 'PHOOL GIRI'
      - 'MR PHOOL GIRI S/O MR KASHI GIRI' -> 'PHOOL GIRI'
      - 'AMIT S/O MR NARENDRA LAHOTI' -> 'AMIT LAHOTI'
    """
    s = re.sub(r"\s+", " ", str(raw_name or "")).strip()
    m_rel = re.search(
        r"(?i)^(.*?)\b(?:S/O|W/O|D/O|C/O|(?:SO|WO|DO|CO)(?=\s+(?:MR|MRS|MS|MISS|SMT|SHRI|DR|LATE)(?:\.|\b)))\b(.*)$",
        s,
    )
    if m_rel:
        left = clean_person_name(m_rel.group(1))
        right = clean_person_name(m_rel.group(2))
        if left and len(left.split()) >= 2:
            return left
        if left and right:
            r_parts = right.split()
            if len(r_parts) >= 2 and r_parts[-1] not in left.split():
                return f"{left} {r_parts[-1]}"
            return left
    return clean_person_name(s)


def parse_national_parivar_mediclaim(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "PARIVAR MEDICLAIM"
    data["sub_type"] = "MEDICLAIM"

    # 1. Policy Number
    for pat in [
        r"(?i)Policy\s*Number\s*[:\-]\s*[\r\n\s]*([0-9]{14,22})\b",
        r"(?i)Policy\s*No\.?\s*[:\-]\s*[\r\n\s]*([0-9]{14,22})\b",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            data["policy_number"] = m_pol.group(1).strip()
            break

    # 2. Client Name (cleans SO / S/O / W/O / D/O relation suffixes)
    for pat in [
        r"(?i)Customer\s*Name\s*[:\-]\s*([^\r\n]{3,90})",
        r"(?i)Details\s*Of\s*Receiver\s*[:\-]\s*([^\r\n]{3,90})",
        r"(?i)certify\s+that\s*\.?\s*([^\r\n]{3,90}?)\s+has\s+paid\b",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = _clean_nic_relation_name(m_nm.group(1))
            if cand and len(cand) >= 3:
                data["client_name"] = cand
                break

    # 3. Agency (Sales Channel Details -> Name: Mrs Khushbu Bhandari)
    m_sc = re.search(
        r"(?i)Sales\s*Channel\s*Details[\s\S]{0,160}?Name\s*[:\-]\s*([^\r\n]{2,80})",
        pdf_text,
    )
    if m_sc:
        cand = shorten_agency_name(clean_person_name(m_sc.group(1)))
        if cand:
            data["agency"] = cand

    # 4. Inception & Expiry Dates
    date_tok = r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})"
    m_per = re.search(
        rf"(?i)Policy\s*Effective\s*from[\s\S]{{0,35}}?{date_tok}[\s\S]{{0,30}}?to[\s\S]{{0,30}}?{date_tok}",
        pdf_text,
    )
    if not m_per:
        m_per = re.search(rf"(?i)for\s+the\s+period\s+from\s+{date_tok}\s+to\s+{date_tok}", pdf_text)
    if m_per:
        data["start_dt"] = parse_any_date(m_per.group(1))
        data["end_dt"] = parse_any_date(m_per.group(2))

    # 5. Sum Insured (Basic Cover Sum Insured)
    for pat in [
        r"(?i)Basic\s*Cover\s*Sum\s*Insured\s*[\r\n\s]*[:\-]?\s*(?:Rs\.?|INR|₹|`)?\s*([\d,]{5,15}(?:\.\d{2})?)",
        r"(?i)Sum\s*Insured\s*[\r\n]+\s*(?:Rs\.?|INR|₹|`)?\s*([\d,]{5,15}(?:\.\d{2})?)\b",
    ]:
        m_si = re.search(pat, pdf_text)
        if m_si:
            amt = clean_amount(m_si.group(1))
            if amt.isdigit() and int(amt) >= 50000:
                data["sum_insured"] = amt
                break

    # 6. Total Premium (with GST)
    for pat in [
        r"(?i)Total\s*Amount\s*[\r\n\s]*[:\-]?\s*(?:Rs\.?|INR|₹|`)?\s*([\d,]+(?:\.\d{2})?)",
        r"(?i)Total\s*Invoice\s*Value\s*\(In\s*figures\)\s*[:\-]\s*(?:Rs\.?|INR|₹|`)?\s*([\d,]+(?:\.\d{2})?)",
        r"(?i)has\s+paid\s*(?:Rs\.?|INR|₹|`)\s*([\d,]+(?:\.\d{2})?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            amt = clean_amount(m_p.group(1))
            if amt.isdigit() and int(amt) > 0:
                data["premium"] = amt
                break

    # 7. Previous Policy Number (picks the one WITH an expiry date if multiple lines exist)
    m_pyp_block = re.search(
        r"(?i)Previous\s*Policy\s*Number\s*and[\r\n\s]*Expiry\s*Date([\s\S]{0,260})",
        pdf_text,
    )
    if m_pyp_block:
        blk = re.split(r"(?i)(?:Rupees|Government\s+Subsidy|General\s+Summary|Basic\s+Cover)", m_pyp_block.group(1))[0]
        m_with_dt = re.search(r"([0-9]{14,24})[^\r\n]{0,25}?\d{2}/\d{2}/\d{4}", blk)
        if m_with_dt:
            data["pyp_number"] = m_with_dt.group(1).strip()
        else:
            all_nums = re.findall(r"([0-9]{14,24})", blk)
            if all_nums:
                data["pyp_number"] = all_nums[-1].strip()

    # 8. DOB (Oldest Insured Person)
    dobs = []
    for m_d in re.finditer(r"(\d{2}/\d{2}/(?:19|20)\d{2})\s*[\r\n\s]+\d{1,3}\s*Yrs\b", pdf_text, re.I):
        dt = parse_any_date(m_d.group(1))
        if dt and dt.year >= 1920:
            dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    # 9. Premium Mode
    data["premium_mode"] = extract_premium_mode(pdf_text)
    if not data["premium_mode"] and re.search(r"(?i)by\s+Instrument\s+number\s+\d+", pdf_text):
        data["premium_mode"] = "CHEQUE"
    return data
