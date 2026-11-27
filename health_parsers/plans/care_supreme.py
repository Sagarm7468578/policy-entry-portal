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


def is_care_supreme(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)Plan\s*Name\s*[\r\n\s]*[:\-]?\s*Care\s+Supreme", pdf_text)
        or re.search(r"(?i)Proposal\s*Form\s*[\-\s]*['\"]?CARE\s+SUPREME", pdf_text)
        or re.search(r"(?i)CHIHLIP23128V", pdf_text)
    )


def parse_care_supreme(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "CARE SUPREME"
    data["sub_type"] = "MEDICLAIM"

    for pat in [
        r"(?i)Policy\s*No\.?\s*[:\-]?\s*[\r\n\s]*([0-9]{7,16})\b",
        r"(?i)Policy\s*Number\s*[:\-]?\s*[\r\n\s]*([0-9]{7,16})\b",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            data["policy_number"] = m_pol.group(1).strip()
            break

    for pat in [
        r"(?i)Policyholder\s*[\r\n]+\s*Gender\s*[\r\n]+\s*Date\s*Of\s*Birth\s*[\r\n]+\s*Client\s*ID\s*[\r\n]+\s*([^\r\n]{3,80})",
        r"(?i)Dear\s+([^\r\n,]{3,80})",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1))
            if cand and len(cand) >= 3 and cand not in ("CUSTOMER", "SIR", "MADAM"):
                data["client_name"] = cand
                break

    m_ag = re.search(
        r"(?i)Intermediary\s*Details\s*[\r\n]+\s*Name\s*[\r\n]+\s*Code\s*[\r\n]+\s*Contact\s*Details\s*[\r\n]+\s*([^\r\n]{3,80})",
        pdf_text,
    )
    if m_ag:
        cand = clean_person_name(m_ag.group(1))
        if cand and len(cand) >= 2:
            data["agency"] = shorten_agency_name(cand)

    date_tok = r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})"
    m_st = re.search(rf"(?i)Policy\s*Period\s*\-\s*Start\s*Date\s*[\r\n\s]*(?:[\d:]+\s*hrs\s*)?{date_tok}", pdf_text)
    if m_st:
        data["start_dt"] = parse_any_date(m_st.group(1))
    m_en = re.search(rf"(?i)Policy\s*Period\s*\-\s*End\s*Date\s*[\r\n\s]*(?:Midnight\s*)?{date_tok}", pdf_text)
    if m_en:
        data["end_dt"] = parse_any_date(m_en.group(1))
    if not data["start_dt"] or not data["end_dt"]:
        m_pp = re.search(rf"(?i){date_tok}\s+to\s+{date_tok}", pdf_text)
        if m_pp:
            data["start_dt"] = data["start_dt"] or parse_any_date(m_pp.group(1))
            data["end_dt"] = data["end_dt"] or parse_any_date(m_pp.group(2))

    m_ins = re.search(
        r"(?i)Details\s+of\s+Insured\s+Person([\s\S]{0,1600}?)(?:Details\s+of\s+Cover|Medical\s+History|Contact\s+details|Intermediary\s+Details|Schedule\s+of\s+Benefits|$)",
        pdf_text,
    )
    if m_ins:
        amts = [clean_amount(a) for a in re.findall(r"\b(\d{1,2}(?:,\d{2})*,\d{3}(?:\.\d{2})?)\b", m_ins.group(1))]
        amts = [a for a in amts if a.isdigit() and int(a) >= 100000]
        if amts:
            data["sum_insured"] = amts[0]
    if not data["sum_insured"]:
        m_si2 = re.search(r"(?i)Sum\s*Insured\s*[\r\n]+\s*([\d,]{5,15})\b", pdf_text)
        if m_si2:
            data["sum_insured"] = clean_amount(m_si2.group(1))

    for pat in [
        r"(?i)Premium\s*Paid\s*[\r\n\s]*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)([\d,]+(?:\.\d{2}))\s*[\r\n]+\s*Total\b",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    # PYP Number: (a) Portability table OR (b) Renewal "Previous Insurer Details" first row
    m_port = re.search(
        r"(?i)Portability\s+Details\s+of\s+the\s+Insured([\s\S]{0,1400}?)(?:Continuity\s+Benefit|Add-on\s+Policy|For\s+Care\s+Health|$)",
        pdf_text,
    )
    if m_port:
        m_exp_pol = re.search(
            r"([A-Z0-9/\-]{8,30})\s*[\r\n]+\s*\d{2}\-[A-Za-z]{3}\-\d{4}",
            m_port.group(1),
        )
        if m_exp_pol and re.search(r"\d{6,}", m_exp_pol.group(1)):
            data["pyp_number"] = m_exp_pol.group(1).strip()

    if not data["pyp_number"]:
        m_prev_sec = re.search(
            r"(?i)Previous\s+Insurer\s+Details\s+of\s+the\s+Insured([\s\S]{0,1200}?)(?:For\s+Care\s+Health|Service\s+Branch|$)",
            pdf_text,
        )
        if m_prev_sec:
            m_first_pyp = re.search(
                r"(?i)([A-Z0-9/\-]{7,30})\s*[\r\n]+\s*\d{2}\-[A-Za-z]{3}\-\d{4}",
                m_prev_sec.group(1),
            )
            if m_first_pyp and re.search(r"\d{6,}", m_first_pyp.group(1)):
                data["pyp_number"] = m_first_pyp.group(1).strip()

    if not data["pyp_number"]:
        m_pyp = re.search(r"(?i)Previous\s*Policy\s*(?:No\.?|Number)\s*[:\-]\s*([A-Z0-9/\-]{6,30})", pdf_text)
        if m_pyp and re.search(r"\d{5,}", m_pyp.group(1)):
            data["pyp_number"] = m_pyp.group(1).strip()

    # DOB: supports both Fresh/Port ("RELATION\nDOB") and Renewal ("DOB\nRELATION")
    dobs = []
    if m_ins:
        for m_d in re.finditer(
            r"(?i)(?:MEMBER|SELF|SPOUSE|SON|DAUGHTER|FATHER|MOTHER)\s*[\r\n]+\s*(\d{2}\-[A-Za-z]{3}\-(?:19|20)\d{2})"
            r"|(\d{2}\-[A-Za-z]{3}\-(?:19|20)\d{2})\s*[\r\n]+\s*(?:MEMBER|SELF|SPOUSE|SON|DAUGHTER|FATHER|MOTHER)\b",
            m_ins.group(1),
        ):
            dt = parse_any_date(m_d.group(1) or m_d.group(2))
            if dt and dt.year >= 1920:
                dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    data["premium_mode"] = extract_premium_mode(pdf_text)
    return data
