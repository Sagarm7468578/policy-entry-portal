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
        re.search(r"(?i)Optima\s+(?:Super\s+)?Secure|my\s*:\s*Optima\s+Secure|Optima\s+Select", pdf_text)
        or re.search(r"(?i)HDFHLIP21016V|HDFHLIP22063V|HDFHLIP23045V|HDFHLIP24092V|HDFHLIP25\d+V", pdf_text)
    )


def parse_hdfc_optima_secure(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "OS"
    data["sub_type"] = "MEDICLAIM"

    # 1. Policy Number (supports spaced 19-digit format like "2856 2048 4130 3200 000" and compact)
    for pat in [
        r"(?i)Policy\s*(?:Number|No\.?)\s*[\r\n\s]*[:\-]\s*([0-9][0-9 \t]{14,26})",
        r"(?i)policy\s+reference\s+no\.?\s*([0-9]{15,22})\b",
        r"(?i)Policy\s*No\.?\s*([0-9]{15,22})\b",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            digits = re.sub(r"\s+", "", m_pol.group(1))
            if 15 <= len(digits) <= 22:
                data["policy_number"] = digits
                break

    # 2. Client Name
    for pat in [
        r"(?i)Policyholder\s*Name\s*[\r\n\s]*[:\-]\s*([^\r\n]{3,80})",
        r"(?i)Proposer\s*Name\s*[\r\n\s]*[:\-]\s*([^\r\n]{3,80})",
        r"(?i)Dear\s+([^\r\n,]{3,80})",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1).lstrip(" :-\t"))
            if cand and len(cand) >= 3 and cand not in ("CUSTOMER", "SIR", "MADAM", "POLICYHOLDER"):
                data["client_name"] = cand
                break

    # 3. Agency (Intermediary Name table or inline colon format)
    m_ag_tbl = re.search(
        r"(?i)Intermediary\s*Name\s*[\r\n]+\s*Intermediary\s*Code\s*[\r\n]+\s*Intermediary\s*Contact[^\r\n]*[\r\n]+\s*([^\r\n]{2,80})",
        pdf_text,
    )
    if m_ag_tbl:
        cand = shorten_agency_name(clean_person_name(m_ag_tbl.group(1)))
        if cand:
            data["agency"] = cand
    if not data["agency"]:
        for pat in [
            r"(?i)Intermediary\s*Name\s*[:\-]\s*([^\r\n]{2,80})",
            r"(?i)Agent\s*/?\s*Broker\s*Name\s*[:\-]\s*([^\r\n]{2,80})",
        ]:
            m_ag = re.search(pat, pdf_text)
            if m_ag:
                cand = shorten_agency_name(clean_person_name(m_ag.group(1).lstrip(" :-\t")))
                if cand:
                    data["agency"] = cand
                    break

    # 4. Inception & Expiry Dates
    date_tok = r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})"
    for pat in [
        rf"(?i)Period\s*of\s*Insurance\s*[\r\n\s]*[:\-]?\s*From\s*{date_tok}[\s\S]{{0,40}}?To\s*{date_tok}",
        rf"(?i)for\s+the\s+period\s+{date_tok}\s+to\s+{date_tok}",
    ]:
        m_per = re.search(pat, pdf_text)
        if m_per:
            data["start_dt"] = parse_any_date(m_per.group(1))
            data["end_dt"] = parse_any_date(m_per.group(2))
            if data["start_dt"] and data["end_dt"]:
                break

    # 5. Base Sum Insured (handles inline label + 2022–2025 Insured Person's Details tables)
    m_si_inline = re.search(
        r"(?i)Base\s*Sum\s*Insured\s*(?:\([^)]*\))?\s*[:\-]\s*(?:Rs\.?|INR|₹|`)?\s*([\d,]{5,15}(?:\.\d{2})?)",
        pdf_text,
    )
    if m_si_inline:
        amt = clean_amount(m_si_inline.group(1))
        if amt.isdigit() and int(amt) >= 100000:
            data["sum_insured"] = amt

    m_ins = re.search(
        r"(?i)Insured\s+Person[\u2018\u2019']?s?\s+Details\s+and\s+Sum\s+Insured[^\r\n]*([\s\S]{0,2600}?)(?:The\s+nominee\s+must\s+be|Unlimited\s+Restore\s+UIN|Insured\s+Person[\u2018\u2019']?s?\s+Details\s+and\s+Sum\s+Insured\s*[\-\u2013\u2014]\s*Add\s*On|Special\s+Conditions|Renewal\s+Continuity|$)",
        pdf_text,
    )
    if not data["sum_insured"] and m_ins:
        ins_blk = m_ins.group(1)
        # First policy inception date (DD/MM/YYYY) is immediately followed by Base Sum Insured
        m_after_inc = re.search(
            r"(?:\d{2}[/\-]\d{2}[/\-](?:19|20)\d{2})\s*[\r\n]+\s*(?:Rs\.?|INR|₹|`)?\s*([\d,]{6,15}(?:\.\d{2})?)\b",
            ins_blk,
        )
        if m_after_inc:
            amt = clean_amount(m_after_inc.group(1))
            if amt.isdigit() and 100000 <= int(amt) <= 500000000:
                data["sum_insured"] = amt

        if not data["sum_insured"]:
            cands = []
            for m_num in re.finditer(r"(?<![A-Za-z0-9/\-])([\d,]{6,15}(?:\.\d{2})?)(?![A-Za-z0-9/\-])", ins_blk):
                amt = clean_amount(m_num.group(1))
                if amt.isdigit():
                    v = int(amt)
                    if 100000 <= v <= 500000000 and v % 50000 == 0:
                        cands.append(v)
            if cands:
                data["sum_insured"] = str(max(cands))

    # 6. Total Premium (with GST)
    for pat in [
        r"(?i)received\s+an\s+amount\s+of\s*(?:Rs\.?|INR|₹|`)?\s*([\d,]+(?:\.\d+)?)\s*towards\s+premium",
        r"(?i)Grand\s*Total\s*[\-\s]*Premium\s*including\s*GST\s*(?:\([^)]+\))?\s*[\r\n\s]*[:\-]?\s*(?:Rs\.?|INR|₹|`)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Net\s*Premium\s*Payable\s*[\r\n\s]*[:\-]?\s*(?:Rs\.?|INR|₹|`)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Total\s*Premium\s*Payable\s*[\r\n\s]*[:\-]?\s*(?:Rs\.?|INR|₹|`)?\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            amt = clean_amount(m_p.group(1))
            if amt.isdigit() and int(amt) > 0:
                data["premium"] = amt
                break

    # 7. Previous Policy Number
    m_pyp = re.search(
        r"(?i)Previous\s*Policy\s*(?:No\.?|Number)?\s*[\r\n\s]*[:\-]\s*([0-9A-Z/\-]{8,30})\b",
        pdf_text,
    )
    if m_pyp and re.search(r"\d{6,}", m_pyp.group(1)):
        cand_pyp = m_pyp.group(1).strip()
        if cand_pyp != data["policy_number"]:
            data["pyp_number"] = cand_pyp

    # 8. DOB (Oldest Insured Person)
    dobs = []
    for m_d in re.finditer(
        r"(?i)(?:Male|Female)\s*[\r\n\s]+(\d{2}[/\-]\d{2}[/\-](?:19|20)\d{2})",
        pdf_text,
    ):
        dt = parse_any_date(m_d.group(1))
        if dt and dt.year >= 1920:
            dobs.append(dt)
    if not dobs:
        for m_d in re.finditer(
            r"(\d{2}[/\-]\d{2}[/\-](?:19|20)\d{2})\s*[\r\n\s]+(?:Male|Female)\b",
            pdf_text,
            re.I,
        ):
            dt = parse_any_date(m_d.group(1))
            if dt and dt.year >= 1920:
                dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    # 9. Premium Mode
    data["premium_mode"] = extract_premium_mode(pdf_text)
    if not data["premium_mode"] and re.search(r"(?i)Instrument\s+details\s*[\r\n\s]*\d{5,}", pdf_text):
        data["premium_mode"] = "CHEQUE"

    return data
