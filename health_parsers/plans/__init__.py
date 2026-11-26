from health_parsers.plans.hdfc_sarv_suraksha_plus_group import (
    is_hdfc_sarv_suraksha_plus_group,
    parse_hdfc_sarv_suraksha_plus_group,
)
from health_parsers.plans.hdfc_optima_restore import (
    is_hdfc_optima_restore,
    parse_hdfc_optima_restore,
)
from health_parsers.plans.hdfc_koti_suraksha import (
    is_hdfc_koti_suraksha,
    parse_hdfc_koti_suraksha,
)
from health_parsers.plans.hdfc_individual_pa import (
    is_hdfc_individual_pa,
    parse_hdfc_individual_pa,
)
from health_parsers.plans.star_health_assure import (
    is_star_health_assure,
    parse_star_health_assure,
)
from health_parsers.plans.star_medi_classic_individual import (
    is_star_medi_classic_individual,
    parse_star_medi_classic_individual,
)
from health_parsers.plans.star_super_surplus import (
    is_star_super_surplus,
    parse_star_super_surplus,
)
from health_parsers.plans.star_super_star import (
    is_star_super_star,
    parse_star_super_star,
)
from health_parsers.plans.star_women_care import (
    is_star_women_care,
    parse_star_women_care,
)
from health_parsers.plans.star_comprehensive import (
    is_star_comprehensive,
    parse_star_comprehensive,
)
from health_parsers.plans.national_parivar_mediclaim import (
    is_national_parivar_mediclaim,
    parse_national_parivar_mediclaim,
)
from health_parsers.plans.new_india_cpa_vehicle import (
    is_new_india_cpa_vehicle,
    parse_new_india_cpa_vehicle,
)
from health_parsers.plans.manipal_cigna_sarvah import (
    is_manipal_cigna_sarvah,
    parse_manipal_cigna_sarvah,
)
from health_parsers.plans.aditya_birla_activ_one import (
    is_aditya_birla_activ_one,
    parse_aditya_birla_activ_one,
)
from health_parsers.plans.iffco_tokio_fhp import (
    is_iffco_tokio_fhp,
    parse_iffco_tokio_fhp,
)

# Plan-wise isolated parsers (main company parsers remain untouched)
PLAN_PARSERS = {
    "HDFC ERGO": [
        (is_hdfc_sarv_suraksha_plus_group, parse_hdfc_sarv_suraksha_plus_group),
        (is_hdfc_optima_restore, parse_hdfc_optima_restore),
        (is_hdfc_koti_suraksha, parse_hdfc_koti_suraksha),
        (is_hdfc_individual_pa, parse_hdfc_individual_pa),
    ],
    "STAR HEALTH": [
        (is_star_health_assure, parse_star_health_assure),
        (is_star_medi_classic_individual, parse_star_medi_classic_individual),
        (is_star_super_surplus, parse_star_super_surplus),
        (is_star_super_star, parse_star_super_star),
        (is_star_women_care, parse_star_women_care),
        (is_star_comprehensive, parse_star_comprehensive),
    ],
    "NATIONAL": [
        (is_national_parivar_mediclaim, parse_national_parivar_mediclaim),
    ],
    "NEW INDIA": [
        (is_new_india_cpa_vehicle, parse_new_india_cpa_vehicle),
    ],
    "MANIPAL CIGNA": [
        (is_manipal_cigna_sarvah, parse_manipal_cigna_sarvah),
    ],
    "ADITYA BIRLA": [
        (is_aditya_birla_activ_one, parse_aditya_birla_activ_one),
    ],
    "IFFCO TOKIO": [
        (is_iffco_tokio_fhp, parse_iffco_tokio_fhp),
    ],
}


def dispatch_plan_parser(company: str, pdf_text: str):
    """Runs a dedicated plan parser if matched; otherwise falls back to main company parser."""
    for detector_fn, parser_fn in PLAN_PARSERS.get(company, []):
        if detector_fn(pdf_text):
            return parser_fn(pdf_text)
    return None
