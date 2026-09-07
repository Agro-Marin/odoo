import logging

_logger = logging.getLogger(__name__)

REDUNDANT_INDEX = "document_type__code_index"


def migrate(cr, version):
    """Drop the plain index on document.type.code.

    _code_company_uniq is a unique btree whose leading column is code, so it
    answers every query this one answered. Dropping index=True from the field
    is not enough on its own: _registry_schema deliberately keeps an index it
    no longer manages ("Keep unexpected index"), so it has to go explicitly.
    """
    if not version:
        return
    cr.execute(f"DROP INDEX IF EXISTS {REDUNDANT_INDEX}")
    _logger.info("Dropped redundant index %s if it existed", REDUNDANT_INDEX)
