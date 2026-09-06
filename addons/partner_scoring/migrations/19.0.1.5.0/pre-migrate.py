import logging

_logger = logging.getLogger(__name__)

# The CRM descriptors moved to marin, which declares the same columns. Handing
# their metadata over before partner_scoring's own cleanup runs keeps the
# columns (and the data in them) instead of letting the module drop fields it
# no longer declares.
_MOVED_FIELDS = (
    "b2x",
    "decisor_name",
    "decisor_phone",
    "social_style_color",
    "competitor_brands",
)


def migrate(cr, version):
    cr.execute(
        "SELECT 1 FROM ir_module_module WHERE name = 'marin'"
        " AND state IN ('installed', 'to upgrade', 'to install')"
    )
    if not cr.fetchone():
        _logger.info(
            "partner_scoring 19.0.1.5.0: marin is not installed, the descriptor "
            "fields %s leave with this module",
            ", ".join(_MOVED_FIELDS),
        )
        return
    patterns = []
    for name in _MOVED_FIELDS:
        patterns += [
            f"field_res_partner__{name}",
            f"field_res_users__{name}",
            f"selection__res_partner__{name}__%",
            f"selection__res_users__{name}__%",
        ]
    conditions = " OR ".join(["d.name LIKE %s"] * len(patterns))
    # marin already reflects a field it extended (social_style_color carried a
    # write_groups extension there), so a row it holds is dropped on this side
    # rather than moved onto a name it already owns.
    cr.execute(
        f"""
        DELETE FROM ir_model_data d
         WHERE d.module = 'partner_scoring'
           AND ({conditions})
           AND EXISTS (
                SELECT 1 FROM ir_model_data m
                 WHERE m.module = 'marin' AND m.name = d.name
           )
        """,
        patterns,
    )
    already_owned = cr.rowcount
    cr.execute(
        f"""
        UPDATE ir_model_data d
           SET module = 'marin'
         WHERE d.module = 'partner_scoring'
           AND ({conditions})
        """,
        patterns,
    )
    _logger.info(
        "partner_scoring 19.0.1.5.0: handed %s field/selection record(s) to marin, "
        "%s were already marin's",
        cr.rowcount,
        already_owned,
    )
