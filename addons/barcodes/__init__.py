from . import models


def _assign_default_nomenclature(env):
    companies_without_nomenclature = env["res.company"].search(
        [("nomenclature_id", "=", False)]
    )
    default_nomenclature = env.ref(
        "barcodes.default_barcode_nomenclature", raise_if_not_found=False
    )
    if default_nomenclature:
        companies_without_nomenclature.nomenclature_id = default_nomenclature
