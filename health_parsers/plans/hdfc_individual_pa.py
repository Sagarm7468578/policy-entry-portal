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


def is_hdfc_individual_pa(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)Individual\s+Personal\s+Accident", pdf_text)
        or re.search(r"(?i)HDHHLIP21346V|HDFPAIP\d+V", pdf_text)
    )


def parse_hdfc_individual_pa(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "PERSONAL ACCIDENT"
    data["sub_type"] = "PERSONAL ACCIDENT"

    # 1. Policy Number (supports spaced 19-digit format like "2820 2055 4137 7601 000")
    for pat in [
        r"(?i)Policy\s*No\.?\s*[:\-]\s*([0-9][0-9 \t]{14,26})",
        r"(?i)Policy\s*Number\s*[\r\n\s]*[:\-]?\s*([0-9][0-9 \t]{14,26})",
    ]:
        m_pol = re.search(pat, pdf_text)
        if m_pol:
            digits = re.sub(r"\s+", "", m_pol.group(1))
            if 15 <= len(digits) <= 22:
                data["policy_number"] = digits
                break

    # 2. Client Name
    for pat in [
        r"(?i)Policy\s*Holder[\u2018\u2019']?s?\s*Name\s*[\r\n]+\s*([^\r\n]{3,80})",
        r"(?i)Policy\s*Holder[\u2018\u2019']?s?\s*Name\s*[:\-]\s*([^\r\n]{3,80})",
        r"(?i)Dear\s+([^\r\n,]{3,80})",
    ]:
        m_nm = re.search(pat, pdf_text)
        if m_nm:
            cand = clean_person_name(m_nm.group(1).lstrip(" :-\t"))
            if cand and len(cand) >= 3 and cand not in ("CUSTOMER", "SIR", "MADAM"):
                data["client_name"] = cand
                break

    # 3. Agency (strips "AGENT :" / "BROKER :" prefix)
    for pat in [
        r"(?i)Intermediary\s*Name\s*[\r\n]+\s*([^\r\n]{2,90})",
        r"(?i)Intermediary\s*Name\s*[:\-]\s*([^\r\n]{2,90})",
        r"(?i)\b(?:AGENT|BROKER|POSP|IMD)\s*[:\-]\s*([^\r\n]{2,90})",
    ]:
        m_ag = re.search(pat, pdf_text)
        if m_ag:
            raw = m_ag.group(1).strip()
            if re.search(r"(?i)^Intermediary\s+Contact", raw):
                continue
            raw = re.sub(r"(?i)^\s*(?:AGENT|BROKER|POSP|IMD|DIRECT)\s*[:\-]\s*", "", raw)
            cand = shorten_agency_name(clean_person_name(raw))
            if cand and len(cand) >= 2:
                data["agency"] = cand
                break

    # 4. Inception & Expiry Dates
    date_tok = r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})"
    m_per = re.search(
        rf"(?i)Policy\s*Period[\s\S]{{0,50}}?From[\s\S]{{0,30}}?{date_tok}[\s\S]{{0,45}}?To[\s\S]{{0,30}}?{date_tok}",
        pdf_text,
    )
    if m_per:
        data["start_dt"] = parse_any_date(m_per.group(1))
        data["end_dt"] = parse_any_date(m_per.group(2))

    # 5. Sum Insured (handles inline AND stacked-column Benefits + Sum Insured table)
    m_ins = re.search(
        r"(?i)Insured\s+Persons?\s+Details([\s\S]{0,1800}?)(?:Nominee\s+Details|Premium\s+Calculation|$)",
        pdf_text,
    )
    if m_ins:
        ins_blk = m_ins.group(1)
        m_ad_inline = re.search(
            r"(?i)Accidental\s+Death[ \t]*[:\-]?[ \t]*(?:Rs\.?|INR|₹|`)?[ \t]*([\d,]{5,15}(?:\.\d{2})?)\b",
            ins_blk,
        )
        if m_ad_inline:
            amt = clean_amount(m_ad_inline.group(1))
            if amt.isdigit() and 50000 <= int(amt) <= 500000000:
                data["sum_insured"] = amt

        if not data["sum_insured"]:
            lines = [ln.strip() for ln in ins_blk.splitlines() if ln.strip()]
            benefit_lines = []
            amt_lines = []
            in_benefits = False
            for ln in lines:
                if re.fullmatch(r"(?i)(?:Self|Spouse|Son|Daughter|Father|Mother|Brother|Sister|Dependent\s+\w+)", ln):
                    in_benefits = True
                    continue
                if not in_benefits:
                    continue
                if re.fullmatch(r"(?:Rs\.?|INR|₹|`)?\s*[\d,]{5,12}(?:\.\d{2})?", ln):
                    amt_val = clean_amount(re.sub(r"^(?:Rs\.?|INR|₹|`)\s*", "", ln))
                    if amt_val.isdigit() and 10000 <= int(amt_val) <= 500000000:
                        amt_lines.append(int(amt_val))
                elif not amt_lines and re.search(r"[A-Za-z]{4,}", ln):
                    benefit_lines.append(ln.lower())

            if amt_lines:
                ad_idx = next((idx for idx, b in enumerate(benefit_lines) if "accidental death" in b or b == "death"), -1)
                if 0 <= ad_idx < len(amt_lines) and amt_lines[ad_idx] >= 50000:
                    data["sum_insured"] = str(amt_lines[ad_idx])
                else:
                    valid_amts = [a for a in amt_lines if a >= 50000]
                    if valid_amts:
                        data["sum_insured"] = str(max(valid_amts))

        if not data["sum_insured"]:
            cands = []
            for m_num in re.finditer(r"(?m)^\s*([\d,]{5,12}(?:\.\d{2})?)\s*$", ins_blk):
                amt = clean_amount(m_num.group(1))
                if amt.isdigit() and len(amt) <= 9:
                    v = int(amt)
                    if 50000 <= v <= 500000000:
                        cands.append(v)
            if cands:
                data["sum_insured"] = str(max(cands))

    # 6. Total Premium (Gross Premium)
    for pat in [
        r"(?i)Gross\s*Premium\s*[\r\n]+\s*(?:Rs\.?|INR|₹|`)?\s*([\d,]+(?:\.\d+)?)\b",
        r"(?i)Gross\s*Premium\s*[:\-]\s*(?:Rs\.?|INR|₹|`)?\s*([\d,]+(?:\.\d+)?)\b",
        r"(?i)Total\s*Premium\s*[:\-]?\s*[\r\n\s]*(?:Rs\.?|INR|₹|`)?\s*([\d,]+(?:\.\d+)?)\b",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            amt = clean_amount(m_p.group(1))
            if amt.isdigit() and int(amt) > 0:
                data["premium"] = amt
                break

    # 7. DOB (Oldest Insured Person — handles "01/01/1994(30)")
    dobs = []
    search_zone = m_ins.group(1) if m_ins else pdf_text
    for m_d in re.finditer(r"(\d{2}/\d{2}/(?:19|20)\d{2})\s*\(\s*\d{1,3}\s*\)", search_zone):
        dt = parse_any_date(m_d.group(1))
        if dt and dt.year >= 1920:
            dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    # 8. Premium Mode
    data["premium_mode"] = extract_premium_mode(pdf_text)
    return data
