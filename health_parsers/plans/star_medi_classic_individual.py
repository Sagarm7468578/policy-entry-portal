import re
from health_parsers.common import (
    default_extracted_data,
    parse_any_date,
    fmt_date,
    clean_amount,
    clean_person_name,
)


def is_star_medi_classic_individual(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)Medi\s+Classic\s+Insurance\s+Policy\s*\(\s*Individual\s*\)", pdf_text)
        or re.search(r"(?i)SHAHLIP25038V", pdf_text)
        or re.search(r"(?i)Medi\s+Classic\s+Insurance\s+Policy", pdf_text)
    )


def _extract_medi_classic_agency(pdf_text: str) -> str:
    # Restrict search to Schedule Intermediary block (avoids Page 1 letter "as indicated by you")
    m_block = re.search(
        r"(?i)Intermediary[\r\n\s]*Code([\s\S]{0,1400}?)(?:Total\s*Premium|Period\s*of\s*Insurance)",
        pdf_text,
    )
    block = m_block.group(1) if m_block else ""
    if not block:
        return ""

    stop_labels = {
        "intermediary", "code", "renewal", "year", "collection", "date", "inception",
        "first", "policy", "name", "optional", "cover", "loading", "discount",
        "premium", "phone", "no", "cgst", "sgst", "igst", "stamp", "duty", "total", "rs",
        "e-mail", "email", "mail", "id", "tenth", "ninth", "eighth", "seventh", "sixth",
        "fifth", "fourth", "third", "second", "fresh", "new",
    }

    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in block.splitlines()]

    # Priority 1: Salutation-prefixed name (handles leading ":" and multi-line wrap like ": MS.RAJNI\nMAHESHWARI")
    for idx, ln in enumerate(lines):
        m_sal = re.match(
            r"(?i)^:?\s*(?:MRS|MISS|MR|MS|DR|SMT|SHRI|M/S)(?:\.\s*|\s+)([A-Za-z][A-Za-z .&/\-]{1,60})$",
            ln,
        )
        if m_sal:
            parts = [m_sal.group(1).strip()]
            if idx + 1 < len(lines):
                nxt = lines[idx + 1].strip(" :.-_")
                nxt_words = [w.lower() for w in re.findall(r"[A-Za-z]+", nxt)]
                if (
                    nxt
                    and not re.search(r"[\d@/]", nxt)
                    and re.fullmatch(r"[A-Za-z .&\-]{2,40}", nxt)
                    and nxt_words
                    and not any(w in stop_labels for w in nxt_words)
                ):
                    parts.append(nxt)
            return clean_person_name(" ".join(parts))

    # Priority 2: Direct "Intermediary Name : ..." or "Agent Name : ..."
    m_direct = re.search(
        r"(?i)(?:Intermediary\s*Name|Agent\s*Name)[ \t]*[:\-][ \t]*([^\r\n]{3,65})",
        block,
    )
    if m_direct:
        cand = clean_person_name(m_direct.group(1))
        if cand and not re.search(r"(?i)indicated\s+by\s+you", cand):
            return cand

    # Priority 3: Clean alphabetic name line(s) inside block (without salutation)
    for idx, ln in enumerate(lines):
        s = ln.strip(" :.-_")
        if len(s) < 3 or re.search(r"[\d@/]", s):
            continue
        low_words = [w.lower() for w in re.findall(r"[A-Za-z]+", s)]
        if not low_words or any(w in stop_labels for w in low_words):
            continue
        if re.fullmatch(r"[A-Za-z .&\-]{3,60}", s):
            parts = [s]
            if idx + 1 < len(lines):
                nxt = lines[idx + 1].strip(" :.-_")
                nxt_words = [w.lower() for w in re.findall(r"[A-Za-z]+", nxt)]
                if (
                    nxt
                    and not re.search(r"[\d@/]", nxt)
                    and re.fullmatch(r"[A-Za-z .&\-]{2,40}", nxt)
                    and nxt_words
                    and not any(w in stop_labels for w in nxt_words)
                ):
                    parts.append(nxt)
            return clean_person_name(" ".join(parts))

    return ""


def _extract_medi_classic_sum_insured(pdf_text: str) -> str:
    # Priority 1: Explicit labeled Sum Insured line (if present)
    m_lbl = re.search(
        r"(?i)(?:Basic\s+)?Sum\s*Insured[ \t]*[:\-][ \t]*(?:Rs\.?|INR|₹)?[ \t]*([\d,]{5,15}(?:\.\d+)?)",
        pdf_text,
    )
    if m_lbl:
        return clean_amount(m_lbl.group(1))

    # Priority 2: Insured Persons table block (Medi Classic puts Sum Insured & Cumu. Bonus inside this table)
    m_sec = re.search(
        r"(?i)Details\s+of\s+Insured\s+Persons([\s\S]{0,1800}?)(?:Nominee\s+Details|Pre\s+Existing\s+Disease|IMPORTANT|$)",
        pdf_text,
    )
    sec = m_sec.group(1) if m_sec else ""
    if sec:
        # In Star Medi Classic table extraction, Sum Insured sits right before Inception Date
        m_before_dt = re.search(
            r"(?<!\d)(\d{1,2}(?:,\d{2})*,\d{3})\s*[\r\n]+\s*\d{2}[/\-][A-Za-z]{3}[/\-](?:19|20)\d{2}",
            sec,
        )
        if m_before_dt:
            val = clean_amount(m_before_dt.group(1))
            if val.isdigit() and int(val) >= 50000:
                return val

        # Fallback: highest comma-formatted amount >= 50,000 in Insured Persons block (SI >= Cumulative Bonus)
        amts = []
        for m_a in re.finditer(r"(?<!\d)(\d{1,2}(?:,\d{2})*,\d{3})(?!\d)", sec):
            v = clean_amount(m_a.group(1))
            if v.isdigit() and int(v) >= 50000:
                amts.append(int(v))
        if amts:
            return str(max(amts))

    return ""


