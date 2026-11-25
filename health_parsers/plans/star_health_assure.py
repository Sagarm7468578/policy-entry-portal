import re
from health_parsers.common import (
    default_extracted_data,
    parse_any_date,
    fmt_date,
    clean_amount,
    clean_person_name,
)


def is_star_health_assure(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)Star\s+Health\s+Assure\s+Insurance\s+Policy", pdf_text)
        or re.search(r"(?i)SHAHLIP23131V", pdf_text)
        or re.search(r"(?i)Assure\s+Insurance[\-\s]*20\d{2}", pdf_text)
    )


def _extract_star_assure_agency(pdf_text: str) -> str:
    # Restrict search to Schedule Intermediary block (avoids Page 1 letter "as indicated by you")
    m_block = re.search(
        r"(?i)Intermediary[\r\n\s]*Code([\s\S]{0,1400}?)(?:Total\s*Premium|PERIOD\s*OF\s*INSURANCE)",
        pdf_text,
    )
    block = m_block.group(1) if m_block else ""

    if block:
        # Priority 1: Salutation-prefixed name on a single line (e.g. Mr.CHAYAN LADDHA, Mrs. SONAL LADDHA)
        m_sal = re.search(
            r"(?im)^[ \t]*(?:MRS|MISS|MR|MS|DR|SMT|SHRI|M/S)(?:\.[ \t]*|[ \t]+)([A-Za-z][A-Za-z .&/\-]{2,60})[ \t]*$",
            block,
        )
        if m_sal:
            val = clean_person_name(m_sal.group(1))
            if val:
                return val

        # Priority 2: Direct "Intermediary Name : ..." or "Agent Name : ..."
        m_direct = re.search(
            r"(?i)(?:Intermediary\s*Name|Agent\s*Name)[ \t]*[:\-][ \t]*([^\r\n]{3,65})",
            block,
        )
        if m_direct:
            cand = clean_person_name(m_direct.group(1))
            if cand and not re.search(r"(?i)indicated\s+by\s+you", cand):
                return cand

        # Priority 3: Clean alphabetic name line inside block (without salutation)
        skip_words = {
            "intermediary", "code", "renewal", "year", "collection", "date", "inception",
            "first", "policy", "name", "optional", "cover", "loading", "discount",
            "premium", "phone", "no", "cgst", "sgst", "igst", "stamp", "duty", "total", "rs",
            "e-mail", "email", "mail", "id", "tenth", "ninth", "eighth", "seventh", "sixth",
            "fifth", "fourth", "third", "second", "fresh", "new",
        }
        for line in block.splitlines():
            s = re.sub(r"[ \t]+", " ", line).strip(" :.-_")
            if len(s) < 3 or re.search(r"[\d@/]", s):
                continue
            low_words = [w.lower() for w in re.findall(r"[A-Za-z]+", s)]
            if not low_words or any(w in skip_words for w in low_words):
                continue
            if re.fullmatch(r"[A-Za-z .&\-]{3,60}", s):
                return clean_person_name(s)

    return ""


def _extract_star_assure_payment_mode(pdf_text: str) -> str:
    # Star Health Section 80D certificate: "Payment received by Cheque / Online / Cash ..."
    m_rec = re.search(r"(?i)Payment\s+received\s+by\s+([^\r\n]{2,60})", pdf_text)
    if m_rec:
        seg = m_rec.group(1)
        if re.search(r"(?i)\b(?:Cheque|Chq\.?|DD|Demand\s*Draft)\b", seg):
            return "CHEQUE"
        if re.search(
            r"(?i)\b(?:Online|UPI|NEFT|RTGS|IMPS|Net\s*Banking|Credit\s*Card|Debit\s*Card|Card|PG|IPG|EPG|Digital|E-?Pay|Gateway|Razorpay|PayU|BillDesk)\b",
            seg,
        ):
            return "ONLINE"
        if re.search(r"(?i)\b(?:ECS|NACH|Auto\s*Debit)\b", seg):
            return "AUTO DEBIT"
        if re.search(r"(?i)\bCash\b", seg):
            return "CASH"
    return ""


