from health_parsers.plans.hdfc_sarv_suraksha_plus_group import (
    is_hdfc_sarv_suraksha_plus_group,
    parse_hdfc_sarv_suraksha_plus_group,
)

# Har company ke Plan-Wise isolated parsers yahan register honge (Main company parser ko bina touch kiye)
PLAN_PARSERS = {
    "HDFC ERGO": [
        (is_hdfc_sarv_suraksha_plus_group, parse_hdfc_sarv_suraksha_plus_group),
    ],
}


def dispatch_plan_parser(company: str, pdf_text: str):
    """Agar kisi plan ka dedicated parser match ho to wahi run karega, warna None (main parser fallback)."""
    for detector_fn, parser_fn in PLAN_PARSERS.get(company, []):
        if detector_fn(pdf_text):
            return parser_fn(pdf_text)
    return None
