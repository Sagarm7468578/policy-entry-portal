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


def is_united_india_family_medicare(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)FAMILY\s+MEDICARE\s+POLICY", pdf_text)
        or re.search(r"(?i)UIIHLIP25037V|UIIHLIP20013V|UIIHLIP21\d+V|UIIHLIP22\d+V", pdf_text)
    )


def parse_united_india_family_medicare(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "FAMILY MEDICARE"
    data["sub_type"] = "MEDICLAIM"

    # 1. Policy Number (e.g. 1920002824P115364522)
    for pat in [
        r"(?i)Policy\s*(?:No\.?|Number)\s*[:\-]?\s*[\r\n\s]*([0-9]{10}[A-Z][0-9]{8,14})\b",
        r"(?i)Policy\s*(?:No\.?|Number)\s*[:\-]?\s*[\r\n\s]*([A-Z0-9/\-]{14,28})\b",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol and re.search(r"\d{8,}", m_pol.group(1)):
            data["policy_number"] = m_pol.group(1).strip()
            break

    # 2. Client Name (handles "MR MR. ASHWIN TRIPATHI /1778190867" & "Policyholder\nMR MR. ASHWIN TRIPATHI")
    for pat in [
        r"(?i)Name\s*/\s*ID\s+of\s*[\r\n\s]+Policyholder\s*[\r\n]+\s*([^\r\n]{3,90})",
        r"(?i)\bPolicyholder\s*[\r\n]+\s*([^\r\n]{3,90})",
        r"(?i)certify\s+that\s+([^\r\n]{3,90}?)\s+has\s+paid\b",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            raw_nm = m_nm.group(1).split("/")[0].lstrip(" :-\t")
            cand = clean_person_name(raw_nm)
            if cand and len(cand) >= 3 and cand not in ("CUSTOMER", "POLICYHOLDER", "INSURED"):
                data["client_name"] = cand
                break

    # 3. Agency ("Agent Name : VIPUL NEEMA" / "Agent Name\nVIPUL NEEMA")
    for pat in [
        r"(?i)Agent\s*Name\s*[\r\n\s]*[:\-]\s*([^\r\n]{2,80})",
        r"(?i)Agent\s*Name\s*[\r\n]+\s*([^\r\n]{2,80})",
        r"(?i)Intermediary\s*Name\s*[\r\n\s]*[:\-]?\s*([^\r\n]{2,80})",
    ]:
        m_ag = re.search(pat, pdf_text)
        if m_ag:
            raw_ag = m_ag.group(1).lstrip(" :-\t")
            if not re.search(r"(?i)\b(?:Code|Broker|Mobile|Email)\b", raw_ag):
                cand = shorten_agency_name(clean_person_name(raw_ag))
                if cand and len(cand) >= 2:
                    data["agency"] = cand
                    break

    # 4. Inception & Expiry Dates
    date_tok = r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})"
    for pat in [
        rf"(?i)Period\s*of\s*Insurance[\s\S]{{0,45}}?From[\s\S]{{0,35}}?{date_tok}[\s\S]{{0,45}}?To[\s\S]{{0,35}}?{date_tok}",
        rf"(?i)for\s+the\s+period\s+from[\s\S]{{0,30}}?{date_tok}[\s\S]{{0,35}}?To[\s\S]{{0,30}}?{date_tok}",
    ]:
        m_per = re.search(pat, pdf_text)
        if m_per:
            data["start_dt"] = parse_any_date(m_per.group(1))
            data["end_dt"] = parse_any_date(m_per.group(2))
            if data["start_dt"] and data["end_dt"]:
                break

    # 5. Sum Insured ("Family Floater SI( )\n300,000.00" or CIS "Family Floater Basis\nRs. 300000")
    for pat in [
        r"(?i)Family\s*Floater\s*SI\s*\([^)]*\)\s*[\r\n\s]*[:\-]?\s*(?:Rs\.?|INR|₹)?\s*([\d,]{5,15}(?:\.\d{2})?)\b",
        r"(?i)Family\s*Floater\s*Basis\s*[\r\n]+\s*(?:Rs\.?|INR|₹)\s*([\d,]{5,15}(?:\.\d{2})?)\b",
        r"(?i)Sum\s*Insured\s*[:\-]\s*(?:Rs\.?|INR|₹)?\s*([\d,]{5,15}(?:\.\d{2})?)\b",
    ]:
        m_si = re.search(pat, pdf_text)
        if m_si:
            amt = clean_amount(m_si.group(1))
            if amt.isdigit() and int(amt) >= 50000:
                data["sum_insured"] = amt
                break

    # 6. Total Premium (with GST)
    for pat in [
        r"(?i)\bTotal\s*:\s*[\r\n\s]*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d{2})?)\b",
        r"(?i)has\s+paid\s*[\r\n\s]*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d{2})?)\s*\(",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            amt = clean_amount(m_p.group(1))
            if amt.isdigit() and int(amt) > 0:
                data["premium"] = amt
                break

    # 7. Previous Policy Number ("Previous Policy No.\n1903002823P112247945")
    for pat in [
        r"(?i)Previous\s*Policy\s*No\.?\s*[:\-]?\s*[\r\n\s]*([0-9]{10}[A-Z][0-9]{8,14})\b",
        r"(?i)Previous\s*Policy\s*No\.?\s*[:\-]?\s*[\r\n\s]*([A-Z0-9/\-]{10,30})\b",
        r"(?i)Details\s+of\s+Previous\s+Policies[\s\S]{0,200}?\b([0-9]{10}[A-Z][0-9]{8,14})\b",
    ]:
        m_pyp = re.search(pat, pdf_text)
        if m_pyp and re.search(r"\d{6,}", m_pyp.group(1)):
            cand_pyp = m_pyp.group(1).strip()
            if cand_pyp != data["policy_number"]:
                data["pyp_number"] = cand_pyp
                break

    # 8. DOB (Oldest Insured Person from Insured Details table — "26/08/1956\n& 68/M")
    dobs = []
    m_ins = re.search(
        r"(?i)Insured\s+Details([\s\S]{0,2200}?)(?:Optional\s+Cover|Total\s+Basic\s+Premium|$)",
        pdf_text,
    )
    if m_ins:
        for m_d in re.finditer(
            r"(\d{2}/\d{2}/(?:19|20)\d{2})\s*[\r\n\s]*&\s*\d{1,3}\s*/\s*[MF]\b",
            m_ins.group(1),
            re.I,
        ):
            dt = parse_any_date(m_d.group(1))
            if dt and dt.year >= 1920:
                dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    # 9. Premium Mode (if absent, verified_defaults marks FILL MANUAL)
    data["premium_mode"] = extract_premium_mode(pdf_text)
    return data
