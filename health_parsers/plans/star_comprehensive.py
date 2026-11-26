import re
from health_parsers.common import (
    default_extracted_data,
    parse_any_date,
    fmt_date,
    clean_amount,
    clean_person_name,
)


def is_star_comprehensive(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)Star\s+Comprehensive\s+(?:Insurance\s+Policy|Revised)", pdf_text)
        or re.search(r"(?i)SHAHLIP25037V", pdf_text)
    )


def _extract_comprehensive_agency(pdf_text: str) -> str:
    m_block = re.search(
        r"(?i)Intermediary[\r\n\s]*Code([\s\S]{0,1400}?)(?:Total\s*Premium|Period\s*of\s*Insurance)",
        pdf_text,
    )
    block = m_block.group(1) if m_block else ""
    if not block:
        return ""
    stop_words = {
        "intermediary", "code", "renewal", "year", "collection", "date", "inception",
        "first", "policy", "name", "optional", "cover", "loading", "discount",
        "premium", "phone", "no", "cgst", "sgst", "igst", "stamp", "duty", "total", "rs",
        "e-mail", "email", "mail", "id",
    }
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in block.splitlines()]
    for idx, ln in enumerate(lines):
        m_sal = re.match(
            r"(?i)^:?\s*(?:MRS|MISS|MR|MS|DR|SMT|SHRI|M/S)(?:\.[ \t]*|[ \t]+)([A-Za-z][A-Za-z .&/\-]{1,60})$",
            ln,
        )
        if m_sal:
            parts = [m_sal.group(1).strip()]
            for j in range(idx + 1, min(idx + 3, len(lines))):
                nxt = lines[j].strip(" :.-_")
                if not nxt or re.search(r"[\d@/]", nxt):
                    break
                nxt_words = [w.lower() for w in re.findall(r"[A-Za-z]+", nxt)]
                if not nxt_words or any(w in stop_words for w in nxt_words):
                    break
                if re.fullmatch(r"[A-Za-z .&\-]{2,45}", nxt):
                    parts.append(nxt)
                else:
                    break
            return clean_person_name(" ".join(parts))
    return ""


def parse_star_comprehensive(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "STAR COMPREHENSIVE"
    data["sub_type"] = "MEDICLAIM"

    for pat in [
        r"(?i)Renewal\s*Endorsement\s*No\.?\s*[:\-]?\s*([A-Z0-9/\-]{8,30})",
        r"(?i)Attached\s+to\s+and\s+forming\s+part\s+of\s+Policy\s*No\.?\s*[:\-]?\s*([A-Z0-9/\-]{8,30})",
        r"(?i)Policy\s*No\.?\s*[:\-]\s*([A-Z0-9/\-]{8,30})",
    ]:
        m = re.search(pat, pdf_text)
        if m:
            data["policy_number"] = m.group(1).strip()
            break

    for pat in [
        r"(?i)Customer\s*Name[ \t]*[:\-][ \t]*([^\r\n]{3,80})",
        r"(?i)Proposer\s*Name[ \t]*[\r\n]*[ \t]*[:\-][ \t]*[\r\n]*[ \t]*([^\r\n]{3,80})",
        r"(?i)This\s+is\s+to\s+certify\s+that\s+([A-Za-z][A-Za-z .]{2,80}?)\s+has\s+paid",
    ]:
        m = re.search(pat, pdf_text)
        if m:
            raw = re.split(r"(?i)\b(?:Cust\s*CKYC|CKYC|Customer\s*Code|Proposer\s*Code|GSTIN|Address)\b", m.group(1))[0]
            cand = clean_person_name(raw)
            if cand and len(cand) >= 3:
                data["client_name"] = cand
                break

    m_pyp = re.search(r"(?i)towards\s+renewal\s+premium\s+of\s+policy\s*number\s*[:\-]?\s*[\r\n\s]*([A-Z0-9/\-]{8,30})", pdf_text)
    if m_pyp:
        data["pyp_number"] = m_pyp.group(1).strip().rstrip(",.")

    data["agency"] = _extract_comprehensive_agency(pdf_text)

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
    if not data["end_dt"]:
        m_vt = re.search(rf"(?i)Valid\s*Till\s*[:\-]\s*{date_tok}", pdf_text)
        if m_vt:
            data["end_dt"] = parse_any_date(m_vt.group(1))

    # Sum Insured (Priority 1: Floater label; Priority 2: Individual table first comma-amount >= 1,00,000)
    m_si_lbl = re.search(r"(?i)Basic(?:\s+Floater)?\s+Sum\s*Insured[ \t]*[:\-][ \t]*(?:Rs\.?|INR|₹)?[ \t]*([\d,]+(?:\.\d+)?)", pdf_text)
    if m_si_lbl:
        data["sum_insured"] = clean_amount(m_si_lbl.group(1))
    else:
        m_tbl = re.search(r"(?i)Attached\s+to\s+and\s+forming\s+part\s+of\s+Policy\s*No[\s\S]{0,1200}?(?:Pre\s+Existing\s+Disease|Nominee\s+Details|$)", pdf_text)
        if m_tbl:
            joined = re.sub(r"(\d{1,2}(?:,\d{2})*,\d{1,2})\s*[\r\n]+\s*(\d{1,2})\b", r"\1\2", m_tbl.group(0))
            amts = [clean_amount(a) for a in re.findall(r"\b\d{1,2}(?:,\d{2})*,\d{3}\b", joined)]
            amts = [a for a in amts if a.isdigit() and int(a) >= 100000]
            if amts:
                data["sum_insured"] = amts[0]

    for pat in [
        r"(?i)Total\s*Premium\s*[\r\n\s]*[:\-]?\s*[\r\n\s]*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Total\s*Invoice\s*Value\s*\(in\s*Figures\)\s*[\r\n\s]*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    m_rec = re.search(r"(?i)Payment\s+received\s+by\s+([^\r\n]{2,60})", pdf_text)
    if m_rec:
        seg = m_rec.group(1)
        if re.search(r"(?i)\b(?:Cheque|Chq\.?|DD)\b", seg):
            data["premium_mode"] = "CHEQUE"
        elif re.search(r"(?i)\b(?:Online|UPI|NEFT|RTGS|IMPS|Card|PG|Gateway|Razorpay|PayU|BillDesk)\b", seg):
            data["premium_mode"] = "ONLINE"
        elif re.search(r"(?i)\bCash\b", seg):
            data["premium_mode"] = "CASH"

    dobs = []
    m_id = re.search(r"(?i)Customer\s+Identity\s+Card([\s\S]{0,1200})", pdf_text)
    if m_id:
        for m_d in re.finditer(r"(?i)(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-](?:19|20)\d{2})\s*[\r\n\s]+(?:Male|Female|Other)", m_id.group(1)):
            dt = parse_any_date(m_d.group(1))
            if dt:
                dobs.append(dt)
    if dobs:
        data["dob"] = fmt_date(min(dobs))

    return data
