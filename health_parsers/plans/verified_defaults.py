import re

# Plans verified during bugging where Premium Mode may genuinely be absent in the insurer PDF
# (Only applied if parser found blank — if ONLINE/CHEQUE/CASH is printed, that real value is kept!)
VERIFIED_FILL_MANUAL_PREMIUM_MODE = {
    ("NIVA BUPA", "REASSURE 2.0"),
    ("NIVA BUPA", "REASSURE 3.0"),
    ("NIVA BUPA", "HEALTH RECHARGE"),
    ("HDFC ERGO", "OPTIMA RESTORE"),
    ("HDFC ERGO", "OS"),
    ("HDFC ERGO", "PERSONAL ACCIDENT"),
    ("HDFC ERGO", "GROUP HEALTH ENDORSEMENT"),
    ("STAR HEALTH", "FAMILY ACCIDENT CARE"),
    ("STAR HEALTH", "STAR HEALTH ASSURE"),
    ("STAR HEALTH", "AROGYA SANJEEVANI"),
    ("STAR HEALTH", "SENIOR CITIZENS RED CARPET"),
    ("STAR HEALTH", "HOSPITAL CASH"),
    ("STAR HEALTH", "STAR SUPER SURPLUS"),
    ("STAR HEALTH", "FAMILY HEALTH OPTIMA"),
    ("IFFCO TOKIO", "FHP"),
    ("ADITYA BIRLA", "ACTIV HEALTH"),
    ("ADITYA BIRLA", "ACTIV YUVA"),
    ("ADITYA BIRLA", "ACTIV ONE"),
    ("NATIONAL", "PERSONAL ACCIDENT"),
    ("TATA AIG", "TRAVEL"),
    ("ICICI LOMBARD", "GROUP HEALTH"),
}

# Verified plans where renewal continues with the SAME policy number if no separate PYP is printed
VERIFIED_SAME_POLICY_ON_RENEWAL = {
    ("IFFCO TOKIO", "FHP"),
    ("MANIPAL CIGNA", "SUPER TOP UP PLUS"),
    ("MANIPAL CIGNA", "SUPER TOP UP SELECT"),
    ("MANIPAL CIGNA", "SARVAH PARAM"),
    ("MANIPAL CIGNA", "SARVAH UTTAM"),
}

# Known Indian health/general insurer aliases for comparing Previous Insurer vs Current Company
_INSURER_CANONICAL_PATTERNS = [
    ("STAR HEALTH", r"star\s+health"),
    ("HDFC ERGO", r"hdfc\s*ergo|apollo\s+munich"),
    ("NIVA BUPA", r"niva\s+bupa|max\s+bupa"),
    ("MANIPAL CIGNA", r"manipal\s*cigna|cigna\s*ttk"),
    ("ADITYA BIRLA", r"aditya\s+birla|abhi\b"),
    ("CARE HEALTH", r"care\s+health|religare\s+health"),
    ("ICICI LOMBARD", r"icici\s+lombard"),
    ("BAJAJ ALLIANZ", r"bajaj\s+allianz"),
    ("TATA AIG", r"tata\s+aig"),
    ("IFFCO TOKIO", r"iffco[\s\-]*tokio"),
    ("NEW INDIA", r"new\s+india\s+assurance"),
    ("NATIONAL", r"national\s+insurance"),
    ("ORIENTAL", r"oriental\s+insurance"),
    ("UNITED INDIA", r"united\s+india\s+insurance"),
    ("SBI GENERAL", r"sbi\s+general"),
    ("CHOLA MS", r"cholamandalam|chola\s*ms"),
    ("RELIANCE GENERAL", r"reliance\s+general"),
    ("FUTURE GENERALI", r"future\s+generali"),
    ("DIGIT", r"go\s*digit|digit\s+general"),
    ("ACKO", r"acko\s+general"),
    ("MAGMA", r"magma\s+hdi"),
    ("UNIVERSAL SOMPO", r"universal\s+sompo"),
    ("ROYAL SUNDARAM", r"royal\s+sundaram"),
    ("LIBERTY", r"liberty\s+general"),
    ("KOTAK", r"kotak\s+mahindra\s+general|zurich\s+kotak"),
]


def _canonical_insurer(text: str) -> str:
    low = str(text or "").lower()
    for canon, pat in _INSURER_CANONICAL_PATTERNS:
        if re.search(pat, low):
            return canon
    return ""


