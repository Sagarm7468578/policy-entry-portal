import importlib

# Registry: (company_name, module_name, detector_fn_name, parser_fn_name)
_PLAN_SPECS = [
    ("HDFC ERGO", "hdfc_sarv_suraksha_plus_group", "is_hdfc_sarv_suraksha_plus_group", "parse_hdfc_sarv_suraksha_plus_group"),
    ("HDFC ERGO", "hdfc_optima_restore", "is_hdfc_optima_restore", "parse_hdfc_optima_restore"),
    ("HDFC ERGO", "hdfc_koti_suraksha", "is_hdfc_koti_suraksha", "parse_hdfc_koti_suraksha"),
    ("HDFC ERGO", "hdfc_energy", "is_hdfc_energy", "parse_hdfc_energy"),
    ("HDFC ERGO", "hdfc_individual_pa", "is_hdfc_individual_pa", "parse_hdfc_individual_pa"),
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
    ("NIVA BUPA", "niva_bupa_reassure3", "is_niva_bupa_reassure3", "parse_niva_bupa_reassure3"),
    ("NATIONAL", "national_parivar_mediclaim", "is_national_parivar_mediclaim", "parse_national_parivar_mediclaim"),
    ("NEW INDIA", "new_india_cpa_vehicle", "is_new_india_cpa_vehicle", "parse_new_india_cpa_vehicle"),
    ("MANIPAL CIGNA", "manipal_cigna_sarvah", "is_manipal_cigna_sarvah", "parse_manipal_cigna_sarvah"),
    ("ADITYA BIRLA", "aditya_birla_activ_one", "is_aditya_birla_activ_one", "parse_aditya_birla_activ_one"),
    ("IFFCO TOKIO", "iffco_tokio_fhp", "is_iffco_tokio_fhp", "parse_iffco_tokio_fhp"),
    ("TATA AIG", "tata_aig_travel", "is_tata_aig_travel", "parse_tata_aig_travel"),
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
    """Runs a dedicated plan parser if matched; otherwise falls back to main company parser."""
    for detector_fn, parser_fn in PLAN_PARSERS.get(company, []):
        if detector_fn(pdf_text):
            return parser_fn(pdf_text)
    return None
