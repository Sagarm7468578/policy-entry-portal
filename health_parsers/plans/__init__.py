import importlib
from health_parsers.plans.verified_defaults import apply_verified_defaults

# Registry: (company_name, module_name, detector_fn_name, parser_fn_name)
_PLAN_SPECS = [
    ("HDFC ERGO", "hdfc_group_health_endorsement", "is_hdfc_group_health_endorsement", "parse_hdfc_group_health_endorsement"),
    ("HDFC ERGO", "hdfc_sarv_suraksha_plus_group", "is_hdfc_sarv_suraksha_plus_group", "parse_hdfc_sarv_suraksha_plus_group"),
    ("HDFC ERGO", "hdfc_optima_restore", "is_hdfc_optima_restore", "parse_hdfc_optima_restore"),
    ("HDFC ERGO", "hdfc_optima_secure", "is_hdfc_optima_secure", "parse_hdfc_optima_secure"),
    ("HDFC ERGO", "hdfc_koti_suraksha", "is_hdfc_koti_suraksha", "parse_hdfc_koti_suraksha"),
    ("HDFC ERGO", "hdfc_energy", "is_hdfc_energy", "parse_hdfc_energy"),
    ("HDFC ERGO", "hdfc_individual_pa", "is_hdfc_individual_pa", "parse_hdfc_individual_pa"),
    ("HDFC ERGO", "hdfc_arogya_sanjeevani", "is_hdfc_arogya_sanjeevani", "parse_hdfc_arogya_sanjeevani"),
    ("STAR HEALTH", "star_health_assure", "is_star_health_assure", "parse_star_health_assure"),
    ("STAR HEALTH", "star_medi_classic_individual", "is_star_medi_classic_individual", "parse_star_medi_classic_individual"),
    ("STAR HEALTH", "star_super_surplus", "is_star_super_surplus", "parse_star_super_surplus"),
    ("STAR HEALTH", "star_super_star", "is_star_super_star", "parse_star_super_star"),
    ("STAR HEALTH", "star_women_care", "is_star_women_care", "parse_star_women_care"),
    ("STAR HEALTH", "star_comprehensive", "is_star_comprehensive", "parse_star_comprehensive"),
    ("STAR HEALTH", "star_arogya_sanjeevani", "is_star_arogya_sanjeevani", "parse_star_arogya_sanjeevani"),
    ("STAR HEALTH", "star_critical_illness", "is_star_critical_illness", "parse_star_critical_illness"),
    ("STAR HEALTH", "star_family_accident_care", "is_star_family_accident_care", "parse_star_family_accident_care"),
    ("STAR HEALTH", "star_senior_citizens_red_carpet", "is_star_senior_citizens_red_carpet", "parse_star_senior_citizens_red_carpet"),
    ("STAR HEALTH", "star_hospital_cash", "is_star_hospital_cash", "parse_star_hospital_cash"),
    ("STAR HEALTH", "star_family_health_optima", "is_star_family_health_optima", "parse_star_family_health_optima"),
    ("NIVA BUPA", "niva_bupa_reassure3", "is_niva_bupa_reassure3", "parse_niva_bupa_reassure3"),
    ("NIVA BUPA", "niva_bupa_reassure2", "is_niva_bupa_reassure2", "parse_niva_bupa_reassure2"),
    ("NIVA BUPA", "niva_bupa_health_recharge", "is_niva_bupa_health_recharge", "parse_niva_bupa_health_recharge"),
    ("NIVA BUPA", "niva_bupa_health_companion", "is_niva_bupa_health_companion", "parse_niva_bupa_health_companion"),
    ("NATIONAL", "national_parivar_mediclaim", "is_national_parivar_mediclaim", "parse_national_parivar_mediclaim"),
    ("NATIONAL", "national_senior_citizen", "is_national_senior_citizen", "parse_national_senior_citizen"),
    ("NATIONAL", "national_personal_accident", "is_national_personal_accident", "parse_national_personal_accident"),
    ("NATIONAL", "national_mediclaim", "is_national_mediclaim", "parse_national_mediclaim"),
    ("NEW INDIA", "new_india_cpa_vehicle", "is_new_india_cpa_vehicle", "parse_new_india_cpa_vehicle"),
    ("NEW INDIA", "new_india_asha_kiran", "is_new_india_asha_kiran", "parse_new_india_asha_kiran"),
    ("NEW INDIA", "new_india_yuva_bharat", "is_new_india_yuva_bharat", "parse_new_india_yuva_bharat"),
    ("MANIPAL CIGNA", "manipal_cigna_sarvah", "is_manipal_cigna_sarvah", "parse_manipal_cigna_sarvah"),
    ("MANIPAL CIGNA", "manipal_cigna_super_top_up", "is_manipal_cigna_super_top_up", "parse_manipal_cigna_super_top_up"),
    ("ADITYA BIRLA", "aditya_birla_activ_one", "is_aditya_birla_activ_one", "parse_aditya_birla_activ_one"),
    ("ADITYA BIRLA", "aditya_birla_activ_health", "is_aditya_birla_activ_health", "parse_aditya_birla_activ_health"),
    ("ADITYA BIRLA", "aditya_birla_activ_yuva", "is_aditya_birla_activ_yuva", "parse_aditya_birla_activ_yuva"),
    ("CARE HEALTH", "care_classic", "is_care_classic", "parse_care_classic"),
    ("CARE HEALTH", "care_supreme", "is_care_supreme", "parse_care_supreme"),
    ("IFFCO TOKIO", "iffco_tokio_fhp", "is_iffco_tokio_fhp", "parse_iffco_tokio_fhp"),
    ("TATA AIG", "tata_aig_travel", "is_tata_aig_travel", "parse_tata_aig_travel"),
    ("ICICI LOMBARD", "icici_lombard_group_health", "is_icici_lombard_group_health", "parse_icici_lombard_group_health"),
    ("ORIENTAL", "oriental_happy_family_floater", "is_oriental_happy_family_floater", "parse_oriental_happy_family_floater"),
]

PLAN_PARSERS = {}
PLAN_LOAD_ERRORS = {}

for _company, _mod_name, _det_name, _prs_name in _PLAN_SPECS:
    try:
        _mod = importlib.import_module(f"health_parsers.plans.{_mod_name}")
        _det = getattr(_mod, _det_name)
        _prs = getattr(_mod, _prs_name)
        PLAN_PARSERS.setdefault(_company, []).append((_det, _prs))
    except Exception as _e:
        # Isolate any single missing/broken plan file so other companies & PDFs NEVER crash
        PLAN_LOAD_ERRORS[_mod_name] = str(_e)


def dispatch_plan_parser(company: str, pdf_text: str):
    """Runs a dedicated plan parser if matched, then applies verified post-rules (Auto-PYP, FRESH, FILL MANUAL)."""
    for detector_fn, parser_fn in PLAN_PARSERS.get(company, []):
        if detector_fn(pdf_text):
            extracted = parser_fn(pdf_text)
            return apply_verified_defaults(company, extracted, pdf_text)
    return None