def _extract_medi_classic_payment_mode(pdf_text: str) -> str:
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


def _extract_medi_classic_dob(pdf_text: str) -> str:
    dobs = []
    # Priority 1: Customer Identity Card (cleanest layout: Name -> DOB -> Gender)
    m_id = re.search(r"(?i)Customer\s+Identity\s+Card([\s\S]{0,1200})", pdf_text)
    if m_id:
        for m_d in re.finditer(
            r"(?i)(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-](?:19|20)\d{2})\s*[\r\n\s]+(?:Male|Female|Other)"
            r"|(?:Male|Female|Other)\s*[\r\n\s]+(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-](?:19|20)\d{2})",
            m_id.group(1),
        ):
            dt = parse_any_date(m_d.group(1) or m_d.group(2))
            if dt:
                dobs.append(dt)
    if dobs:
        return fmt_date(min(dobs))

    # Priority 2: Details of Insured Persons fallback
    m_ins = re.search(
        r"(?i)Details\s+of\s+Insured\s+Persons([\s\S]{0,1500}?)(?:Nominee\s+Details|Pre\s+Existing\s+Disease|$)",
        pdf_text,
    )
    if m_ins:
        for d_str in re.findall(r"\b\d{2}[/\-][A-Za-z]{3}[/\-](?:19|20)\d{2}\b", m_ins.group(1)):
            dt = parse_any_date(d_str)
            if dt and dt.year <= 2010:
                dobs.append(dt)
    return fmt_date(min(dobs)) if dobs else ""


def parse_star_medi_classic_individual(pdf_text: str) -> dict:
    data = default_extracted_data()
    data["plan_name"] = "MEDI CLASSIC (INDIVIDUAL)"
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

    # 2. Client Name (strictly single-line; never picks "Cust CKYC No")
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

    # 3. PYP Number
    m_pyp = re.search(
        r"(?i)towards\s+renewal\s+premium\s+of\s+policy\s*number\s*[:\-]?\s*[\r\n\s]*([A-Z0-9/\-]{8,30})",
        pdf_text,
    )
    if m_pyp:
        data["pyp_number"] = m_pyp.group(1).strip().rstrip(",.")

    # 4. Agency / Intermediary Name
    data["agency"] = _extract_medi_classic_agency(pdf_text)

    # 5. Inception Date & Expiry Date
    date_tok = r"(\d{2}[/\-][A-Za-z0-9]{2,3}[/\-]\d{2,4})"
    m_period = re.search(
        rf"(?i)Period\s*of\s*Insurance[\s\S]{{0,120}}?From\s*[:\-]?\s*{date_tok}[\s\S]{{0,80}}?To[\s\S]{{0,40}}?(?:Midnight\s*of\s*)?{date_tok}",
        pdf_text,
    )
    if m_period:
        data["start_dt"] = parse_any_date(m_period.group(1))
        data["end_dt"] = parse_any_date(m_period.group(2))

    if not data["start_dt"] or not data["end_dt"]:
        m_cert = re.search(rf"(?i)for\s+the\s+Period\s+{date_tok}\s+To\s+{date_tok}", pdf_text)
        if m_cert:
            data["start_dt"] = data["start_dt"] or parse_any_date(m_cert.group(1))
            data["end_dt"] = data["end_dt"] or parse_any_date(m_cert.group(2))

    if not data["start_dt"]:
        m_vf = re.search(rf"(?i)Valid\s*From\s*[:\-]\s*{date_tok}", pdf_text)
        if m_vf:
            data["start_dt"] = parse_any_date(m_vf.group(1))

    if not data["end_dt"]:
        m_vt = re.search(rf"(?i)Valid\s*Till\s*[:\-]\s*{date_tok}", pdf_text)
        if m_vt:
            data["end_dt"] = parse_any_date(m_vt.group(1))

    # 6. Sum Insured
    data["sum_insured"] = _extract_medi_classic_sum_insured(pdf_text)

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
    data["premium_mode"] = _extract_medi_classic_payment_mode(pdf_text)

    # 9. DOB
    data["dob"] = _extract_medi_classic_dob(pdf_text)

    return data
