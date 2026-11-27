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


def is_manipal_cigna_sarvah(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)ManipalCigna\s+Sarvah", pdf_text)
        or re.search(r"(?i)MCIHLIP25035V|MCIHLIP26038V|MCIHLIP27040V", pdf_text)
    )


def _normalize_mc_mode(tok: str) -> str:
    t = re.sub(r"\s+", "", str(tok or "").upper())
    if t in ("CHEQUE", "CHQ", "DD"):
        return "CHEQUE"
    if t == "CASH":
        return "CASH"
    if t in ("ECS", "NACH"):
        return "AUTO DEBIT"
    if t:
        return "ONLINE"
    return ""


def parse_manipal_cigna_sarvah(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["sub_type"] = "MEDICLAIM"
    if re.search(r"(?i)Sarvah\s*[\-\s]*Uttam", pdf_text):
        data["plan_name"] = "SARVAH UTTAM"
    elif re.search(r"(?i)Sarvah\s*[\-\s]*Pratham", pdf_text):
        data["plan_name"] = "SARVAH PRATHAM"
    else:
        data["plan_name"] = "SARVAH PARAM"

    for pat in [
        r"(?i)Policy\s*Number\s*[:\-]?\s*[\r\n\s]*(SARVA[A-Z0-9]{6,20})",
        r"(?i)Policy\s*Number\s*[:\-]?\s*[\r\n\s]*([A-Z0-9]{10,22})",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            data["policy_number"] = m_pol.group(1).strip()
            break

    for pat in [
        r"(?i)POLICYHOLDER\s*DETAILS\s*:?[\s\S]{0,60}?Name\s*[:\-]\s*([^\r\n]{3,80})",
        r"(?i)Dear\s+([^\r\n,]{3,80})",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1))
            if cand and len(cand) >= 3:
                data["client_name"] = cand
                break

    m_ag = re.search(r"(?i)Intermediary\s*Name\s*[:\-]\s*([^\r\n]{3,80})", pdf_text)
    if m_ag:
        cand = shorten_agency_name(clean_person_name(m_ag.group(1)))
        cand = re.sub(r"\bCHINCHINI\b", "CHINCHANI", cand)
        data["agency"] = cand

    date_tok = r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})"
    m_st = re.search(rf"(?i)Start\s*Date\s*[:\-]\s*{date_tok}", pdf_text)
    if not m_st:
        m_st = re.search(rf"(?i)From\s*:\s*[\d:]+\s*hrs\s*on\s*{date_tok}", pdf_text)
    if m_st:
        data["start_dt"] = parse_any_date(m_st.group(1))

    m_en = re.search(rf"(?i)End\s*Date\s*[:\-]\s*{date_tok}", pdf_text)
    if not m_en:
        m_en = re.search(rf"(?i)To\s*:\s*[\d:]+\s*hrs\s*on\s*{date_tok}", pdf_text)
    if m_en:
        data["end_dt"] = parse_any_date(m_en.group(1))

    for pat in [
        r"(?i)(?:Base\s*)?Sum\s*Insured\s*\(in\s*(?:₹|Rs\.?)\)[\s\S]{0,160}?[\r\n]+\s*([\d,]{5,15})",
        r"(?i)Customer\s*ID[\s\S]{0,400}?(\d{6,10})\s*[\r\n]+\s*(?:0|10000|25000|50000)\s*[\r\n]+",
    ]:
        m_si = re.search(pat, pdf_text)
        if m_si:
            amt = clean_amount(m_si.group(1))
            if amt.isdigit() and int(amt) >= 100000:
                data["sum_insured"] = amt
                break

    for pat in [
        r"(?i)paid\s+the\s+premium\s+of\s*[\r\n\s]*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Total\s*premium\s*paid\s*\(A\+B\+C\)\s*[\r\n]+\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    # Supports both newer ("Payment Mode -> DIRECTDEBIT") & older ("R003673537\nCHEQUE\nDate\nReceipt\nAmount\nPayment\nMode")
    mode_tok = r"(DIRECT\s*DEBIT|ONLINE|UPI|NEFT|RTGS|IMPS|CARD|CHEQUE|CHQ|DD|CASH|ECS|NACH)"
    m_pm = re.search(rf"(?i)Payment\s*[\r\n\s]+Mode\s*[\r\n]+[\s\S]{{0,160}}?\b{mode_tok}\b", pdf_text)
    if not m_pm:
        m_pm = re.search(rf"(?i)\bR\d{{6,14}}\s*[\r\n]+\s*{mode_tok}\b[\s\S]{{0,80}}?Payment\s*[\r\n\s]+Mode\b", pdf_text)
    if not m_pm:
        m_pm = re.search(rf"(?i)\b{mode_tok}\b[\s\S]{{0,60}}?Date\s*[\r\n]+\s*Receipt\s*[\r\n]+\s*Amount\s*[\r\n]+\s*Payment\s*[\r\n\s]+Mode\b", pdf_text)
    if m_pm:
        data["premium_mode"] = _normalize_mc_mode(m_pm.group(1))
    else:
        data["premium_mode"] = extract_premium_mode(pdf_text)

    m_port = re.search(
        r"(?i)Previous\s+Insurance\s+Details\s*\(for\s+Portability\s+Policies\)\s*:?([\s\S]{0,1800}?)(?:BENEFITS\s+UNDER\s+THE\s+POLICY|Pre-existing\s+condition\s+related|$)",
        pdf_text,
    )
    if m_port:
        port_block = m_port.group(1)
        port_joined = re.sub(
            r"([A-Z0-9/\-]{5,})\s*[\r\n]+\s*([A-Z0-9/\-]{2,12})\s*(?=[\r\n]+\s*(?:MEDICLAIM|HEALTH|FLOATER|INDIVIDUAL|FAMILY)\b)",
            r"\1\2",
            port_block,
            flags=re.I,
        )
        m_pyp = re.search(
            r"(?i)\b([A-Z0-9/\-]{8,30})\s*[\r\n]+\s*(?:MEDICLAIM|HEALTH|FLOATER|INDIVIDUAL|FAMILY)\b",
            port_joined,
        )
        if m_pyp and re.search(r"\d{6,}", m_pyp.group(1)):
            data["pyp_number"] = m_pyp.group(1).strip()

    dobs = []
    m_card = re.search(r"(?i)(?:Customer\s*ID\s*[\r\n]+\s*DOB|INSURED\s*NAME\s*[\r\n]+\s*DOB)([\s\S]{0,800}?)(?:Valid\s+From|Claims\b|$)", pdf_text)
    if m_card:
        for m_d in re.finditer(r"\b(\d{2}\-[A-Za-z]{3}\-(?:19|20)\d{2})\b", m_card.group(1)):
            dt = parse_any_date(m_d.group(1))
            if dt and dt.year >= 1920:
                dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    return data
