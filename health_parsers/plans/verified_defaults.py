import re

# Plans verified during bugging where Premium Mode may genuinely be absent in the insurer PDF
# (Only applied if parser found blank — if ONLINE/CHEQUE/CASH is printed, that real value is kept!)
VERIFIED_FILL_MANUAL_PREMIUM_MODE = {
    ("NIVA BUPA", "REASSURE 2.0"),
    ("NIVA BUPA", "REASSURE 3.0"),
    ("NIVA BUPA", "HEALTH RECHARGE"),
    ("HDFC ERGO", "OPTIMA RESTORE"),
    ("HDFC ERGO", "OS"),
    ("STAR HEALTH", "FAMILY ACCIDENT CARE"),
    ("STAR HEALTH", "STAR HEALTH ASSURE"),
    ("IFFCO TOKIO", "FHP"),
}

# Verified plans where renewal continues with the SAME policy number if no separate PYP is printed
VERIFIED_SAME_POLICY_ON_RENEWAL = {
    ("IFFCO TOKIO", "FHP"),
}


def _derive_hdfc_pyp(policy_number: str) -> str:
    """
    HDFC ERGO 19-digit policy format: [14-digit base][2-digit renewal count][000/001].
    - Renewal count > 00 -> decrement count by 1 (e.g. ...06000 -> ...05000).
    - Renewal count == 00 -> Fresh policy ("FRESH").
    """
    digits = re.sub(r"\s+", "", str(policy_number or ""))
    if re.fullmatch(r"\d{19}", digits) and digits[-3:].startswith("00"):
        base = digits[:14]
        ren_cnt = int(digits[14:16])
        if ren_cnt > 0:
            return f"{base}{ren_cnt - 1:02d}000"
        return "FRESH"
    return ""


def _derive_niva_bupa_pyp(policy_number: str) -> str:
    """
    Niva Bupa 14-digit policy format: [8-digit base][4-digit year][2-digit renewal count].
    - Renewal count > 00 -> year - 1 & count - 1 (e.g. 31690007202603 -> 31690007202502).
    - Renewal count == 00 -> Fresh policy ("FRESH").
    """
    digits = re.sub(r"\s+", "", str(policy_number or ""))
    if re.fullmatch(r"\d{14}", digits):
        base = digits[:8]
        yr = int(digits[8:12])
        ren_cnt = int(digits[12:14])
        if 2015 <= yr <= 2040:
            if ren_cnt > 0:
                return f"{base}{yr - 1}{ren_cnt - 1:02d}"
            return "FRESH"
    return ""


def _is_explicit_fresh_policy(company: str, pdf_text: str) -> bool:
    """Detects explicitly labeled Fresh / New policies so PYP Number is marked 'FRESH'."""
    if company == "STAR HEALTH":
        if re.search(r"(?i)Policy\s*Category\s*[\r\n\s]*:?\s*[\r\n\s]*\b(?:New|Fresh)\b", pdf_text):
            return True
    if company == "MANIPAL CIGNA":
        if re.search(r"(?i)Policy\s*Category\s*[:\-]?\s*[\r\n\s]*\b(?:Fresh|New)\b", pdf_text) or re.search(r"(?i)\bNew\s+Business\b", pdf_text):
            if not re.search(r"(?i)Ported\s*Policy\s*[:\-]?\s*[\r\n\s]*Yes\b", pdf_text) and not re.search(r"(?i)Portable\s*Case\s*[:\-]?\s*[\r\n\s]*Yes\b", pdf_text):
                return True
    if company == "TATA AIG":
        if re.search(r"(?i)Travel\s+Insurance", pdf_text):
            return True
    if re.search(r"(?i)\bRenewal\s*[:\-]\s*No\b", pdf_text) and not re.search(r"(?i)\bPortability\s*[:\-]\s*Yes\b", pdf_text):
        return True
    return False


def _is_explicit_renewal(pdf_text: str) -> bool:
    return bool(
        re.search(r"(?i)(?:Thank\s+you\s+for\s+renewing|Renewal\s+of\s+Your|Policy\s*Category\s*[:\-]?\s*[\r\n\s]*Renewal|ITGI[\r\n\s]+RENEWAL)", pdf_text)
    )


def apply_verified_defaults(company: str, data: dict, pdf_text: str) -> dict:
    """
    Applies post-extraction rules ONLY for verified plans in health_parsers/plans/:
    1. Auto-derives PYP Number for HDFC ERGO & Niva Bupa renewals (or 'FRESH' if renewal count == 00).
    2. Marks confirmed fresh/new policies as 'FRESH' in PYP Number.
    3. If a verified plan renews with the same policy number, copies Policy Number into PYP Number.
    4. Fills 'FILL MANUAL' ONLY for verified plan fields genuinely absent from the insurer PDF.
    """
    if not isinstance(data, dict):
        return data

    comp = str(company or "").strip().upper()
    plan = str(data.get("plan_name") or "").strip().upper()
    pol_no = str(data.get("policy_number") or "").strip()

    # 1. PYP Number rules
    if not str(data.get("pyp_number") or "").strip():
        derived = ""
        if comp == "HDFC ERGO":
            derived = _derive_hdfc_pyp(pol_no)
        elif comp == "NIVA BUPA":
            derived = _derive_niva_bupa_pyp(pol_no)

        if derived:
            data["pyp_number"] = derived
        elif _is_explicit_fresh_policy(comp, pdf_text):
            data["pyp_number"] = "FRESH"
        elif (comp, plan) in VERIFIED_SAME_POLICY_ON_RENEWAL and _is_explicit_renewal(pdf_text) and pol_no:
            data["pyp_number"] = pol_no

    # 2. Premium Mode: mark "FILL MANUAL" only for verified plans when absent in PDF
    if not str(data.get("premium_mode") or "").strip():
        if (comp, plan) in VERIFIED_FILL_MANUAL_PREMIUM_MODE:
            data["premium_mode"] = "FILL MANUAL"

    return data
