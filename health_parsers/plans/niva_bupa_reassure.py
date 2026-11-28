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


def is_niva_bupa_reassure(pdf_text: str) -> bool:
    # Registered AFTER reassure3 & reassure2 so it strictly handles ReAssure 1.0
    if re.search(r"(?i)ReAssure\s*[23]\.0", pdf_text):
        return False
    return bool(
        re.search(r"(?i)Product\s*Name\s*:\s*ReAssure\b", pdf_text)
        or re.search(r"(?i)NBHHLIP23107V|NBHHLIP21\d+V", pdf_text)
    )


def parse_niva_bupa_reassure(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "REASSURE"
    data["sub_type"] = "MEDICLAIM"

    # 1. Policy Number
    for pat in [
        r"(?i)Policy\s*Number\s*[:\-]?\s*[\r\n\s]*([0-9]{10,18})\b",
        r"(?i)Policy\s*No\.?\s*[:\-]?\s*[\r\n\s]*([0-9]{10,18})\b",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            data["policy_number"] = m_pol.group(1).strip()
            break

    # 2. Client Name
    for pat in [
        r"(?i)Policyholder\s*Name\s*[:\-]\s*([^\r\n]{3,80})",
        r"(?i)Policyholder\s*Name\s*[\r\n]+\s*([^\r\n]{3,80})",
        r"(?i)Dear\s+([^\r\n,]{3,80})",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1).lstrip(" :-\t"))
            if cand and len(cand) >= 3 and cand not in ("CUSTOMER", "SIR", "MADAM"):
                data["client_name"] = cand
                break

    # 3. Agency (strips appended intermediary code like "Kirti Laddha - Hyd0189942" -> "KIRTI LADDHA")
    m_ag = re.search(
        r"(?i)Intermediary\s*Details\s*[\r\n]+\s*Intermediary\s*Name\s*[\r\n]+\s*Intermediary\s*Code\s*[\r\n]+\s*Intermediary\s*Contact\s*No\.?\s*[\r\n]+\s*([^\r\n]{2,90})",
        pdf_text,
    )
    if not m_ag:
        m_ag = re.search(r"(?i)Intermediary\s*Name\s*[:\-]\s*([^\r\n]{2,90})", pdf_text)
    if m_ag:
        raw_ag = re.sub(r"\s*[\-\u2013\u2014]\s*[A-Za-z]{2,6}\d{4,}[A-Za-z0-9]*\s*$", "", m_ag.group(1).strip())
        cand = shorten_agency_name(clean_person_name(raw_ag))
        if cand:
            data["agency"] = cand

    # 4. Inception & Expiry Dates
    date_tok = r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})"
    m_st = re.search(
        rf"(?i)Policy\s*Commencement\s*Date(?:\s*and\s*Time)?\s*#?\s*(?:From\s*)?[:\-]?\s*[\r\n\s]*{date_tok}",
        pdf_text,
    )
    m_en = re.search(
        rf"(?i)Policy\s*Expiry\s*Date(?:\s*and\s*Time)?\s*[\r\n\s]*(?:To\s*)?[:\-]?\s*[\r\n\s]*{date_tok}",
        pdf_text,
    )
    if m_st:
        data["start_dt"] = parse_any_date(m_st.group(1))
    if m_en:
        data["end_dt"] = parse_any_date(m_en.group(1))

    # 5. Base Sum Insured
    for pat in [
        r"(?i)Base\s*Sum\s*Insured\s*[\r\n]+\s*(?:Rs\.?|INR|₹)?\s*([\d,]{5,15})\b",
        r"(?i)Cover\s*Details[\s\S]{0,400}?\r?\n\s*(?:Mr\.?|Mrs\.?|Ms\.?|Miss\.?|Mast\.?|Dr\.?)[^\r\n]+\r?\n\s*([\d,]{5,15})\b",
    ]:
        m_si = re.search(pat, pdf_text)
        if m_si:
            amt = clean_amount(m_si.group(1))
            if amt.isdigit() and int(amt) >= 100000:
                data["sum_insured"] = amt
                break

    # 6. Total Premium WITH GST (Gross Premium Rs. — NEVER Net Premium before GST)
    for pat in [
        r"(?i)Gross\s*Premium\s*\(Rs\.?\)\s*[\r\n]+\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)\b",
        r"(?i)tax\s+benefits\s+up\s+to\s*(?:Rs\.?|INR|₹)\s*([\d,]+(?:\.\d+)?)\b",
        r"(?i)Gross\s*Premium\s*\(Rs\.?\)\s*\(in\s*words\)\s*[\r\n]+[\s\S]{0,140}?([\d,]+\.\d{2})\s*[\r\n]+[A-Za-z \-]+Only\b",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            amt = clean_amount(m_p.group(1))
            if amt.isdigit() and int(amt) > 0:
                data["premium"] = amt
                break

    # 7. Previous Policy Number (for Portability cases like "intimate you that your policy 320100502110004438 of ...")
    m_port_pyp = re.search(
        r"(?i)intimate\s+you\s+that\s+your\s+policy\s*[\r\n\s]+([A-Z0-9/\-]{8,32})\s+of\b",
        pdf_text,
    )
    if m_port_pyp and re.search(r"\d{6,}", m_port_pyp.group(1)):
        cand_pyp = m_port_pyp.group(1).strip()
        if cand_pyp != data["policy_number"]:
            data["pyp_number"] = cand_pyp

    # 8. DOB (Oldest Insured Person)
    dobs = []
    for m_d in re.finditer(
        r"(\d{2}/\d{2}/(?:19|20)\d{2})\s*[\r\n\s]+(?:Male|Female|M|F)\b",
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
    return data
