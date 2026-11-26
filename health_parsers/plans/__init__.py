from health_parsers.plans.hdfc_sarv_suraksha_plus_group import (
    is_hdfc_sarv_suraksha_plus_group,
    parse_hdfc_sarv_suraksha_plus_group,
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
from health_parsers.plans.national_parivar_mediclaim import (
    is_national_parivar_mediclaim,
    parse_national_parivar_mediclaim,
)
from health_parsers.plans.new_india_cpa_vehicle import (
    is_new_india_cpa_vehicle,
    parse_new_india_cpa_vehicle,
)

# Plan-wise isolated parsers (main company parsers remain untouched)
PLAN_PARSERS = {
    "HDFC ERGO": [
        (is_hdfc_sarv_suraksha_plus_group, parse_hdfc_sarv_suraksha_plus_group),
        (is_hdfc_individual_pa, parse_hdfc_individual_pa),
    ],
    "STAR HEALTH": [
        (is_star_health_assure, parse_star_health_assure),
        (is_star_medi_classic_individual, parse_star_medi_classic_individual),
    ],
    "NATIONAL": [
        (is_national_parivar_mediclaim, parse_national_parivar_mediclaim),
    ],
    "NEW INDIA": [
        (is_new_india_cpa_vehicle, parse_new_india_cpa_vehicle),
    ],
}


def dispatch_plan_parser(company: str, pdf_text: str):
    """Runs a dedicated plan parser if matched; otherwise falls back to main company parser."""
    for detector_fn, parser_fn in PLAN_PARSERS.get(company, []):
        if detector_fn(pdf_text):
            return parser_fn(pdf_text)
    return None
