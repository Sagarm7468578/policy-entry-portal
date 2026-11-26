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


def is_hdfc_arogya_sanjeevani(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)Arogya\s+Sanjeevani\s+Policy\s*,?\s*HDFC\s+ERGO", pdf_text)
        or re.search(r"(?i)HDFHLIP20175V", pdf_text)
    )


def _extract_hdfc_as_payment_mode(pdf_text: str) -> str:
    m_pay = re.search(r"(?i)Payment\s*Details\s*[:\-]\s*([^\r\n]{3,140})", pdf_text)
    if m_pay:
        seg = m_pay.group(1)
        if re.search(r"(?i)\b(?:BizDirect|Online|UPI|NEFT|RTGS|IMPS|PG|Gateway|Card|Net\s*Banking|EASI\d+|OPS[A-Z0-9]+|PG_COLLECTION)\b", seg):
            return "ONLINE"
        if re.search(r"(?i)\b(?:Cheque|Chq\.?|DD|Demand\s*Draft)\b", seg):
            return "CHEQUE"
        if re.search(r"(?i)\bCash\b", seg):
            return "CASH"
        # Leading token before comma: 6-digit instrument no -> CHEQUE; 10+ digit ref -> ONLINE
        m_num = re.match(r"\s*(\d{5,22})\b", seg)
        if m_num:
            n = m_num.group(1)
            if len(n) == 6:
                return "CHEQUE"
            if len(n) >= 10:
                return "ONLINE"
    return extract_premium_mode(pdf_text)


def parse_hdfc_arogya_sanjeevani(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "AROGYA SANJEEVANI"
    data["sub_type"] = "MEDICLAIM"

    # 1. Policy Number (clean 19 digits)
    for pat in [
        r"(?i)Policy\s*No\.?\s*[\r\n\s]*[:\-]\s*([\d\s]{15,28})",
        r"(?i)policy\s*reference\s*no\.?\s*([\d]{15,22})",
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
        r"(?i)Agent\s*Name\s*[:\-]\s*([^\r\n]{3,80})",
        r"(?i)Intermediary\s*Name\s*[:\-]\s*([^\r\n]{3,80})",
    ]:
        m_ag = re.search(pat, pdf_text)
        if m_ag:
            raw = re.sub(r"(?i)^\s*(?:AGENT|BROKER|POSP|IMD|DIRECT)\s*[:\-]\s*", "", m_ag.group(1).strip())
            cand = clean_person_name(raw)
            if cand and len(cand) >= 2:
                data["agency"] = shorten_agency_name(cand)
                break

    # 4. Inception & Expiry Dates
    date_tok = r"(\d{2}[/\-]\d{2}[/\-]\d{2,4})"
    m_per = re.search(
        rf"(?i)Period\s*of\s*Insurance[\s\S]{{0,40}}?From\s+{date_tok}[\s\S]{{0,40}}?To\s+{date_tok}",
        pdf_text,
    )
    if not m_per:
        m_per = re.search(rf"(?i)for\s+the\s+period\s+{date_tok}\s+to\s+{date_tok}", pdf_text)
    if m_per:
        data["start_dt"] = parse_any_date(m_per.group(1))
        data["end_dt"] = parse_any_date(m_per.group(2))

    # 5. Base Sum Insured
    for pat in [
        r"(?i)Sum\s*Insured\s*opted\s*[:\-]\s*(?:Rs\.?|INR|₹)?\s*([\d,]{5,15})",
        r"(?i)Basic\s*Sum\s*Insured\s*\([₹`]\)\s*[\r\n\s]*([\d,]{5,15})",
    ]:
        m_si = re.search(pat, pdf_text)
        if m_si:
            data["sum_insured"] = clean_amount(m_si.group(1))
            break

    # 6. Total Premium
    for pat in [
        r"(?i)Grand\s*Total\s*\-\s*Premium\s*including\s*GST\s*[\r\n]+\s*([\d,]+(?:\.\d+)?)",
        r"(?i)received\s+an\s+amount\s+of\s*[\r\n\s]*(?:₹|`|Rs\.?|INR)?\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    # 7. DOB (Oldest Insured Person)
    dobs = []
    m_card = re.search(r"(?i)Insured\s+Name\s*[\r\n]+\s*Member\s+ID([\s\S]{0,1200}?)(?:HDFC\s+ERGO|Proposal\s+No|$)", pdf_text)
    if m_card:
        for m_d in re.finditer(r"(\d{2}[/\-]\d{2}[/\-](?:19|20)\d{2})\s*[\r\n\s]+(?:Male|Female|M|F)\b", m_card.group(1), re.I):
            dt = parse_any_date(m_d.group(1))
            if dt and dt.year >= 1920:
                dobs.append(dt)
    if not dobs:
        m_tbl = re.search(r"(?i)Insured\s+Person[’'`]?s\s+Details\s*&\s*Sum\s+Insured([\s\S]{0,1600}?)(?:Schedule\s+of\s+Coverage|Note\s*:|$)", pdf_text)
        if m_tbl:
            joined = re.sub(r"(\d{2}/\d{2}/\d{2,3})\s*[\r\n]+\s*(\d{1,2})\b", r"\1\2", m_tbl.group(1))
            for m_d in re.finditer(r"(?:Male|Female|M|F)\s*[\r\n\s]+(\d{2}/\d{2}/(?:19|20)\d{2})", joined, re.I):
                dt = parse_any_date(m_d.group(1))
                if dt and dt.year >= 1920:
                    dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    # 8. Premium Mode
    data["premium_mode"] = _extract_hdfc_as_payment_mode(pdf_text)

    # 9. PYP Number auto-derived via verified_defaults
    return data
