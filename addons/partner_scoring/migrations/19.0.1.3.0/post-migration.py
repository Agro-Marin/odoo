import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # partner.profile.company_id defaulted to the acting user's company, so
    # every scale created through the UI was company-scoped by accident rather
    # than by decision -- and _compute_partner_profile_id resolves a partner
    # against its own company's bands, a partner with no company against
    # company-less ones. Odoo partners carry no company unless someone sets one,
    # so a scale that was never meant to be scoped classified nobody at all.
    #
    # Clearing it is only unambiguous where the scale was never multi-company in
    # the first place: one company across every band means the value came from
    # the default. A deployment that genuinely runs a scale per company is left
    # exactly as it is.
    cr.execute(
        """
        SELECT count(DISTINCT company_id), count(*) FILTER (WHERE company_id IS NULL)
          FROM partner_profile
         WHERE active
        """
    )
    distinct_companies, already_universal = cr.fetchone()
    if distinct_companies != 1 or already_universal:
        _logger.info(
            "partner.profile: %s distinct companies across the scale, leaving "
            "company_id alone -- this deployment scopes its bands deliberately.",
            distinct_companies,
        )
        return

    cr.execute(
        "UPDATE partner_profile SET company_id = NULL WHERE company_id IS NOT NULL"
    )
    cleared = cr.rowcount
    if not cleared:
        return

    # The assignment is a stored compute whose triggers are the partner's own
    # score and company, so widening the scale does not reach it on its own.
    cr.execute(
        """
        UPDATE res_partner p
           SET partner_profile_id = (
                SELECT id FROM partner_profile b
                 WHERE b.active
                   AND b.min_value <= coalesce(p.score_pct, 0)
                   AND (b.max_value = 0 OR coalesce(p.score_pct, 0) < b.max_value)
                 ORDER BY b.sequence, b.id
                 LIMIT 1
           )
         WHERE p.partner_profile_id IS NULL
        """
    )
    _logger.info(
        "partner.profile: %s band(s) became company-less; %s partner(s) "
        "classified that the accidental scoping had left with no profile.",
        cleared,
        cr.rowcount,
    )
