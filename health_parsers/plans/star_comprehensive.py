import re
from health_parsers.common import (
    default_extracted_data,
    parse_any_date,
    fmt_date,
    clean_amount,
    clean_person_name,
    shorten_agency_name,
)


def is_star_comprehensive(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)Star\s+Comprehensive\s+Insurance", pdf_text)
        or re.search(r"(?i)SHAHLIP22028V|SHAHLIP24\d+V", pdf_text)
    )


def _extract_star_agency(pdf_text: str) -> str:
    m_block = re.search(
        r"(?i)Intermediary[\r\n\s]*Code([\s\S]{0,1400}?)(?:Total\s*Premium|Period\s*of\s*Insurance)",
        pdf_text,
    )
    block = m_block.group(1) if m_block else ""
    if not block:
        return ""

    stop_words = {
        "intermediary", "code", "policy", "category", "renewal", "year", "collection",
        "date", "inception", "first", "name", "optional", "cover", "loading", "discount",
        "premium", "base", "product", "phone", "no", "cgst", "sgst", "igst", "stamp",
        "duty", "total", "rs", "e-mail", "email", "mail", "id", "new", "fresh",
        "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth",
    }
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in block.splitlines()]

    def collect_continuation(start_idx: int) -> list:
        extra = []
        for j in range(start_idx + 1, min(start_idx + 3, len(lines))):
            nxt = lines[j].strip(" :.-_")
            if not nxt or re.search(r"[\d@/]", nxt):
                break
            nxt_words = [w.lower() for w in re.findall(r"[A-Za-z]+", nxt)]
            if not nxt_words or any(w in stop_words for w in nxt_words):
                break
            if re.fullmatch(r"[A-Za-z .&\-]{2,45}", nxt):
                extra.append(nxt)
            else:
                break
        return extra

    for idx, ln in enumerate(lines):
        m_sal = re.match(
            r"(?i)^:?\s*(?:MRS|MISS|MR|MS|DR|SMT|SHRI|M/S)(?:\.[ \t]*|[ \t]+)([A-Za-z][A-Za-z .&/\-]{1,60})$",
            ln,
        )
        if m_sal:
            parts = [m_sal.group(1).strip()] + collect_continuation(idx)
            val = clean_person_name(" ".join(parts))
            if val:
                return shorten_agency_name(val)

    for idx, ln in enumerate(lines):
        m_colon = re.match(r"^:\s*([A-Za-z][A-Za-z .&\-]{2,60})$", ln)
        if m_colon:
            s = m_colon.group(1).strip()
            low_words = [w.lower() for w in re.findall(r"[A-Za-z]+", s)]
            if low_words and not any(w in stop_words for w in low_words) and not re.search(r"[\d@/]", s):
                parts = [s] + collect_continuation(idx)
                return shorten_agency_name(clean_person_name(" ".join(parts)))

    return ""