def _extract_star_assure_dob(pdf_text: str) -> str:
    # Prefer DOBs directly from Insured Persons / Customer Identity Card section
    dobs = []
    for m_sec in re.finditer(
        r"(?i)(?:Details\s+of\s+Insured\s+Persons|Customer\s+Identity\s+Card)([\s\S]{0,1600})",
        pdf_text,
    ):
        sec = m_sec.group(1)
        for m_d in re.finditer(
            r"(?i)(?:Male|Female|Other)\s*[\r\n\s]+(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-](?:19|20)\d{2})"
            r"|(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-](?:19|20)\d{2})\s*[\r\n\s]+(?:Male|Female|Other)",
            sec,
        ):
            d_str = m_d.group(1) or m_d.group(2)
            dt = parse_any_date(d_str)
            if dt:
                dobs.append(dt)
    if dobs:
        return fmt_date(min(dobs))
    return ""


def parse_star_health_assure(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "STAR HEALTH ASSURE"
    data["sub_type"] = "MEDICLAIM"

    # 1. Policy Number
    for pat in [
        r"(?i)Renewal\s*Endorsement\s*No\.?\s*[:\-]?\s*([A-Z0-9/\-]{8,30})",
        r"(?i)Attached\s+to\s+and\s+forming\s+part\s+of\s+Policy\s*No\.?\s*[:\-]?\s*([A-Z0-9/\-]{8,30})",
        r"(?i)Policy\s*No\.?\s*[:\-]\s*([A-Z0-9/\-]{8,30})",
        r"(?i)Health\s+Insurance\s+Policy\s*[\-:]\s*([A-Z0-9/\-]{8,30})",
    ]:
        m = re.search(pat, pdf_text)
        if m:
            data["policy_number"] = m.group(1).strip()
            break

    # 2. Client Name (strictly single-line; never picks "Cust CKYC No" from next line)
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

    # 3. PYP Number (Previous Policy Number in renewal clause)
    m_pyp = re.search(
        r"(?i)towards\s+renewal\s+premium\s+of\s+policy\s*number\s*[:\-]?\s*[\r\n\s]*([A-Z0-9/\-]{8,30})",
        pdf_text,
    )
    if m_pyp:
        data["pyp_number"] = m_pyp.group(1).strip().rstrip(",.")

    # 4. Agency / Intermediary Name
    data["agency"] = _extract_star_assure_agency(pdf_text)

    # 5. Inception Date & Expiry Date
    date_tok = r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})"
    m_period = re.search(
        rf"(?i)PERIOD\s*OF\s*INSURANCE[\s\S]{{0,120}}?From\s*[:\-]?\s*{date_tok}[\s\S]{{0,80}}?To[\s\S]{{0,40}}?(?:Midnight\s*Of\s*)?{date_tok}",
        pdf_text,
    )
    if m_period:
        data["start_dt"] = parse_any_date(m_period.group(1))
        data["end_dt"] = parse_any_date(m_period.group(2))

    if not data["start_dt"] or not data["end_dt"]:
        m_cert_p = re.search(rf"(?i)for\s+the\s+Period\s+{date_tok}\s+To\s+{date_tok}", pdf_text)
        if m_cert_p:
            data["start_dt"] = data["start_dt"] or parse_any_date(m_cert_p.group(1))
            data["end_dt"] = data["end_dt"] or parse_any_date(m_cert_p.group(2))

    if not data["start_dt"]:
        m_vf = re.search(rf"(?i)Valid\s*From\s*[:\-]\s*{date_tok}", pdf_text)
        if m_vf:
            data["start_dt"] = parse_any_date(m_vf.group(1))

    if not data["end_dt"]:
        m_vt = re.search(rf"(?i)Valid\s*Till\s*[:\-]\s*{date_tok}", pdf_text)
        if m_vt:
            data["end_dt"] = parse_any_date(m_vt.group(1))

    # 6. Sum Insured
    m_si = re.search(
        r"(?i)Basic(?:\s+Floater)?\s+Sum\s*Insured\s*[:\-]?\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        pdf_text,
    )
    if not m_si:
        m_si = re.search(
            r"(?i)Sum\s*Insured\s*[:\-]\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
            pdf_text,
        )
    if m_si:
        data["sum_insured"] = clean_amount(m_si.group(1))

    # 7. Total Premium
    for pat in [
        r"(?i)Total\s*Premium\s*[\r\n\s]*[:\-]?\s*[\r\n\s]*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)Total\s*Invoice\s*Value\s*\(in\s*Figures\)\s*[\r\n\s]*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
        r"(?i)has\s+paid\s+(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)",
    ]:
        m_p = re.search(pat, pdf_text)
        if m_p:
            data["premium"] = clean_amount(m_p.group(1))
            break

    # 8. Premium Mode
    data["premium_mode"] = _extract_star_assure_payment_mode(pdf_text)

    # 9. DOB (Oldest Insured Person)
    data["dob"] = _extract_star_assure_dob(pdf_text)

    return data
