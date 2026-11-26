import re
from health_parsers.common import (
    default_extracted_data,
    parse_any_date,
    fmt_date,
    clean_amount,
    clean_person_name,
    extract_premium_mode,
)


def is_manipal_cigna_sarvah(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)Manipal\s*Cigna\s+Sarvah", pdf_text)
        or re.search(r"(?i)MCIHLIP26038V", pdf_text)
    )


def parse_manipal_cigna_sarvah(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["sub_type"] = "MEDICLAIM"

    m_plan = re.search(r"(?i)ManipalCigna\s+(Sarvah\s*[-–]\s*[A-Za-z0-9]+)", pdf_text)
    if m_plan:
        data["plan_name"] = re.sub(r"\s*[-–]\s*", " ", m_plan.group(1)).strip().upper()
    else:
        data["plan_name"] = "SARVAH PARAM"

    m_pol = re.search(r"(?i)Policy\s*Number\s*[:\-]?\s*[\r\n\s]*([A-Z0-9/\-]{8,30})", pdf_text)
    if m_pol:
        data["policy_number"] = m_pol.group(1).strip()

    for pat in [
        r"(?i)POLICYHOLDER\s*DETAILS\s*:\s*[\r\n]+\s*Name\s*[:\-]\s*([^\r\n]{3,80})",
        r"(?i)Dear\s+([^\r\n,]{3,80}),",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1))
            if cand and len(cand) >= 3:
                data["client_name"] = cand
                break

    m_ag = re.search(r"(?i)Intermediary\s*Name\s*[:\-]\s*([^\r\n]{3,70})", pdf_text)
    if m_ag:
        ag = clean_person_name(m_ag.group(1))
        if ag == "SURESH KUMAR CHINCHINI":
            ag = "SURESH KUMAR CHINCHANI"
        data["agency"] = ag

    date_tok = r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})"
    m_st = re.search(rf"(?i)(?:Start\s*Date\s*[:\-]\s*|From\s*[:\-]\s*(?:\d{{2}}:\d{{2}}\s*hrs\s*on\s*)?){date_tok}", pdf_text)
    m_en = re.search(rf"(?i)(?:End\s*Date\s*[:\-]\s*|To\s*[:\-]\s*(?:\d{{2}}:\d{{2}}\s*hrs\s*on\s*)?){date_tok}", pdf_text)
    if m_st:
        data["start_dt"] = parse_any_date(m_st.group(1))
    if m_en:
        data["end_dt"] = parse_any_date(m_en.group(1))

    for pat in [
        r"(?i)Base\s*Sum\s*Insured\s*\(in\s*₹\)[\s\S]{0,120}?\b([\d,]{5,12})\b",
        r"(?i)100\d{6,8}\s*[\r\n]+\s*(\d{5,9})\s*[\r\n]+",
        r"(?i)MEDICLAIM\s*[\r\n]+\s*([\d,]{5,12})",
    ]:
        m_si = re.search(pat, pdf_text)
        if m_si:
            data["sum_insured"] = clean_amount(m_si.group(1))
            break

    for pat in [
        r"(?i)paid\s+the\s+premium\s+of\s*(?:Rs\.?|INR|₹)\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Receipt\s*[\r\n\s]*Amount[\s\S]{0,120}?([\d,]+\.\d{2})",
        r"(?i)Total\s*[\r\n\s]*Premium\s*\(₹\)[\s\S]{0,200}?([\d,]+\.\d{2})\s*$",
    ]:
        m_p = re.search(pat, pdf_text, flags=re.MULTILINE)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    m_prev = re.search(
        r"(?i)Previous\s+Insurance\s+Details([\s\S]{0,900}?)(?:BENEFITS\s+UNDER|$)",
        pdf_text,
    )
    if m_prev:
        joined = re.sub(r"-\s*[\r\n]+\s*", "-", m_prev.group(1))
        joined = re.sub(r"(?i)\b\d{2}[/\-][A-Za-z]{3}[/\-]\d{2,4}\b", " ", joined)
        m_pno = re.search(r"\b(\d{2}-\d{2}-\d{5,10}-\d{2}|[A-Z0-9]{2,8}[/\-]\d{4,}[A-Z0-9/\-]*|\d{10,22})\b", joined)
        if m_pno:
            data["pyp_number"] = m_pno.group(1).strip()

    cleaned_dob = re.sub(r"(\b\d{2}-[A-Za-z]{3}-)[\r\n\s]+((?:19|20)\d{2})\b", r"\1\2", pdf_text)
    dobs = []
    m_id = re.search(r"(?i)Full\s*Name\s*[\r\n]+\s*Customer\s*ID\s*[\r\n]+\s*DOB([\s\S]{0,600}?)(?:Valid\s*From|$)", cleaned_dob)
    if m_id:
        for d_str in re.findall(r"\b\d{2}-[A-Za-z]{3}-(?:19|20)\d{2}\b", m_id.group(1)):
            dt = parse_any_date(d_str)
            if dt:
                dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    m_pm = re.search(r"(?i)Payment\s*Mode[\s\S]{0,180}?\b(DIRECT\s*DEBIT|ONLINE|UPI|NEFT|RTGS|IMPS|CARD|CHEQUE|CHQ|CASH|ECS|NACH|AUTO\s*DEBIT)\b", pdf_text)
    if m_pm:
        tok = re.sub(r"\s+", "", m_pm.group(1).upper())
        if tok in {"DIRECTDEBIT", "ONLINE", "UPI", "NEFT", "RTGS", "IMPS", "CARD"}:
            data["premium_mode"] = "ONLINE"
        elif tok in {"CHEQUE", "CHQ"}:
            data["premium_mode"] = "CHEQUE"
        elif tok in {"ECS", "NACH", "AUTODEBIT"}:
            data["premium_mode"] = "AUTO DEBIT"
        elif tok == "CASH":
            data["premium_mode"] = "CASH"
    if not data["premium_mode"]:
        data["premium_mode"] = extract_premium_mode(pdf_text)

    return data
