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
        re.search(r"(?i)Sarv\s*Suraksha\s*Plus\s*\(\s*Group\s*\)", pdf_text)
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

    is_corporate_schedule = bool(re.search(r"(?i)1\.\s*Name\s*&\s*Address\s*of\s*the\s*Policyholder", pdf_text))

    # 1. Policy / Certificate Number (single-line digit capture)
    for pat in [
        r"(?i)Certificate\s*No\.?[ \t]*[\r\n]*[ \t]*[:\-][ \t]*([\d \t]{15,28})",
        r"(?i)policy\s*reference\s*no\.?[ \t]*([0-9]{15,22})",
        r"(?i)(?<!Master\s)Policy\s*(?:No\.?|Number)[ \t]*[:\-][ \t]*[\r\n\s]*([\d \t]{15,28})",
        r"(?i)Policy\s*number[ \t]*[\r\n]+[ \t]*([0-9]{15,22})",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            digits = re.sub(r"\s+", "", m_pol.group(1))
            if len(digits) >= 15:
                data["policy_number"] = digits
                break

    # 2. Client Name (avoids "Dear Customer")
    for pat in [
        r"(?i)1\.\s*Name\s*&\s*Address\s*of\s*the\s*Policyholder\s*[\r\n]+\s*([^\r\n]{2,90})",
        r"(?i)Proposer\s*Name\s*[\r\n\s]*[:\-]\s*([^\r\n]{3,80})",
        r"(?i)Dear\s+([^\r\n,]{3,80})",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1))
            if cand and len(cand) >= 2 and cand not in ("CUSTOMER", "SIR", "MADAM", "POLICYHOLDER"):
                data["client_name"] = cand
                break

    # 3. Agency
    for pat in [
        r"(?i)Broker\s*Name\s*[:\-]\s*[\r\n\s]*([^\r\n]{2,80})",
        r"(?i)Intermediary\s*Name\s*[:\-]\s*[\r\n\s]*([^\r\n]{2,80})",
        r"(?i)Agent\s*Name\s*[:\-]\s*[\r\n\s]*([^\r\n]{2,80})",
    ]:
        m_ag = re.search(pat, pdf_text)
        if m_ag:
            raw = re.sub(r"(?i)^\s*(?:AGENT|BROKER|POSP|IMD|DIRECT)\s*[:\-]\s*", "", m_ag.group(1).strip())
            cand = shorten_agency_name(clean_person_name(raw))
            if cand:
                data["agency"] = cand
                break

    # 4. Inception & Expiry Dates (DD/MM/YYYY + "January 29, 2025")
    date_tok = r"(\d{2}[/\-]\d{2}[/\-]\d{2,4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})"
    m_per = re.search(
        rf"(?i)(?:Period\s*of\s*Insurance|Policy\s*Period)[\s\S]{{0,60}}?From(?:\s*[\d:]+\s*hours\s*[:\-]?)?\s*{date_tok}[\s\S]{{0,60}}?To(?:\s*\(?Midnight\)?\s*[:\-]?)?\s*{date_tok}",
        pdf_text,
    )
    if m_per:
        data["start_dt"] = parse_any_date(m_per.group(1))
        data["end_dt"] = parse_any_date(m_per.group(2))

    # 5. Sum Insured
    if is_corporate_schedule:
        for pat in [
            r"(?i)Total\s*Sum\s*Insured\s*Consider(?:ed)?\s*is\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
            r"(?i)Maximum\s*Accumulation\s*Limit\s*[:\-]?\s*[\r\n\s]*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
            r"(?i)Maximum\s*Any\s*One\s*Life\s*Limit\s*[:\-]?\s*[\r\n\s]*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        ]:
            m_si = re.search(pat, pdf_text)
            if m_si:
                data["sum_insured"] = clean_amount(m_si.group(1))
                break
    else:
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
        r"(?i)Total\s*Amount\s*Payable\s*[\r\n\s]*(?:Rs\.?|INR|₹)?\s*[\r\n\s]*([\d,]+(?:\.\d+)?)",
        r"(?i)Total\s*Premium\s*including\s*GST\s*[:\-]?\s*[\r\n\s]*([\d,]+(?:\.\d+)?)",
        r"(?i)Gross\s*Premium\s*(?:\([A-Z]\))?\s*[\r\n]+\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    # 7. DOB
    if is_corporate_schedule:
        data["dob"] = "GROUP POLICY"
        data["skip_dob_fallback"] = True
    else:
        dobs = []
        m_ins_sec = re.search(
            r"(?i)Insured\s+Person\s+Details([\s\S]{0,1200}?)(?:Nominee\s+Details|Schedule\s+of\s+Coverage|$)",
            pdf_text,
        )
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
    return data
