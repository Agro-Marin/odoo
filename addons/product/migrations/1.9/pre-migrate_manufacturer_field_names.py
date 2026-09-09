import ast
import json
import logging
import re

from lxml import etree

_logger = logging.getLogger(__name__)

RENAMES = {
    "manufacturer": "is_manufacturer",
    "product_count": "count_manufactured_products",
}

MODELS = ["res.partner", "res.users"]


def migrate(cr, version):
    _rename_the_column(cr)
    _rename_the_metadata_rows(cr)
    _rewrite_stored_arches(cr)
    _rewrite_saved_filters(cr)


def _rename_the_column(cr):
    cr.execute(
        """
        SELECT column_name FROM information_schema.columns
         WHERE table_name = 'res_partner' AND column_name = ANY(%s)
        """,
        (["manufacturer", "is_manufacturer"],),
    )
    present = {name for (name,) in cr.fetchall()}
    if "is_manufacturer" in present or "manufacturer" not in present:
        return
    cr.execute("ALTER TABLE res_partner RENAME COLUMN manufacturer TO is_manufacturer")
    _logger.info("renamed res_partner.manufacturer to is_manufacturer")


def _rename_the_metadata_rows(cr):
    for old, new in RENAMES.items():
        cr.execute(
            "UPDATE ir_model_fields SET name = %s WHERE name = %s AND model = ANY(%s)",
            (new, old, MODELS),
        )
        fields_moved = cr.rowcount
        cr.execute(
            """
            UPDATE ir_model_data SET name = %s
             WHERE model = 'ir.model.fields' AND name = %s
            """,
            (f"field_res_partner__{new}", f"field_res_partner__{old}"),
        )
        cr.execute(
            """
            UPDATE ir_model_data SET name = %s
             WHERE model = 'ir.model.fields' AND name = %s
            """,
            (f"field_res_users__{new}", f"field_res_users__{old}"),
        )
        _logger.info("renamed %s to %s on %s model(s)", old, new, fields_moved)


def _rewrite_saved_filters(cr):
    """A user's saved filter names the field in a domain nobody re-loads.

    A module's own domains are rewritten by its data files on upgrade, and a
    domain naming a field that no longer exists does NOT fail at load -- it
    raises when someone opens the filter. So these are rewritten here, and only
    where the domain parses: a filter this cannot read is left alone and named
    in the log rather than edited by pattern.
    """
    # `ir.filters.model_id` is a Selection holding the model NAME, not a
    # Many2one to ir_model -- the column is varchar and a join on ir_model.id
    # dies on `integer = character varying`.
    cr.execute(
        """
        SELECT id, domain FROM ir_filters
         WHERE model_id = 'res.partner' AND domain IS NOT NULL
        """
    )
    rewritten = 0
    unreadable = []
    for filter_id, domain in cr.fetchall():
        try:
            parsed = ast.literal_eval(domain)
        except ValueError, SyntaxError:
            if any(old in domain for old in RENAMES):
                unreadable.append(filter_id)
            continue
        changed, new_domain = _rename_leaves(parsed)
        if not changed:
            continue
        cr.execute(
            "UPDATE ir_filters SET domain = %s WHERE id = %s",
            (repr(new_domain), filter_id),
        )
        rewritten += 1
    if rewritten:
        _logger.info("rewrote %s saved res.partner filter(s)", rewritten)
    if unreadable:
        _logger.warning(
            "left %s saved res.partner filter(s) alone -- their domain does not "
            "parse and naming a field by pattern would rewrite a value: %s",
            len(unreadable),
            unreadable,
        )


def _rename_leaves(domain):
    """Rewrite only the FIELD position of a leaf, never an operator or a value."""
    changed = False
    out = []
    for item in domain:
        if isinstance(item, (list, tuple)) and len(item) == 3:
            field, operator, value = item
            head, dot, rest = str(field).partition(".")
            if head in RENAMES:
                field = RENAMES[head] + dot + rest
                changed = True
            out.append((field, operator, value))
        else:
            out.append(item)
    return changed, out


# Attributes whose VALUE is a Python expression naming fields. `name` and `for`
# are handled per tag instead, because <group name="manufacturer"> and
# id="manufacturer_span" are node names that must not move.
EXPRESSION_ATTRS = (
    "invisible",
    "readonly",
    "required",
    "column_invisible",
    "domain",
    "context",
)


def _rewrite_stored_arches(cr):
    cr.execute(
        """
        SELECT id, arch_db FROM ir_ui_view
         WHERE model = 'res.partner' AND arch_db IS NOT NULL
           AND arch_db::text ~ %s
        """,
        ("|".join(RENAMES),),
    )
    rewritten = 0
    unreadable = []
    for view_id, arch_db in cr.fetchall():
        if isinstance(arch_db, str):
            arch_db = json.loads(arch_db)
        new = {}
        failed = False
        for lang, arch in arch_db.items():
            try:
                new[lang] = _rewrite_arch(arch)
            except etree.XMLSyntaxError:
                failed = True
                break
        if failed:
            unreadable.append(view_id)
            continue
        if new == arch_db:
            continue
        cr.execute(
            "UPDATE ir_ui_view SET arch_db = %s WHERE id = %s",
            (json.dumps(new), view_id),
        )
        rewritten += 1
    if rewritten:
        _logger.info("rewrote %s stored res.partner view arch(es)", rewritten)
    if unreadable:
        _logger.warning(
            "left %s res.partner arch(es) alone -- they do not parse: %s",
            len(unreadable),
            unreadable,
        )


def _rewrite_arch(arch):
    tree = etree.fromstring(arch.encode())
    for node in tree.iter():
        if node.tag == "field" and node.get("name") in RENAMES:
            node.set("name", RENAMES[node.get("name")])
        if node.tag == "label" and node.get("for") in RENAMES:
            node.set("for", RENAMES[node.get("for")])
        for attr in EXPRESSION_ATTRS:
            value = node.get(attr)
            if value:
                node.set(attr, _rename_words(value))
    return etree.tostring(tree, encoding="unicode")


def _rename_words(text):
    """Rewrite whole-word field names, and the context keys built from them."""
    for old, new in RENAMES.items():
        text = re.sub(
            rf"\b(default_|search_default_)?{old}\b",
            lambda m, new=new: (m.group(1) or "") + new,
            text,
        )
    return text
