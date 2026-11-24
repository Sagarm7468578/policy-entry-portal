import io
import re
from datetime import timedelta
import pandas as pd
import pymupdf
from pypdf import PdfReader
from health_parsers.common import parse_any_date, clean_amount

_COMPANY_ALIASES = {
    "ICIC LOMBARD": "ICICI LOMBARD",
    "ICICI LOMBARD GENERAL INSURANCE": "ICICI LOMBARD",
    "MANIPAL SIGMA": "MANIPAL CIGNA",
    "MANIPALCIGNA": "MANIPAL CIGNA",
    "MAX BUPA": "NIVA BUPA",
    "RELIGARE HEALTH": "CARE HEALTH",
    "ORIENTAL INSURANCE": "ORIENTAL",
    "THE ORIENTAL": "ORIENTAL",
    "THE ORIENTAL INSURANCE": "ORIENTAL",
    "UNITED INDIA INSURANCE": "UNITED INDIA",
    "THE NEW INDIA ASSURANCE": "NEW INDIA",
    "NEW INDIA ASSURANCE": "NEW INDIA",
    "NATIONAL INSURANCE": "NATIONAL",
    "NATIONAL INSURANCE COMPANY": "NATIONAL",
    "STAR HEALTH AND ALLIED": "STAR HEALTH",
    "ADITYA BIRLA HEALTH": "ADITYA BIRLA",
    "IFFCO-TOKIO": "IFFCO TOKIO",
}

_AGENCY_SHORT_ALIASES = {
    "SURESH KUMAR CHINCHANI": "SKC",
    "SONAL LADDHA": "SL",
    "CHAYAN LADDHA": "CL",
    "SUMIT MAHESHWARI": "SM",
    "MOHIT MAHESHWARI": "MM",
}

_RN_COMPANY_PATTERNS = [
    ("HDFC ERGO", r"HDFC\s*ERGO"),
    ("STAR HEALTH", r"STAR\s*HEALTH"),
    ("CARE HEALTH", r"CARE\s*HEALTH|RELIGARE\s*HEALTH"),
    ("NIVA BUPA", r"NIVA\s*BUPA|MAX\s*BUPA"),
    ("MANIPAL CIGNA", r"MANIPAL\s*CIGNA|MANIPAL\s*SIGMA|MANIPALCIGNA"),
    ("TATA AIG", r"TATA\s*AIG"),
    ("TATA AIA", r"TATA\s*AIA"),
    ("ICICI LOMBARD", r"ICICI?\s*LOMBARD"),
    ("BAJAJ ALLIANZ", r"BAJAJ\s*ALLIANZ"),
    ("UNITED INDIA", r"UNITED\s*INDIA"),
    ("NEW INDIA", r"(?:THE\s+)?NEW\s*INDIA"),
    ("ORIENTAL", r"(?:THE\s+)?ORIENTAL(?:\s*INSURANCE)?"),
    ("NATIONAL", r"NATIONAL(?:\s*INSURANCE)?"),
    ("ADITYA BIRLA", r"ADITYA\s*BIRLA"),
    ("IFFCO TOKIO", r"IFFCO[\s\-]*TOKIO"),
    ("SBI GENERAL", r"SBI\s*GENERAL"),
    ("GO DIGIT", r"GO\s*DIGIT|DIGIT"),
    ("SHRIRAM", r"SHRIRAM"),
    ("ROYAL SUNDARAM", r"ROYAL\s*SUNDARAM"),
    ("CHOLA MS", r"CHOLA\s*MS|CHOLAMANDALAM"),
    ("FUTURE GENERALI", r"FUTURE\s*GENERALI"),
    ("RELIANCE", r"RELIANCE\s*GENERAL"),
    ("LIBERTY", r"LIBERTY"),
    ("MAGMA", r"MAGMA"),
    ("ZURICH KOTAK", r"ZURICH\s*KOTAK|KOTAK"),
]

