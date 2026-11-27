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


def is_hdfc_sarv_suraksha_plus_group(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)Sarv\s+Suraksha\s+Plus\s*\(\s*Group\s*\)", pdf_text)
        or re.search(r"(?i)HDFHLGP25043V|HDFHLGP24020V", pdf_text)
    )


def _extract_ssp_payment_mode(pdf_text: str) -> str:
    m_pay = re.search(r"(?i)Payment\s*Details\s*[:\-]\s*([^\r\n]{3,140})", pdf_text)
    if m_pay:
        seg = m_pay.group(1)
        if re.search(r"(?i)\b(?:BizDirect|Online|UPI|NEFT|RTGS|IMPS|PG|Gateway|Card|Net\s*Banking|EASI\d+|OPS[A-Z0-9]+|PG_COLLECTION)\b", seg):
            return "ONLINE"
        if re.search(r"(?i)\b(?:Cheque|Chq\.?|DD|Demand\s*Draft)\b", seg):
            return "CHEQUE"
        if re.search(r"(?i)\bCash\b", seg):
            return "CASH"
        m_num = re.match(r"\s*(\d{5,22})\b", seg)
        if m_num:
            n = m_num.group(1)
            if len(n) == 6:
                return "CHEQUE"
            if len(n) >= 10:
                return "ONLINE"
    return extract_premium_mode(pdf_text)


def parse_hdfc_sarv_suraksha_plus_group(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "SARV SURAKSHA PLUS (GROUP)"
    data["sub_type"] = "PERSONAL ACCIDENT"

    # 1. Policy / Certificate Number (explicitly ignores Master Policy No.)
    for pat in [
        r"(?i)Certificate\s*No\.?\s*[\r\n\s]*[:\-]\s*([\d\s]{15,28})",
        r"(?i)policy\s*reference\s*no\.?\s*([\d]{15,22})",
        r"(?i)(?<!Master\s)Policy\s*No\.?\s*[:\-]\s*([\d\s]{15,28})",
        r"(?i)Policy\s*number\s*[\r\n]+\s*([\d]{15,22})",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            digits = re.sub(r"\s+", "", m_pol.group(1))
            if len(digits) >= 15:
                data["policy_number"] = digits
                break

    # 2. Client Name
    for pat in [
        r"(?i)Proposer\s*Name\s*[\r\n\s]*[:\-]\s*([^\r\n]{3,80})",
        r"(?i)Dear\s+([^\r\n,]{3,80})",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1))
            if cand and len(cand) >= 3:
                data["client_name"] = cand
                break

    # 3. Agency
    for pat in [
        r"(?i)Broker\s*Name\s*[:\-]\s*([^\r\n]{2,80})",
        r"(?i)Agent\s*Name\s*[:\-]\s*([^\r\n]{2,80})",
        r"(?i)Intermediary\s*Name\s*[:\-]\s*([^\r\n]{2,80})",
    ]:
        m_ag = re.search(pat, pdf_text)
        if m_ag:
            raw = re.sub(r"(?i)^\s*(?:AGENT|BROKER|POSP|IMD|DIRECT)\s*[:\-]\s*", "", m_ag.group(1).strip())
            cand = shorten_agency_name(clean_person_name(raw))
            if cand:
                data["agency"] = cand
                break

    # 4. Inception & Expiry Dates
    date_tok = r"(\d{2}[/\-]\d{2}[/\-]\d{2,4})"
    m_per = re.search(
        rf"(?i)Period\s*of\s*Insurance[\s\S]{{0,40}}?From\s+{date_tok}[\s\S]{{0,40}}?To\s+{date_tok}",
        pdf_text,
    )
    if m_per:
        data["start_dt"] = parse_any_date(m_per.group(1))
        data["end_dt"] = parse_any_date(m_per.group(2))

    # 5. Sum Insured (Insured Person Details Self row; fallback to Accident Death)
    m_ins_sec = re.search(
        r"(?i)Insured\s+Person\s+Details([\s\S]{0,1200}?)(?:Nominee\s+Details|Schedule\s+of\s+Coverage|$)",
        pdf_text,
    )
    if m_ins_sec:
        m_self = re.search(
            r"(?i)Self\s*[\r\n\s]+(?:Male|Female|M|F)\s*[\r\n\s]+\d{2}/\d{2}/\d{4}\s*[\r\n\s]+\d{2}/\d{2}/\d{4}\s*[\r\n\s]+([\d,]{5,15})",
            m_ins_sec.group(1),
        )
        if m_self:
            data["sum_insured"] = clean_amount(m_self.group(1))
        else:
            m_any = re.search(
                r"(?i)(?:Male|Female|M|F)\s*[\r\n\s]+\d{2}/\d{2}/\d{4}\s*[\r\n\s]+\d{2}/\d{2}/\d{4}\s*[\r\n\s]+([\d,]{5,15})",
                m_ins_sec.group(1),
            )
            if m_any:
                data["sum_insured"] = clean_amount(m_any.group(1))
    if not data["sum_insured"]:
        m_ad = re.search(r"(?i)Accident(?:al)?\s*Death\s*[\r\n]+\s*([\d,]{5,15})", pdf_text)
        if m_ad:
            data["sum_insured"] = clean_amount(m_ad.group(1))

    # 6. Total Premium (including GST)
    for pat in [
        r"(?i)Grand\s*Total\s*\-\s*Premium\s*including\s*GST\s*(?:\([A-Z]\))?\s*[\r\n]+\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Total\s*Premium\s*including\s*GST\s*[:\-]?\s*[\r\n\s]*([\d,]+(?:\.\d+)?)",
        r"(?i)Gross\s*Premium\s*(?:\([A-Z]\))?\s*[\r\n]+\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    # 7. DOB (Oldest Insured Person)
    dobs = []
    if m_ins_sec:
        for m_d in re.finditer(r"(?i)(?:Male|Female|M|F)\s*[\r\n\s]+(\d{2}/\d{2}/(?:19|20)\d{2})", m_ins_sec.group(1)):
            dt = parse_any_date(m_d.group(1))
            if dt and dt.year >= 1920:
                dobs.append(dt)
    if not dobs:
        m_card = re.search(r"(?i)Insured\s+Name\s*[\r\n]+\s*Member\s+ID([\s\S]{0,900})", pdf_text)
        if m_card:
            for m_d in re.finditer(r"(\d{2}/\d{2}/(?:19|20)\d{2})\s*[\r\n\s]+(?:Male|Female|M|F)\b", m_card.group(1), re.I):
                dt = parse_any_date(m_d.group(1))
                if dt and dt.year >= 1920:
                    dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    # 8. Premium Mode
    data["premium_mode"] = _extract_ssp_payment_mode(pdf_text)

    # 9. PYP Number auto-derived via verified_defaults
    return data
