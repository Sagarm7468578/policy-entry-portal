import re
from health_parsers.common import (
    default_extracted_data,
    parse_any_date,
    fmt_date,
    clean_amount,
    clean_person_name,
    shorten_agency_name,
)


def is_star_super_surplus(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)Super\s+Surplus", pdf_text)
        or re.search(r"(?i)SHAHLIP22032V|SHAHLIP22034V|SHAHLIP21\d+V", pdf_text)
    )


def _extract_star_agency(pdf_text: str) -> str:
    stop_words = {
        "intermediary", "code", "policy", "category", "renewal", "year", "collection",
        "date", "inception", "first", "name", "optional", "cover", "loading", "discount",
        "premium", "base", "product", "phone", "no", "cgst", "sgst", "igst", "stamp",
        "duty", "total", "rs", "e-mail", "email", "mail", "id", "new", "fresh",
        "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth",
        "customer", "number", "tel", "mobile", "address",
    }

    def _scan_block(block: str) -> str:
        if not block:
            return ""
        lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in block.splitlines()]

        def collect_continuation(start_idx: int) -> list:
            extra = []
            for j in range(start_idx + 1, min(start_idx + 3, len(lines))):
                nxt = lines[j].strip(" :.-_")
                if not nxt or re.search(r"[\d@/]", nxt) or lines[j].startswith(":"):
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

    # Standard Star layout: agency appears AFTER Intermediary Code
    m_after = re.search(
        r"(?i)Intermediary[\r\n\s]*Code([\s\S]{0,1400}?)(?:Total\s*Premium|Period\s*of\s*Insurance|$)",
        pdf_text,
    )
    if m_after:
        found = _scan_block(m_after.group(1))
        if found:
            return found

    # PREMIA layout: agency appears right BEFORE Intermediary Code
    m_pos = re.search(r"(?i)Intermediary[\r\n\s]*Code", pdf_text)
    if m_pos:
        before_blk = pdf_text[max(0, m_pos.start() - 450):m_pos.start()]
        found = _scan_block(before_blk)
        if found:
            return found

    return ""


