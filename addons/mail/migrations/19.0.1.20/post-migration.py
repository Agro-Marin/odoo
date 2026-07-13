import logging

_logger = logging.getLogger(__name__)

# Font Awesome style classes (FA7 long form + FA5 shorthands). One of these must
# be present for an icon to render: FA7 sets font-family/weight on the style
# class, not on the bare ``fa`` base class that FA4/5 relied on.
_FA_STYLE_TOKENS = {
    "fa-solid",
    "fa-regular",
    "fa-brands",
    "fa-light",
    "fa-thin",
    "fa-duotone",
    "fas",
    "far",
    "fab",
    "fal",
    "fat",
    "fad",
}


def _to_fa7(icon):
    """Normalize a legacy Font Awesome icon class to FA7.

    The chatter/activity templates dropped the ``fa`` base class they used to
    prepend (``fa #{icon} fa-fw`` -> ``#{icon}``), so a stored value like
    ``fa-envelope`` or ``fa fa-envelope`` now renders as an empty box: FA7 only
    attaches the font to a style class. Ensure one is present.
    """
    tokens = icon.split()
    # The lone ``fa`` base class carries no font in FA7; drop it.
    tokens = [tok for tok in tokens if tok != "fa"]
    if not any(tok in _FA_STYLE_TOKENS for tok in tokens):
        tokens.insert(0, "fa-solid")
    return " ".join(tokens)


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        "SELECT id, icon FROM mail_activity_type WHERE icon IS NOT NULL AND icon != ''"
    )
    remapped = [
        (new_icon, row_id)
        for row_id, icon in cr.fetchall()
        if (new_icon := _to_fa7(icon)) != icon
    ]
    for new_icon, row_id in remapped:
        cr.execute(
            "UPDATE mail_activity_type SET icon = %s WHERE id = %s", (new_icon, row_id)
        )
    if remapped:
        _logger.info(
            "mail: normalized %s activity-type icon(s) to Font Awesome 7",
            len(remapped),
        )
