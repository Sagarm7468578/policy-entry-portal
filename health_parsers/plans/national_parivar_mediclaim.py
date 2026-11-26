import re
from health_parsers.common import (
    default_extracted_data,
    parse_any_date,
    fmt_date,
    clean_amount,
    clean_person_name,
    extract_premium_mode,
)


def is_national_parivar_mediclaim(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)(?:New\s+)?National\s+Parivar\s*Mediclaim", pdf_text)
        or re.search(r"(?i)NICHLIP25037V", pdf_text)
    )


def _extract_national_agency(pdf_text: str) -> str:
    # National Insurance bilingual header: "Sales Channel Details ... नाम /Name: Mrs Sunanda Mangal ..."
    m_sc = re.search(
        r"(?i)Sales\s*Channel\s*Details([\s\S]{0,450}?)(?:UIN\s*No|Customer\s*Care|Printed\s*on|$)",
        pdf_text,
    )
    if m_sc:
        block = m_sc.group(1)
        m_nm = re.search(r"(?i)(?:/\s*)?Name\s*[:\-]\s*([^\r\n]{3,80})", block)
        if m_nm:
            raw = m_nm.group(1)
            raw = re.split(r"(?i)(?:Contact\s*Number|संपकर|संपर्क|Mobile|Phone|Email|E-mail|\d{6,})", raw)[0]
            cand = clean_person_name(raw)
            if cand and len(cand) >= 3:
                return cand
    return ""


def _extract_national_pyp(pdf_text: str) -> str:
    # National lists multiple previous policies with Dt.DD/MM/YYYY — pick the most recent one
    m_sec = re.search(
        r"(?i)Previous\s*Policy\s*Number\s*and\s+Expiry\s*Date([\s\S]{0,700}?)(?:Rupees|General\s*Summary|Government\s*Subsidy|Basic\s*Cover|$)",
        pdf_text,
    )
    if not m_sec:
        return ""
    sec = m_sec.group(1)
    pairs = re.findall(
        r"([A-Z0-9/\-]{10,25})[^\d\r\n]{0,25}Dt\.?\s*(\d{2}[/\-]\d{2}[/\-]\d{2,4})",
        sec,
        flags=re.IGNORECASE,
    )
    best_dt = None
    best_pno = ""
    for pno, d_str in pairs:
        dt = parse_any_date(d_str)
        if dt and (best_dt is None or dt > best_dt):
            best_dt = dt
            best_pno = pno.strip()
    if best_pno:
        return best_pno

    ids = re.findall(r"\b\d{14,22}\b", sec)
    return ids[-1] if ids else ""


def _extract_national_dob(pdf_text: str) -> str:
    m_sec = re.search(
        r"(?i)Individual\s+member\s+details([\s\S]{0,1800}?)(?:Cumulative\s*Bonus|Optional\s*Copayment|Nominee\s*Details|$)",
        pdf_text,
    )
    sec = m_sec.group(1) if m_sec else ""
    dobs = []
    if sec:
        for d_str in re.findall(r"\b\d{2}[/\-]\d{2}[/\-](?:19|20)\d{2}\b", sec):
            dt = parse_any_date(d_str)
            if dt and dt.year >= 1920:
                dobs.append(dt)
    return fmt_date(min(dobs)) if dobs else ""


def parse_national_parivar_mediclaim(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "PARIVAR MEDICLAIM"
    data["sub_type"] = "MEDICLAIM"

    # 1. Policy Number
    m_pol = re.search(r"(?i)Policy\s*Number\s*[:\-]\s*[\r\n\s]*([A-Z0-9/\-]{10,30})", pdf_text)
    if m_pol:
        data["policy_number"] = m_pol.group(1).strip()

    # 2. Client Name
    for pat in [
        r"(?i)Customer\s*Name\s*[:\-]\s*([^\r\n]{3,80})",
        r"(?i)Details\s*Of\s*Receiver\s*[:\-]\s*([^\r\n]{3,80})",
        r"(?i)This\s+is\s+to\s+certify\s+that\s+([^\r\n]{3,70}?)\s+has\s+paid",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1))
            if cand and len(cand) >= 3:
                data["client_name"] = cand
                break

    # 3. Agency (Sales Channel Details -> Name)
    data["agency"] = _extract_national_agency(pdf_text)

    # 4. Policy Period
    date_tok = r"(\d{2}[/\-]\d{2}[/\-]\d{2,4})"
    m_per = re.search(
        rf"(?i)Policy\s*Effective\s*from\s*[:\-]?\s*(?:00:00\s*hours,?\s*)?(?:on\s*)?{date_tok}\s*to\s*[\r\n\s]*(?:midnight\s*of\s*)?{date_tok}",
        pdf_text,
    )
    if not m_per:
        m_per = re.search(rf"(?i)period\s+from\s+{date_tok}\s+to\s+{date_tok}", pdf_text)
    if m_per:
        data["start_dt"] = parse_any_date(m_per.group(1))
        data["end_dt"] = parse_any_date(m_per.group(2))

    # 5. Premium (Total Amount / Total Premium)
    for pat in [
        r"(?i)Total\s*Amount\s*[\r\n\s]*(?:`|Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Total\s*Premium\s*[\r\n\s]*(?:`|Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Total\s*Value\s*\(In\s*figures\)\s*[:\-]?\s*(?:`|Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    # 6. Sum Insured
    for pat in [
        r"(?i)Basic\s*Cover\s*Sum\s*Insured\s*[\r\n\s]*(?:`|Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Floater\s*Sum\s*Insured\s*\(SI\)\s*[:\-]?\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_si = re.search(pat, pdf_text)
        if m_si:
            data["sum_insured"] = clean_amount(m_si.group(1))
            break

    # 7. PYP Number
    data["pyp_number"] = _extract_national_pyp(pdf_text)

    # 8. DOB
    data["dob"] = _extract_national_dob(pdf_text)

    # 9. Premium Mode (e.g. Instrument number EASI... -> ONLINE, 6-digit -> CHEQUE)
    m_inst = re.search(r"(?i)by\s+Instrument\s+number\s*[\r\n\s]*([A-Z0-9/\-]{4,35})", pdf_text)
    if m_inst:
        inst = m_inst.group(1).strip().upper()
        if re.fullmatch(r"\d{6}", inst):
            data["premium_mode"] = "CHEQUE"
        elif re.match(r"^(?:EASI|PG|IPG|EPG|UPI|NEFT|RTGS|IMPS|ONL|PAY|TXN|OPS)", inst) or len(inst) >= 10:
            data["premium_mode"] = "ONLINE"
    if not data["premium_mode"]:
        data["premium_mode"] = extract_premium_mode(pdf_text)

    return data