def _detect_previous_insurer_on_port(company: str, pdf_text: str) -> str:
    """
    Detects if the policy is a CURRENT-YEAR PORTABILITY case from a DIFFERENT previous insurer.
    Returns canonical previous insurer name if ported from a different company; else "".
    """
    comp = str(company or "").strip().upper()
    if not pdf_text or not comp:
        return ""

    # Guard: skip regular renewals / explicitly non-ported policies
    if re.search(r"(?i)(?:Ported\s*Policy|Portable\s*Case|Portability(?:/Migration)?)\s*[:\-]?\s*[\r\n\s]*No\b", pdf_text):
        return ""

    # Pattern 1: Niva Bupa portability letter
    m_nb = re.search(
        r"(?i)intimate\s+you\s+that\s+your\s+policy[\s\S]{0,60}?\bof\s+([A-Za-z][A-Za-z .&\-]{3,90}?)\s+and\s+Date\s+of\s+Initiation",
        pdf_text,
    )
    if m_nb:
        prev = _canonical_insurer(m_nb.group(1))
        if prev and prev != comp:
            return prev

    # Check if PDF explicitly flags current policy as Portability
    is_port_case = bool(
        re.search(r"(?i)Policy\s*Category\s*[:\-]?\s*[\r\n\s]*Portability\b", pdf_text)
        or re.search(r"(?i)(?:Ported\s*Policy|Portable\s*Case|Portability(?:/Migration)?)\s*[:\-]?\s*[\r\n\s]*Yes\b", pdf_text)
        or re.search(r"(?i)through\s+portability|has\s+been\s+ported\s+as\s+per\s+Portability", pdf_text)
    )
    if not is_port_case:
        return ""

    # Pattern 2: Previous Insurance / Portability section mentioning a different insurer
    for m_sec in re.finditer(
        r"(?i)(?:Previous\s+Insurance\s+Details|Previous\s+Insurer\s+Details|Previous\s+Insurer[\s\S]{0,80}?Previous\s+Policy|Portability\s+Continuity\s+Benefits)([\s\S]{0,2200})",
        pdf_text,
    ):
        sec_text = re.split(
            r"(?i)(?:BENEFITS\s+UNDER\s+THE\s+POLICY|Correspondence\s+Address|For\s+Claims|Nominee\s+Details|Premium\s+Details|Product\s+Name\s*:)",
            m_sec.group(1),
        )[0]
        for canon, pat in _INSURER_CANONICAL_PATTERNS:
            if canon != comp and re.search(pat, sec_text, re.I):
                return canon

    return ""


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
    if company == "ADITYA BIRLA":
        if re.search(r"(?i)Policy\s*Category\s*[\r\n\s]*[:\-]?\s*[\r\n\s]*\b(?:Fresh|New)\b", pdf_text):
            if not re.search(r"(?i)Portability(?:/Migration)?\s*[\r\n\s]*[:\-]?\s*Yes\b", pdf_text):
                return True
    if company == "TATA AIG":
        if re.search(r"(?i)Travel\s+Insurance", pdf_text):
            return True
    if re.search(r"(?i)\bRenewal\s*[:\-]\s*No\b", pdf_text) and not re.search(r"(?i)\bPortability\s*[:\-]\s*Yes\b", pdf_text):
        return True
    return False


def _is_explicit_renewal(pdf_text: str) -> bool:
    return bool(
        re.search(
            r"(?i)(?:Thank\s+you\s+for\s+renewing|Renewal\s+of\s+Your|Policy\s*Category\s*[:\-]?\s*[\r\n\s]*Renewal|ITGI[\r\n\s]+RENEWAL|\bRenewals\b)",
            pdf_text,
        )
    )


def apply_verified_defaults(company: str, data: dict, pdf_text: str) -> dict:
    """
    Applies post-extraction rules for verified plans in health_parsers/plans/:
    1. Auto-derives PYP Number for HDFC ERGO & Niva Bupa renewals (or 'FRESH' if renewal count == 00).
    2. Marks confirmed fresh/new policies as 'FRESH' in PYP Number.
    3. If a verified plan renews with the same policy number, copies Policy Number into PYP Number.
    4. Fills 'FILL MANUAL' ONLY for verified plan fields genuinely absent from the insurer PDF.
    5. Auto-fills Portability Company (= Current Company Name) & Portability Year (= Inception Year)
       whenever PDF shows policy was ported from a DIFFERENT previous insurer in the current term.
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

    # 3. Portability Company & Portability Year (when ported from a DIFFERENT previous company)
    if not str(data.get("portability_company") or "").strip():
        prev_ins = _detect_previous_insurer_on_port(comp, pdf_text)
        if prev_ins:
            data["portability_company"] = comp
            start_dt = data.get("start_dt")
            if start_dt and hasattr(start_dt, "year"):
                data["portability_year"] = str(start_dt.year)

    return data
