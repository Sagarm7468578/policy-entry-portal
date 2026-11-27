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


def is_new_india_asha_kiran(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)New\s+India\s+Asha\s+Kiran", pdf_text)
        or re.search(r"(?i)Asha\s+Kiran\s+Policy", pdf_text)
        or re.search(r"(?i)NIAHLIP25047V|NIAHLIP21\d+V|NIAHLIP22029V", pdf_text)
    )


def _clean_nia_relation_name(raw_name: str) -> str:
    """
    Cleans New India relation-embedded names:
      - 'MR. AMIT S/O MR. NARENDRA LAHOTI' -> 'AMIT LAHOTI'
      - 'MR. AMIT LAHOTI S/O NARENDRA LAHOTI' -> 'AMIT LAHOTI'
    """
    s = re.sub(r"\s+", " ", str(raw_name or "")).strip()
    m_rel = re.search(r"(?i)^(.*?)\b(?:S/O|W/O|D/O|C/O)\b(.*)$", s)
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


def parse_new_india_asha_kiran(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "ASHA KIRAN"
    data["sub_type"] = "MEDICLAIM"

    # 1. Policy Number
    for pat in [
        r"(?i)Policy\s*Number\s*[\r\n\s]*[:\-]\s*([0-9]{16,24})\b",
        r"(?i)Policy\s*No\.?\s*[:\-]\s*[\r\n\s]*([0-9]{16,24})\b",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            data["policy_number"] = m_pol.group(1).strip()
            break

    # 2. Client Name
    for pat in [
        r"(?i)Insured\s*Name\s*[\r\n\s]*[:\-]\s*([^\r\n]{3,90})",
        r"(?i)Policyholder\s*Name\s*[\r\n\s]*[:\-]?\s*([^\r\n]{3,90})",
        r"(?i)certify\s+that\s+(?:Mr\.?/Mrs\.?|Mr\.?|Mrs\.?|Ms\.?)\s*([A-Za-z ./]{3,90}?)\s+has\s+paid\b",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = _clean_nia_relation_name(m_nm.group(1))
            if cand and len(cand) >= 3:
                data["client_name"] = cand
                break

    # 3. Agency ("Agent/Bancassurance/Specified Person : Mrs. SONAL LADDHA (NIAAG00134008)")
    for pat in [
        r"(?i)Agent/Bancassurance/Spe[\r\n\s]*cified\s*Person\s*[\r\n\s]*[:\-]\s*([^\r\n(]{3,80})",
        r"(?i)Name\s+of\s+the\s*[\r\n\s]+Agent/Intermediary\s*[\r\n\s]*[:\-]?\s*([^\r\n(]{3,80})",
        r"(?i)Agent/Intermediary\s*[\r\n\s]*[:\-]\s*([^\r\n(]{3,80})",
    ]:
        m_ag = re.search(pat, pdf_text)
        if m_ag:
            cand = shorten_agency_name(clean_person_name(m_ag.group(1)))
            if cand and len(cand) >= 2:
                data["agency"] = cand
                break

    # 4. Inception & Expiry Dates
    date_tok = r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})"
    m_per = re.search(
        rf"(?i)Period\s*of\s*Insurance\s*[\r\n\s]*[:\-]?\s*From\s*:\s*{date_tok}[\s\S]{{0,45}}?To\s*:\s*{date_tok}",
        pdf_text,
    )
    if not m_per:
        m_per = re.search(rf"(?i)for\s+the\s+period\s+{date_tok}[\s\S]{{0,35}}?to\s+{date_tok}", pdf_text)
    if m_per:
        data["start_dt"] = parse_any_date(m_per.group(1))
        data["end_dt"] = parse_any_date(m_per.group(2))

    # 5. Sum Insured
    for pat in [
        r"(?i)Total\s*Sum\s*Insured\s*[\r\n]+\s*(?:Rs\.?|INR|₹|`)?\s*([\d,]{5,15})\b",
        r"(?i)Floater\s*Sum\s*Insured\s*[\r\n]+\s*(?:Rs\.?|INR|₹|`)?\s*([\d,]{5,15})\b",
        r"(?i)Sum\s*Insured\s*[:\-]\s*(?:Rs\.?|INR|₹|`)?\s*([\d,]{5,15})\b",
    ]:
        m_si = re.search(pat, pdf_text)
        if m_si:
            amt = clean_amount(m_si.group(1))
            if amt.isdigit() and int(amt) >= 50000:
                data["sum_insured"] = amt
                break

    # 6. Total Premium (with GST):
    #    (a) "Net Premium Amt. 21344" / "Net Premium(With GST)" / "Total Premium"
    #    (b) 80D numeric "has paid ` 21344 towards premium"
    #    (c) Fallback: Gross Premium + GST (e.g. 18088 + 3256 = 21344)
    for pat in [
        r"(?i)Net\s*Premium\s*Amt\.?\s*[:\-]?\s*(?:Rs\.?|INR|₹|`)?\s*([\d,]+(?:\.\d+)?)\b",
        r"(?i)Net\s*Premium\s*\(\s*With\s*[\r\n\s]*GST\s*\)\s*[:\-]?\s*[\r\n\s]*(?:Rs\.?|INR|₹|`)?\s*([\d,]+(?:\.\d+)?)\b",
        r"(?i)Total\s*Premium\s*(?:Payable|Paid)?\s*[:\-]\s*[\r\n\s]*(?:Rs\.?|INR|₹|`)?\s*([\d,]+(?:\.\d+)?)\b",
        r"(?i)has\s+paid\s*(?:Rs\.?|INR|₹|`)\s*([\d,]+(?:\.\d+)?)\s*(?:\([^)]+\))?\s*towards\s+premium",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            amt = clean_amount(m_p.group(1))
            if amt.isdigit() and int(amt) > 0:
                data["premium"] = amt
                break

    if not data["premium"]:
        m_gp = re.search(r"(?i)Gross\s*Premium\s*[:\-]?\s*(?:Rs\.?|INR|₹|`)?\s*([\d,]+(?:\.\d+)?)\b", pdf_text)
        m_gst = re.search(r"(?i)\bGST\s*[:\-]?\s*(?:Rs\.?|INR|₹|`)?\s*([\d,]+(?:\.\d+)?)\b", pdf_text)
        if m_gp and m_gst:
            gp_a, gst_a = clean_amount(m_gp.group(1)), clean_amount(m_gst.group(1))
            if gp_a.isdigit() and gst_a.isdigit() and int(gp_a) > 0:
                data["premium"] = str(int(gp_a) + int(gst_a))

    # 7. PYP Number
    for pat in [
        r"(?i)Prev\.?\s*Policy\s*no\.?\s*[\r\n\s]*[:\-]\s*([A-Z0-9/\-]{8,30})\b",
        r"(?i)Previous\s*Policy\s*No\.?\s*[\r\n\s]*[:\-]\s*([A-Z0-9/\-]{8,30})\b",
    ]:
        m_pyp = re.search(pat, pdf_text)
        if m_pyp and re.search(r"\d{6,}", m_pyp.group(1)):
            data["pyp_number"] = m_pyp.group(1).strip()
            break

    # 8. DOB (Oldest Insured Person)
    dobs = []
    for m_sec in re.finditer(
        r"(?i)(?:Member\s+Details|Insured\s+Persons?\s+details)([\s\S]{0,2000}?)(?:Total\s+Sum\s+Insured|Floater\s+Sum\s+Insured|Optional\s+Cover|$)",
        pdf_text,
    ):
        for m_d in re.finditer(
            r"(\d{2}/\d{2}/(?:19|20)\d{2})\s*(?:[\r\n\s]*\(\s*\d{1,3}\s*\))?\s*[\r\n\s]+(?:M|F|Male|Female)\b",
            m_sec.group(1),
            re.I,
        ):
            dt = parse_any_date(m_d.group(1))
            if dt and dt.year >= 1920:
                dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    # 9. Premium Mode
    data["premium_mode"] = extract_premium_mode(pdf_text)
    if not data["premium_mode"] and re.search(r"(?i)QR_RENEWAL|ONLINE|UPI|PORTAL", pdf_text):
        data["premium_mode"] = "ONLINE"
    return data
