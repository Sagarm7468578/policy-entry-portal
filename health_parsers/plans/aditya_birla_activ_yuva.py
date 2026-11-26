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


def is_aditya_birla_activ_yuva(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)Product\s*Name\s*[:\-]?\s*[\r\n\s]*Activ\s+Yuva\b", pdf_text)
        or re.search(r"(?i)Activ\s+Yuva\s*[\r\n]+\s*POLICY\s+SCHEDULE", pdf_text)
        or re.search(r"(?i)ADIHLIP27047V", pdf_text)
    )


def parse_aditya_birla_activ_yuva(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "ACTIV YUVA"
    data["sub_type"] = "MEDICLAIM"

    # 1. Policy Number
    for pat in [
        r"(?i)Policy\s*Number\s*[:\-]?\s*[\r\n\s]*([0-9]{2}\-[0-9]{2}\-[0-9A-Z\-]{6,22})",
        r"(?i)POLICY\s*NO\.?\s*[:\-]?\s*([0-9]{2}\-[0-9]{2}\-[0-9A-Z\-]{6,22})",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            data["policy_number"] = m_pol.group(1).strip()
            break

    # 2. Client Name
    for pat in [
        r"(?i)Policyholder\s*Name\s*[\r\n]+\s*([^\r\n]{3,80})",
        r"(?i)Proposer\s*Name\s*[:\-]\s*[\r\n\s]*([^\r\n]{3,80})",
        r"(?i)(?:Hi|Dear)\s+([^\r\n,]{3,80})",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1))
            if cand and len(cand) >= 3:
                data["client_name"] = cand
                break

    # 3. Agency
    for pat in [
        r"(?i)Intermediary\s*Name\s*[\r\n]+\s*([^\r\n]{3,80})",
        r"(?i)Intermediary\s*[\r\n]+\s*Name\s*[\r\n]+\s*([^\r\n]{3,80})",
    ]:
        m_ag = re.search(pat, pdf_text)
        if m_ag:
            cand = clean_person_name(m_ag.group(1))
            if cand and len(cand) >= 2:
                data["agency"] = shorten_agency_name(cand)
                break

    # 4. Inception & Expiry Dates
    date_tok = r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})"
    for pat in [
        rf"(?i)Start\s*Date\s*(?:&\s*Time\s*)?[\r\n\s]*of\s*Policy\s*[:\-]?\s*[\r\n\s]*(?:[\d:]+\s*hrs?\s*on\s*)?{date_tok}",
        rf"(?i)Policy\s*Start\s*Date\s*[:\-]?\s*[\r\n\s]*(?:[\d:]+\s*hrs?\s*on\s*)?{date_tok}",
    ]:
        m_st = re.search(pat, pdf_text)
        if m_st:
            data["start_dt"] = parse_any_date(m_st.group(1))
            if data["start_dt"]:
                break

    for pat in [
        rf"(?i)Expiry\s*Date\s*(?:&\s*Time\s*)?[\r\n\s]*of\s*Policy\s*[:\-]?\s*[\r\n\s]*(?:[\d:]+\s*hrs?\s*on\s*)?{date_tok}",
        rf"(?i)Policy\s*End\s*Date\s*[:\-]?\s*[\r\n\s]*(?:[\d:]+\s*hrs?\s*on\s*)?{date_tok}",
    ]:
        m_en = re.search(pat, pdf_text)
        if m_en:
            data["end_dt"] = parse_any_date(m_en.group(1))
            if data["end_dt"]:
                break

    # 5. Base Sum Insured
    m_si_sec = re.search(
        r"(?i)Base\s*Sum\s*[\r\n\s]*Insured([\s\S]{0,600}?)(?:Continued\s+and\s+to\s+be\s+read|Yuva\s+Health\s+Check|$)",
        pdf_text,
    )
    if m_si_sec:
        amts = [clean_amount(a) for a in re.findall(r"\b(\d[\d,]{4,14})\b", m_si_sec.group(1))]
        amts = [a for a in amts if a.isdigit() and int(a) >= 100000]
        if amts:
            data["sum_insured"] = amts[0]

    # 6. Total Premium
    for pat in [
        r"(?i)receipt\s+of\s+premium\s+amount\s+of\s*(?:INR|Rs\.?|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Total\s*Premium\s*Paid[\s\S]{0,120}?(\d[\d,]+(?:\.\d+)?)\s*[\r\n]+\s*Mode\s*of\s*Premium",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    # 7. PYP Number (Policy Details OR Portability table previous insurer policy no.)
    m_pyp = re.search(r"(?i)Previous\s*Policy\s*Number\s*[\r\n]+\s*([0-9A-Z/\-]{8,30})", pdf_text)
    if m_pyp and re.search(r"\d{4,}", m_pyp.group(1)) and m_pyp.group(1).strip().upper() != "NA":
        data["pyp_number"] = m_pyp.group(1).strip()

    if not data["pyp_number"]:
        m_port = re.search(
            r"(?i)Previous\s+Insurer[\s\S]{0,120}?Previous[\r\n\s]+Policy[\r\n\s]+Number([\s\S]{0,2200}?)(?:Correspondence\s+Address|For\s+Claims|$)",
            pdf_text,
        )
        if m_port:
            port_block = m_port.group(1)
            port_joined = re.sub(
                r"([A-Z0-9/\-]{5,})\s*[\r\n]+\s*([0-9\-]{2,10})\s*(?=[\r\n]+\s*(?:Floater|Individual)\b)",
                r"\1\2",
                port_block,
                flags=re.I,
            )
            curr_pol = re.sub(r"\s+", "", data["policy_number"])
            for m_row in re.finditer(
                r"(?i)\b(?:Ltd\.?|Limited)\s*[\r\n]+\s*([A-Z0-9/\-]{8,30})\s*[\r\n]+\s*(?:Floater|Individual)\b",
                port_joined,
            ):
                pno = re.sub(r"\s+", "", m_row.group(1))
                if pno and pno != curr_pol and re.search(r"\d{6,}", pno):
                    data["pyp_number"] = pno
                    break

    # 8. DOB (Oldest Insured Person)
    dobs = []
    m_dob_sec = re.search(
        r"(?i)Pre-existing\s*Disease\s*\(PED\)[\s\S]{0,40}?Waiting\s*Period#?([\s\S]{0,1200}?)(?:Maternity\s+Waiting|Base\s+Sum|$)",
        pdf_text,
    )
    if m_dob_sec:
        for m_d in re.finditer(r"\b(\d{2}/\d{2}/(?:19|20)\d{2})\b", m_dob_sec.group(1)):
            dt = parse_any_date(m_d.group(1))
            if dt and dt.year >= 1920 and (not data["start_dt"] or dt < data["start_dt"]):
                dobs.append(dt)
    if not dobs:
        m_card = re.search(r"(?i)Membership\s*No\.?\s*[\r\n]+\s*DOB([\s\S]{0,600})", pdf_text)
        if m_card:
            for m_d in re.finditer(r"\b(\d{2}/[A-Za-z]{3}/(?:19|20)\d{2})\b", m_card.group(1)):
                dt = parse_any_date(m_d.group(1))
                if dt and dt.year >= 1920:
                    dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    # 9. Premium Mode
    data["premium_mode"] = extract_premium_mode(pdf_text)
    return data
