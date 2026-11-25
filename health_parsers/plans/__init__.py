from health_parsers.plans.hdfc_sarv_suraksha_plus_group import (
    is_hdfc_sarv_suraksha_plus_group,
    parse_hdfc_sarv_suraksha_plus_group,
)
from health_parsers.plans.star_health_assure import (
    is_star_health_assure,
    parse_star_health_assure,
)

# Plan-wise isolated parsers (main company parsers remain untouched)
PLAN_PARSERS = {
    "HDFC ERGO": [
        (is_hdfc_sarv_suraksha_plus_group, parse_hdfc_sarv_suraksha_plus_group),
    ],
    "STAR HEALTH": [
        (is_star_health_assure, parse_star_health_assure),
    ],
}


def dispatch_plan_parser(company: str, pdf_text: str):
    """Runs a dedicated plan parser if matched; otherwise falls back to main company parser."""
    for detector_fn, parser_fn in PLAN_PARSERS.get(company, []):
        if detector_fn(pdf_text):
            return parser_fn(pdf_text)
    return None