_RN_SUBTYPE_PATTERNS = [
    ("PERSONAL ACCIDENT", r"PERSONAL\s*ACCIDENT"),
    ("TRAVEL INSURANCE", r"TRAVEL\s*INSURANCE"),
    ("SUPER TOP UP", r"SUPER\s*TOP[\s\-]*UP"),
    ("TOP UP", r"TOP[\s\-]*UP"),
    ("CRITICAL ILLNESS", r"CRITICAL\s*ILLNESS"),
    ("MEDICLAIM", r"MEDICLAIM"),
    ("WORKMEN COMPENSATION", r"WORKMEN\s*COMPENSATION|WC"),
    ("BURGLARY", r"BURGLARY"),
    ("MARINE", r"MARINE"),
    ("FIRE", r"FIRE"),
]

_RN_TAIL_RE = re.compile(
    r"(?<![\d.,])(?P<premium>\d{1,3}(?:[,.]\d{2,3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s+"
    r"(?P<si>\d{1,3}(?:[,.]\d{2,3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s+"
    r"(?P<inc>\d{2}[-/]\d{2}[-/]\d{2,4})\s+"
    r"(?P<exp>\d{2}[-/]\d{2}[-/]\d{2,4})\s*$"
)


def _norm_upper(val: str) -> str:
    return re.sub(r"\s+", " ", str(val or "").strip().upper()).strip(" .:-_")


def _norm_company(val: str) -> str:
    u = _norm_upper(val)
    return _COMPANY_ALIASES.get(u, u)


def _norm_agency_alias(val: str) -> str:
    u = _norm_upper(val)
    return _AGENCY_SHORT_ALIASES.get(u, u)


def _norm_policy_id(p: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(p or "").upper())


def _norm_name_compact(name: str) -> str:
    s = re.sub(r"(?i)^\s*((?:MRS|MISS|MR|MS|DR|SMT|SHRI|MASTER|MAST|M/S)(?:\.|\b)\s*)+", "", str(name or ""))
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def _clean_rn_amount(val: str) -> str:
    """Cleans renewal list amounts including OCR dot-thousands like 16.191.0 or 33.064.0."""
    if not val:
        return ""
    s = re.sub(r"\.\d+$", "", str(val).strip())
    return re.sub(r"[,\.\s]", "", s)


def lookup_client_master(client_name: str, master_df: pd.DataFrame) -> dict:
    empty = {
        "client_code": "",
        "occupation": "",
        "mobile": "",
        "mail_id": "",
        "sub_agent": "",
        "family_code": "",
    }
    if master_df is None or master_df.empty or not client_name:
        return empty

    cols = {str(c).strip().lower(): c for c in master_df.columns}
    name_col = cols.get("client name") or cols.get("name")
    if not name_col:
        return empty

    target = client_name.strip().upper()
    series = master_df[name_col].astype(str).str.strip().str.upper()

    matched = master_df[series == target]
    if matched.empty:
        matched = master_df[series.str.contains(re.escape(target), na=False)]
    if matched.empty:
        return empty

    row = matched.iloc[0]

    def get_val(keys):
        for k in keys:
            if k in cols:
                v = row[cols[k]]
                if pd.notna(v):
                    s = str(v).strip()
                    if s.lower() == "nan":
                        return ""
                    if re.fullmatch(r"\d+\.0+", s):
                        s = s.split(".")[0]
                    return s
        return ""

    return {
        "client_code": get_val(["client code"]),
        "occupation": get_val(["occupation", "profession"]),
        "mobile": get_val(["mobile", "mobile no", "phone"]),
        "mail_id": get_val(["mail id", "mail", "email", "email id"]),
        "sub_agent": get_val(["sub agent", "subagent"]),
        "family_code": get_val(["family code"]),
    }


