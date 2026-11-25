from datetime import datetime, timedelta
from health_parsers import COMPANY_PARSERS
from health_parsers.plans import dispatch_plan_parser
from health_parsers.common import (
    IST,
    OUTPUT_COLUMNS,
    ALL_SYSTEM_FIELDS,
    MONTH_NAMES_BY_NUM,
    extract_pdf_text,
    get_company_scores,
    fmt_date,
    extract_generic_agency,
    extract_premium_mode,
    extract_oldest_dob,
)
from health_parsers.masters_renewal import (
    lookup_client_master,
    lookup_accounts_master,
    parse_renewal_list_pdf,
    get_renewal_lookup_months,
    match_renewal_record,
)
from health_parsers.schema_excel import (
    parse_custom_columns,
    normalize_custom_columns_spec,
    spec_to_multiline,
    get_custom_schema_info,
    project_rows_to_schema,
    build_excel_bytes,
    build_sample_master_bytes,
    build_sample_accounts_master_bytes,
    read_excel_headers_from_bytes,
    append_rows_to_excel_bytes,
    append_rows_to_local_excel,
)


def process_health_pdf(file_name: str, pdf_bytes: bytes, master_df=None, accounts_df=None):
    """Returns (row_dict, is_success, error_reason, debug_info)"""
    today_ist = datetime.now(IST).replace(tzinfo=None)
    entry_date = fmt_date(today_ist)

    base_row = {col: "" for col in ALL_SYSTEM_FIELDS}
    base_row["Insurance Type"] = "HEALTH INSURANCE"
    base_row["Date of Entry"] = entry_date

    debug_info = {
        "file_name": file_name,
        "client_name": "",
        "detected_company": "",
        "company_scores": {},
        "raw_text": "",
        "error_reason": "",
    }

    try:
        pdf_text = extract_pdf_text(pdf_bytes)
        debug_info["raw_text"] = pdf_text

        if len(pdf_text.strip()) < 80:
            base_row["Client Name"] = file_name
            debug_info["client_name"] = file_name
            debug_info["error_reason"] = "Scanned / Image PDF (text readable nahi hai)"
            return base_row, False, debug_info["error_reason"], debug_info

        scores = get_company_scores(pdf_text)
        company = next(iter(scores.keys()), "")
        debug_info["company_scores"] = scores
        debug_info["detected_company"] = company

        extracted = dispatch_plan_parser(company, pdf_text) if company else None
        if extracted is None:
            parser_fn = COMPANY_PARSERS.get(company)
            if not company or not parser_fn:
                base_row["Client Name"] = file_name
                base_row["Company Name"] = company or "UNKNOWN"
                debug_info["client_name"] = file_name
                debug_info["error_reason"] = f"Company parser abhi add nahi hua: {company or 'Unknown'}"
                return base_row, False, debug_info["error_reason"], debug_info
            extracted = parser_fn(pdf_text)

        if not extracted.get("client_name") and not extracted.get("policy_number"):
            base_row["Client Name"] = file_name
            base_row["Company Name"] = company
            debug_info["client_name"] = file_name
            debug_info["error_reason"] = "Client Name aur Policy Number extract nahi ho paya"
            return base_row, False, debug_info["error_reason"], debug_info

        debug_info["client_name"] = extracted["client_name"] or file_name
        master_info = lookup_client_master(extracted["client_name"], master_df)

        end_dt = extracted.get("end_dt")
        reminder_date = fmt_date(end_dt - timedelta(days=15)) if end_dt else ""
        policy_status = ""
        if end_dt:
            policy_status = "INACTIVE" if end_dt.date() < today_ist.date() else "ACTIVE"

        agency = extracted.get("agency") or extract_generic_agency(pdf_text)
        premium_mode = extracted.get("premium_mode") or extract_premium_mode(pdf_text)
        if extracted.get("skip_dob_fallback"):
            dob = extracted.get("dob", "")
        else:
            dob = extracted.get("dob") or extract_oldest_dob(pdf_text, extracted.get("start_dt"))
        accounts_val = lookup_accounts_master(company, agency, accounts_df)

        base_row.update({
            "Client Name": extracted["client_name"],
            "Client Code": master_info["client_code"],
            "Occupation": master_info["occupation"],
            "Mobile": master_info["mobile"],
            "Mail Id": master_info["mail_id"],
            "Policy Number": str(extracted["policy_number"]),
            "Insurance Type": "HEALTH INSURANCE",
            "Sub Type": extracted["sub_type"],
            "Company Name": company,
            "Agency": agency,
            "Sub agent": master_info["sub_agent"],
            "Accounts": accounts_val,
            "Plan Name": extracted["plan_name"],
            "Premium": extracted["premium"],
            "Sum Insured": extracted["sum_insured"],
            "Inception Date": fmt_date(extracted.get("start_dt")),
            "Expiry Date": fmt_date(end_dt),
            "Reminder Date": reminder_date,
            "Premium Mode": premium_mode,
            "Policy Status": policy_status,
            "Remark": "",
            "PYP Number": str(extracted["pyp_number"]),
            "PYP premium": "",
            "Share": "",
            "Share %": "",
            "Family code": master_info["family_code"],
            "Date of Entry": entry_date,
            "DOB": dob,
            "OUR RENEWAL": "",
        })
        return base_row, True, "", debug_info

    except Exception as e:
        base_row["Client Name"] = file_name
        debug_info["client_name"] = file_name
        debug_info["error_reason"] = str(e)
        return base_row, False, str(e), debug_info