def parse_star_comprehensive(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "STAR COMPREHENSIVE"
    data["sub_type"] = "MEDICLAIM"

    # 1. Policy Number
    for pat in [
        r"(?i)Renewal\s*Endorsement\s*No\.?\s*[:\-]?\s*([A-Z0-9/\-]{8,30})",
        r"(?i)Policy\s*No\.?\s*[\r\n\s]*[:\-]\s*[\r\n\s]*([A-Z0-9/\-]{8,30})",
        r"(?i)Attached\s+to\s+and\s+forming\s+part\s+of\s+Policy\s*No\.?\s*[:\-]?\s*([A-Z0-9/\-]{8,30})",
    ]:
        m = re.search(pat, pdf_text)
        if m and re.search(r"\d{6,}", m.group(1)):
            data["policy_number"] = m.group(1).strip()
            break

    # 2. Client Name
    for pat in [
        r"(?i)Customer\s*Name[ \t]*[:\-][ \t]*([^\r\n]{3,80})",
        r"(?i)Proposer\s*Name[ \t]*[\r\n]*[ \t]*[:\-][ \t]*[\r\n]*[ \t]*([^\r\n]{3,80})",
    ]:
        m = re.search(pat, pdf_text)
        if m:
            raw = re.split(r"(?i)\b(?:Cust\s*CKYC|CKYC|Customer\s*Code|Proposer\s*Code|GSTIN|Address)\b", m.group(1))[0]
            cand = clean_person_name(raw)
            if cand and len(cand) >= 3:
                data["client_name"] = cand
                break

    # 3. Previous Policy Number
    for pat in [
        r"(?i)Previous\s*Policy\s*No\.?[ \t]*[\r\n]*[ \t]*[:\-][ \t]*([^\r\n]{6,35})",
        r"(?i)towards\s+renewal\s+premium\s+of\s+policy[\r\n\s]+number\s*[:\-]?\s*[\r\n\s]*([A-Z0-9/\-]{8,35})",
    ]:
        m_pyp = re.search(pat, pdf_text)
        if m_pyp:
            cand_pyp = m_pyp.group(1).strip().rstrip(",.")
            if re.search(r"\d{5,}", cand_pyp) and cand_pyp != data["policy_number"]:
                data["pyp_number"] = cand_pyp
                break

    # 4. Agency
    data["agency"] = _extract_star_agency(pdf_text)

    # 5. Inception & Expiry Dates
    date_tok = r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})"
    m_per = re.search(
        rf"(?i)Period\s*of\s*Insurance[\s\S]{{0,120}}?From\s*[:\-]?\s*{date_tok}[\s\S]{{0,80}}?To[\s\S]{{0,40}}?(?:Midnight\s*of\s*)?{date_tok}",
        pdf_text,
    )
    if m_per:
        data["start_dt"] = parse_any_date(m_per.group(1))
        data["end_dt"] = parse_any_date(m_per.group(2))
    if not data["start_dt"] or not data["end_dt"]:
        m_cert = re.search(rf"(?i)for\s+the\s+Period\s+{date_tok}\s+To\s+{date_tok}", pdf_text)
        if m_cert:
            data["start_dt"] = data["start_dt"] or parse_any_date(m_cert.group(1))
            data["end_dt"] = data["end_dt"] or parse_any_date(m_cert.group(2))

    # 6. Sum Insured (handles multi-line "Basic Floater Sum Insured :\nRs. 10,00,000/-")
    for pat in [
        r"(?i)Basic\s*(?:Floater\s*)?Sum\s*Insured[ \t]*[:\-][ \t]*[\r\n\s]*(?:Rs\.?|INR|₹)?[ \t]*([\d,]+(?:\.\d+)?)",
        r"(?i)Sum\s*Insured\s*Under\s*Section\s*1\s*\(Health\)\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Sum\s*Insured[ \t]*[:\-][ \t]*(?:Rs\.?|INR|₹)?[ \t]*([\d,]+(?:\.\d+)?)",
    ]:
        m_si = re.search(pat, pdf_text)
        if m_si:
            amt = clean_amount(m_si.group(1))
            if amt.isdigit() and int(amt) >= 100000:
                data["sum_insured"] = amt
                break

    # 7. Total Premium
    for pat in [
        r"(?i)Total\s*Premium\s*[\r\n\s]*[:\-]?\s*[\r\n\s]*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Total\s*Invoice\s*Value\s*\(in\s*Figures\)\s*[\r\n\s]*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            amt = clean_amount(m_p.group(1))
            if amt.isdigit() and int(amt) > 0:
                data["premium"] = amt
                break

    # 8. Premium Mode
    m_rec = re.search(r"(?i)Payment\s+received\s+by\s+([^\r\n]{2,60})", pdf_text)
    if m_rec:
        seg = m_rec.group(1)
        if re.search(r"(?i)\b(?:Cheque|Chq\.?|DD)\b", seg):
            data["premium_mode"] = "CHEQUE"
        elif re.search(r"(?i)\b(?:Online|UPI|NEFT|RTGS|IMPS|Card|PG|Gateway|Razorpay|PayU|BillDesk)\b", seg):
            data["premium_mode"] = "ONLINE"
        elif re.search(r"(?i)\bCash\b", seg):
            data["premium_mode"] = "CASH"

    # 9. DOB (Oldest Insured Person from Details of Insured Persons — skips member inception dates)
    first_inc_dt = None
    m_finc = re.search(rf"(?i)Date\s*of\s*Inception[\r\n\s]*of\s*first\s*policy[\r\n\s]*{date_tok}", pdf_text)
    if m_finc:
        first_inc_dt = parse_any_date(m_finc.group(1))

    dobs = []
    m_tbl = re.search(
        r"(?i)(?:Details\s+of\s+Insured\s+Persons|Insured\s+Person\s+Details)\s*:?([\s\S]{0,2600}?)(?:Star\s+Extra\s+Protect|Nominee\s+Details|Entered\s+by|$)",
        pdf_text,
    )
    if m_tbl:
        tbl_txt = m_tbl.group(1)
        for m_d in re.finditer(
            r"(?i)(?:Self|Spouse|Son|Daughter|Father|Mother|Brother|Sister|Dependent[^\r\n]*)\s*[\r\n]+\s*\d{1,3}\s*[\r\n]+\s*(\d{2}\-[A-Za-z]{3}\-(?:19|20)\d{2})"
            r"|(?:Male|Female)\s*[\r\n]+\s*(\d{2}\-[A-Za-z]{3}\-(?:19|20)\d{2})\s*[\r\n]+\s*\d{1,3}\b",
            tbl_txt,
        ):
            dt = parse_any_date(m_d.group(1) or m_d.group(2))
            if dt and dt.year >= 1920 and dt != first_inc_dt and dt != data["start_dt"]:
                dobs.append(dt)
        if not dobs:
            for m_d in re.finditer(r"\b(\d{2}\-[A-Za-z]{3}\-(?:19|20)\d{2})\b", tbl_txt):
                dt = parse_any_date(m_d.group(1))
                if dt and dt.year >= 1920 and dt != first_inc_dt and dt != data["start_dt"]:
                    dobs.append(dt)

    if dobs:
        data["dob"] = fmt_date(min(dobs))

    return data