def lookup_accounts_master(company_name: str, agency_name: str, accounts_df: pd.DataFrame) -> str:
    if accounts_df is None or accounts_df.empty or not company_name or not agency_name:
        return ""

    cols = {str(c).strip().lower(): c for c in accounts_df.columns}
    comp_col = cols.get("company name") or cols.get("company") or cols.get("insurer") or cols.get("insurance company")
    ag_col = cols.get("agency") or cols.get("agency name") or cols.get("intermediary") or cols.get("agent") or cols.get("broker")
    acc_col = cols.get("accounts") or cols.get("account") or cols.get("account name")

    if not comp_col or not ag_col or not acc_col:
        return ""

    target_comp_raw = _norm_upper(company_name)
    target_comp_norm = _norm_company(company_name)
    target_ag_raw = _norm_upper(agency_name)
    target_ag_alias = _norm_agency_alias(agency_name)

    exact_map, comp_norm_map, full_norm_map = {}, {}, {}

    for _, row in accounts_df.iterrows():
        c_val, a_val, acc_val = row[comp_col], row[ag_col], row[acc_col]
        if pd.isna(c_val) or pd.isna(a_val) or pd.isna(acc_val):
            continue
        acc_str = str(acc_val).strip()
        if not acc_str or acc_str.lower() == "nan":
            continue

        c_raw, c_norm = _norm_upper(c_val), _norm_company(c_val)
        a_raw, a_alias = _norm_upper(a_val), _norm_agency_alias(a_val)
        if not c_raw or not a_raw:
            continue

        exact_map.setdefault((c_raw, a_raw), acc_str)
        comp_norm_map.setdefault((c_norm, a_raw), acc_str)
        full_norm_map.setdefault((c_norm, a_alias), acc_str)

    if (target_comp_raw, target_ag_raw) in exact_map:
        return exact_map[(target_comp_raw, target_ag_raw)]
    if (target_comp_norm, target_ag_raw) in comp_norm_map:
        return comp_norm_map[(target_comp_norm, target_ag_raw)]
    if (target_comp_norm, target_ag_alias) in full_norm_map:
        return full_norm_map[(target_comp_norm, target_ag_alias)]
    return ""


def parse_renewal_list_pdf(pdf_bytes: bytes) -> list:
    """Extracts structured rows from Renewal List PDFs (Health / Motor / SME)."""
    text = ""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = "\n".join(p.extract_text() or "" for p in reader.pages)
    except Exception:
        text = ""

    if len(text.strip()) < 30:
        try:
            doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
            text = "\n".join(page.get_text("text") or "" for page in doc)
            doc.close()
        except Exception:
            pass

    records = []
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        low = line.lower()
        if "client name" in low and "expiry date" in low:
            continue

        m_tail = _RN_TAIL_RE.search(line)
        if not m_tail:
            continue

        premium = _clean_rn_amount(m_tail.group("premium"))
        sum_insured = _clean_rn_amount(m_tail.group("si"))
        exp_str = m_tail.group("exp")
        left = line[:m_tail.start()].strip()

        comp_name, comp_pos = "", len(left)
        for cname, cpat in _RN_COMPANY_PATTERNS:
            mc = re.search(rf"(?i)\b(?:{cpat})\b", left)
            if mc and mc.start() < comp_pos:
                comp_pos = mc.start()
                comp_name = cname

        sub_type, sub_pos = "", len(left)
        for sname, spat in _RN_SUBTYPE_PATTERNS:
            ms = re.search(rf"(?i)\b(?:{spat})\b", left)
            if ms and ms.start() < sub_pos:
                sub_pos = ms.start()
                sub_type = sname

        head = left[:min(comp_pos, sub_pos)].strip()
        head_spaced = re.sub(r"([A-Za-z])([6-9]\d{9}\b)", r"\1 \2", head)
        head_spaced = re.sub(r"(\d{10}),(\S)", r"\1 ,\2", head_spaced)

        name_tokens, id_tokens, in_ids = [], [], False
        for tok in head_spaced.split():
            if not in_ids and (re.search(r"\d", tok) or tok.startswith(",")):
                in_ids = True
            (id_tokens if in_ids else name_tokens).append(tok)

        client_name = " ".join(name_tokens).strip(" .,:-_").upper()
        id_str = " ".join(id_tokens).strip()

        policy_no = ""
        if "," in id_str:
            policy_no = _norm_policy_id(id_str.split(",", 1)[1].strip())
        else:
            m_mob_55 = re.match(r"^[6-9]\d{4}\s+\d{5}\s+(.+)$", id_str)
            m_mob_10 = re.match(r"^[6-9]\d{9}\s+(.+)$", id_str)
            if m_mob_55 and re.search(r"\d", m_mob_55.group(1)):
                policy_no = _norm_policy_id(m_mob_55.group(1))
            elif m_mob_10 and re.search(r"\d", m_mob_10.group(1)):
                policy_no = _norm_policy_id(m_mob_10.group(1))
            elif m_mob_10 and not re.search(r"\d", m_mob_10.group(1)):
                policy_no = ""
            elif re.search(r"\d", id_str):
                policy_no = _norm_policy_id(id_str)

        records.append({
            "client_name": client_name,
            "client_compact": _norm_name_compact(client_name),
            "policy_no_norm": policy_no,
            "sub_type": sub_type,
            "company": comp_name,
            "premium": premium,
            "sum_insured": sum_insured,
            "exp_dt": parse_any_date(exp_str),
        })

    return records