def parse_star_super_surplus(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "STAR SUPER SURPLUS"
    data["sub_type"] = "TOP UP"

    # 1. Policy Number (supports standard + PREMIA reverse-order Renewal Endorsement No)
    for pat in [
        r"(?i)Renewal\s*Endorsement\s*No\.?[ \t]*[:\-][ \t]*([A-Z0-9/\-]{8,30})",
        r"(?i)Attached\s+to\s+and\s+forming\s+part\s+of\s+Policy\s*No\.?\s*[:\-]?\s*([A-Z0-9/\-]{8,30})",
        r"(?i)Health\s+Insurance\s+Policy\s*[\-\:]\s*([A-Z0-9/\-]{8,30})",
        r"(?i)Policy\s*No\.?\s*[\r\n\s]*[:\-]\s*[\r\n\s]*([A-Z0-9/\-]{8,30})",
    ]:
        m = re.search(pat, pdf_text)
        if m and re.search(r"\d{6,}", m.group(1)):
            data["policy_number"] = m.group(1).strip()
            break

    # 2. Client Name (handles colon-before AND PREMIA newline-before-colon formats)
    for pat in [
        r"(?i)Customer\s*Name[ \t]*[:\-][ \t]*([^\r\n]{3,80})",
        r"(?i)Customer\s*Name[ \t]*[\r\n]+[ \t]*([^\r\n:]{3,80})[ \t]*[\r\n]+[ \t]*:",
        r"(?i)Proposer(?:'s)?\s*Name[ \t]*[\r\n]*[ \t]*[:\-][ \t]*[\r\n]*[ \t]*([^\r\n]{3,80})",
        r"(?i)Proposer(?:'s)?\s*Name[ \t]*[\r\n]+[ \t]*([^\r\n:]{3,80})[ \t]*[\r\n]+[ \t]*:",
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
        r"(?i)towards\s+renewal\s+premium\s+of\s+policy[\r\n\s]+number\s*[:\-]?\s*[\r\n\s]*([A-Z0-9/\-]{8,35})",
        r"(?i)Previous\s*Policy\s*No\.?[ \t]*[\r\n]*[ \t]*[:\-][ \t]*([^\r\n]{6,35})",
    ]:
        m_pyp = re.search(pat, pdf_text)
        if m_pyp:
            cand_pyp = m_pyp.group(1).strip().rstrip(",.")
            if re.search(r"\d{5,}", cand_pyp) and cand_pyp != data["policy_number"]:
                data["pyp_number"] = cand_pyp
                break

    # 4. Agency
    data["agency"] = _extract_star_agency(pdf_text)

    # 5. Inception & Expiry Dates (standard + PREMIA stacked dates)
    date_tok = r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})"
    m_per = re.search(
        rf"(?i)Period\s*of\s*Insurance[\s\S]{{0,120}}?From\s*[:\-]?\s*{date_tok}[\s\S]{{0,80}}?To[\s\S]{{0,40}}?(?:Midnight\s*of\s*)?{date_tok}",
        pdf_text,
    )
    if not m_per:
        m_per = re.search(
            rf"(?i)Period\s*of\s*Insurance[\s\S]{{0,40}}?FROM[\s\S]{{0,25}}?{date_tok}\s*(?:00:00)?\s*[\r\n]+\s*{date_tok}",
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

    # 6. Sum Insured (inline OR PREMIA stacked table: GOLD / SILVER -> 1000000)
    m_si = re.search(
        r"(?i)(?:Basic\s*(?:Floater\s*)?)?Sum\s*Insured[ \t]*[:\-][ \t]*(?:Rs\.?|INR|₹)?[ \t]*([\d,]+(?:\.\d+)?)",
        pdf_text,
    )
    if m_si:
        amt = clean_amount(m_si.group(1))
        if amt.isdigit() and int(amt) >= 100000:
            data["sum_insured"] = amt
    if not data["sum_insured"]:
        m_si_premia = re.search(
            r"(?i)Sum\s*Insured\s*:[\s\S]{0,120}?\b(?:GOLD|SILVER)\b\s*[\r\n]+\s*([\d,]{6,15})\b",
            pdf_text,
        )
        if m_si_premia:
            amt = clean_amount(m_si_premia.group(1))
            if amt.isdigit() and int(amt) >= 100000:
                data["sum_insured"] = amt

    # 7. Total Premium (with GST — handles standard, renewal clause, and PREMIA Tax Invoice)
    for pat in [
        r"(?i)In\s+consideration\s+of\s+payment\s+of\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)\s*/?\-\s*towards\s+renewal",
        r"(?i)Total\s*Premium\s*[\r\n\s]*[:\-]?\s*[\r\n\s]*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Total\s*Invoice\s*Value\s*\(in\s*Figures\)\s*[\r\n\s]*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Total\s*Premium[\s\S]{0,60}?Re\.?\s*[\r\n\s]*([\d,]+(?:\.\d+)?)",
        r"(?i)Total\s*Invoice\s*Value[\s\S]{0,300}?Rs\.?\s*([\d,]+(?:\.\d+)?)\s*[\r\n]+Rupees",
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

    # 9. DOB (Oldest Insured Person — supports DD-MMM-YYYY & DD/MM/YYYY; excludes inception/period dates)
    first_inc_dt = None
    m_finc = re.search(rf"(?i)Date\s*of\s*Inception[\r\n\s]*of\s*first\s*policy[\r\n\s]*:?[\r\n\s]*{date_tok}", pdf_text)
    if m_finc:
        first_inc_dt = parse_any_date(m_finc.group(1))

    dobs = []
    m_tbl = re.search(
        r"(?i)(?:Details\s+of\s+Insured\s+Persons|Insured\s+Person\s+Details)\s*:?([\s\S]{0,2600}?)(?:Nominee\s+Details|Entered\s+by|$)",
        pdf_text,
    )
    if m_tbl:
        for m_d in re.finditer(r"\b(\d{2}\-[A-Za-z]{3}\-(?:19|20)\d{2}|\d{2}/\d{2}/(?:19|20)\d{2})\b", m_tbl.group(1)):
            dt = parse_any_date(m_d.group(1))
            if dt and dt.year >= 1920 and dt != first_inc_dt and dt != data["start_dt"] and dt != data["end_dt"]:
                dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    return data
