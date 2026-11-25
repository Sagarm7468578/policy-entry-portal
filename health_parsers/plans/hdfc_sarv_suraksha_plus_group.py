import re
from health_parsers.common import (
    default_extracted_data,
    parse_any_date,
    clean_amount,
)


def is_hdfc_sarv_suraksha_plus_group(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)sarv\s*suraksha\s*plus\s*\(\s*group\s*\)", pdf_text)
        or re.search(r"(?i)HDFHLGP25043V", pdf_text)
    )


def parse_hdfc_sarv_suraksha_plus_group(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "SARV SURAKSHA PLUS (GROUP)"
    data["sub_type"] = "PERSONAL ACCIDENT"
    data["skip_dob_fallback"] = True  # Group policy: stamp duty notification date (09-01-2018) ko DOB na banaye

    # 1. Policy Number
    m_pol = re.search(r"(?i)Policy\s*(?:Number|No\.?)\s*[:\-]?\s*[\r\n\s]*([A-Z0-9/\-]{8,30})", pdf_text)
    if m_pol:
        data["policy_number"] = m_pol.group(1).strip()

    # 2. Client / Policyholder Name (Schedule -> 1. Name & Address of the Policyholder)
    m_name = re.search(
        r"(?i)1\.\s*Name\s*&\s*Address\s*of\s*the\s*Policyholder\s*[\r\n]+\s*([^\r\n]+)",
        pdf_text,
    )
    if m_name:
        raw_name = re.sub(r"\s+", " ", m_name.group(1)).strip(" .,:-_")
        raw_name = re.sub(r"(?i)^\s*(?:M/S\.?|MR\.?|MRS\.?|MS\.?|SMT\.?|SHRI\.?)\s+", "", raw_name)
        data["client_name"] = raw_name.upper()

    # Fallback: Cover letter line right after date
    if not data["client_name"]:
        m_cover = re.search(
            r"(?i)(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\s*[\r\n]+\s*([^\r\n]+)",
            pdf_text,
        )
        if m_cover:
            cand = re.sub(r"\s+", " ", m_cover.group(1)).strip(" .,:-_")
            if cand and not re.search(r"(?i)^dear\s+customer", cand):
                data["client_name"] = cand.upper()

    # 3. Intermediary / Agency Name
    m_ag = re.search(r"(?i)2\.\s*Intermediary\s*Name\s*[:\-]?\s*[\r\n\s]*([^\r\n]+)", pdf_text)
    if not m_ag:
        m_ag = re.search(r"(?i)Intermediary\s*Name\s*[:\-]\s*([^\r\n]+)", pdf_text)
    if m_ag:
        ag_val = re.sub(r"\s+", " ", m_ag.group(1)).strip(" .,:-_")
        ag_val = re.sub(r"(?i)^\s*(?:MR\.?|MRS\.?|MS\.?|SMT\.?|SHRI\.?)\s+", "", ag_val)
        data["agency"] = ag_val.upper()

    # 4. Policy Period (From ... To ...)
    m_from = re.search(
        r"(?i)From\s*(?:00:01\s*hours)?\s*[:\-]\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4}|\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})",
        pdf_text,
    )
    if m_from:
        data["start_dt"] = parse_any_date(m_from.group(1))

    m_to = re.search(
        r"(?i)To\s*(?:\(?\s*Midnight\s*\)?)?\s*[:\-]\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4}|\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})",
        pdf_text,
    )
    if m_to:
        data["end_dt"] = parse_any_date(m_to.group(1))

    # 5. Sum Insured (Maximum Any One Life Limit; fallback to Accumulation / Total SI)
    m_si = re.search(
        r"(?i)Maximum\s*Any\s*One\s*Life\s*Limit\s*[:\-]?\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        pdf_text,
    )
    if not m_si:
        m_si = re.search(
            r"(?i)(?:Total\s*Sum\s*Insured\s*Consider\s*is|Maximum\s*Accumulation\s*Limit)\s*[:\-]?\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
            pdf_text,
        )
    if m_si:
        data["sum_insured"] = clean_amount(m_si.group(1))

    # 6. Premium (Total Amount Payable)
    m_prem = re.search(
        r"(?i)Total\s*Amount\s*Payable\s*[\r\n\s]*(?:Rs\.?|INR|₹)?\s*[\r\n\s]*([\d,]+(?:\.\d+)?)",
        pdf_text,
    )
    if m_prem:
        data["premium"] = clean_amount(m_prem.group(1))

    # 7. PYP Number (if present)
    m_pyp = re.search(
        r"(?i)(?:Previous\s*Policy\s*(?:No\.?|Number)|Expiring\s*Policy\s*(?:No\.?|Number))\s*[:\-]?\s*([A-Z0-9/\-]{8,30})",
        pdf_text,
    )
    if m_pyp:
        data["pyp_number"] = m_pyp.group(1).strip()

    return data