def get_renewal_lookup_months(row_dict: dict) -> list:
    inc_dt = parse_any_date(row_dict.get("Inception Date", ""))
    exp_dt = parse_any_date(row_dict.get("Expiry Date", ""))
    targets = []

    if inc_dt:
        targets.append((inc_dt.year, inc_dt.month))
        if inc_dt.day <= 5:
            prev_dt = inc_dt - timedelta(days=inc_dt.day)
            targets.append((prev_dt.year, prev_dt.month))
        elif inc_dt.day >= 26:
            nxt_dt = inc_dt + timedelta(days=7)
            targets.append((nxt_dt.year, nxt_dt.month))
    elif exp_dt:
        targets.append((exp_dt.year - 1, exp_dt.month))

    seen, ordered = set(), []
    for ym in targets:
        if ym not in seen:
            seen.add(ym)
            ordered.append(ym)
    return ordered


def match_renewal_record(row_dict: dict, records: list):
    if not records:
        return None

    pyp_norm = _norm_policy_id(row_dict.get("PYP Number", ""))
    pno_norm = _norm_policy_id(row_dict.get("Policy Number", ""))
    cname_compact = _norm_name_compact(row_dict.get("Client Name", ""))
    comp_norm = _norm_company(row_dict.get("Company Name", ""))
    sub_norm = _norm_upper(row_dict.get("Sub Type", ""))
    inc_dt = parse_any_date(row_dict.get("Inception Date", ""))

    # Priority 1: PYP Number match
    if len(pyp_norm) >= 6:
        for r in records:
            rp = r["policy_no_norm"]
            if rp and (rp == pyp_norm or (len(rp) >= 8 and (rp in pyp_norm or pyp_norm in rp))):
                return r

    # Priority 2: Same Policy Number or same base policy prefix
    if len(pno_norm) >= 6:
        for r in records:
            rp = r["policy_no_norm"]
            if rp and rp == pno_norm:
                return r
        for r in records:
            rp = r["policy_no_norm"]
            if rp and len(rp) >= 12 and len(pno_norm) >= 12:
                if rp[:14] == pno_norm[:14]:
                    return r
                if rp[:8] == pno_norm[:8] and cname_compact and r["client_compact"] == cname_compact:
                    return r

    # Priority 3: Client Name + Company + Sub Type + Date proximity
    if cname_compact:
        name_matches = []
        for r in records:
            rc = r["client_compact"]
            if not rc:
                continue
            if rc == cname_compact or (len(rc) >= 8 and len(cname_compact) >= 8 and (rc in cname_compact or cname_compact in rc)):
                score = 0
                if comp_norm and _norm_company(r["company"]) == comp_norm:
                    score += 10
                if sub_norm and _norm_upper(r["sub_type"]) == sub_norm:
                    score += 5
                if inc_dt and r["exp_dt"]:
                    diff_days = abs((inc_dt - r["exp_dt"]).days)
                    if diff_days <= 15:
                        score += 8
                    elif diff_days <= 45:
                        score += 3
                name_matches.append((score, r))
        if name_matches:
            name_matches.sort(key=lambda x: x[0], reverse=True)
            best_score, best_rec = name_matches[0]
            if best_score >= 5 or len(name_matches) == 1:
                return best_rec

    return None
