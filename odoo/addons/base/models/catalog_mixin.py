"""Shared shape of a catalog: a named, archivable record with a unique name."""

from odoo import fields, models

SOURCE_LANG = "en_US"

assert SOURCE_LANG.replace("_", "").isalnum(), "SOURCE_LANG must be an alphanumeric tag"
_NAME_SOURCE_SQL = f"(name->>'{SOURCE_LANG}')"


def name_uniq_index(*scope, message=None):
    """Build the catalog name-uniqueness rule, optionally scoped to a parent.

    **Why an index and not a Constraint.** A ``translate=True`` Char is stored
    as a ``jsonb`` column, so the obvious ``UNIQUE(name)`` compares whole
    translation *documents* rather than names. Two records both called
    "Whitefly" are distinct rows the moment their translation sets differ --
    and they differ as soon as a second language is active, because Odoo writes
    the active language alongside the source term on create. A user working in
    Spanish creating "Mosca blanca" therefore stores ``{"en_US": .., "es_MX":
    ..}`` where an English colleague stored ``{"en_US": ..}``, and the
    constraint sees no duplicate.

    The rule has to compare the *source term*, which means an expression, and
    PostgreSQL does not allow expressions in a UNIQUE constraint. It must
    therefore be an index -- but a ``models.UniqueIndex`` rather than a
    hand-rolled ``CREATE UNIQUE INDEX``, so that Odoo registers it in
    ``_table_objects``. Registration is what buys the three properties a
    hand-rolled index does not have:

    * a violation is reported with ``message`` instead of raw PostgreSQL text;
    * the definition is stored in the index comment and compared on every
      upgrade, so changing the scope here actually re-creates the index rather
      than silently leaving the old rule in force;
    * application goes through ``Registry.post_constraint``, which logs and
      carries on when duplicate rows block creation, and retries once the rest
      of the modules have loaded.

    Odoo's own counter-pattern is ``utm.medium``, which declares
    ``translate=False`` specifically so its ``UNIQUE(name)`` holds. That is not
    available here: catalog names genuinely need translating (Papa/Potato).

    The language key is interpolated as a literal rather than bound: an index
    definition is DDL and PostgreSQL accepts no bind parameters there.
    ``SOURCE_LANG`` is a module constant that never sees user input, and the
    assertion above keeps it that way should anyone make it configurable.

    :param scope: extra columns the name must only be unique *within*, e.g.
        ``"parent_id"`` on a hierarchical catalog. Empty means globally unique.
        ``NULLS NOT DISTINCT`` makes a NULL scope column compare as a value, so
        a parentless record still collides with another parentless record of
        the same name.
    :param str message: what to tell the user on a violation.
    :rtype: odoo.models.UniqueIndex
    """
    columns = ", ".join([_NAME_SOURCE_SQL, *scope])
    return models.UniqueIndex(
        f"({columns}) NULLS NOT DISTINCT",
        message or "A record with this name already exists in this catalog.",
    )


class CatalogMixin(models.AbstractModel):
    """A named, archivable record whose name is unique.

    The single most repeated field bundle in this codebase: 289 concrete models
    across 155 modules declare ``name`` and ``active`` themselves, and 95% of
    them carry no name-uniqueness rule at all. The three declarations are the
    small half of what is consolidated here; the rule is the large half, since
    it is the one piece that is easy to get wrong (see :func:`name_uniq_index`)
    and expensive to discover wrong.

    The rule declared here is the *unscoped* one, and it reaches every
    inheriting catalog with that catalog's own table name, because Odoo builds
    ``_table_objects`` per concrete model. A catalog whose names are only
    unique within a parent redeclares ``_name_src_uniq`` with its own scope,
    and the derived declaration wins.

    Uniqueness is part of the contract, not an option: ``_table_objects``
    collects every definition up the MRO, so an inheritor can re-scope the rule
    but cannot drop it. A model that must tolerate duplicate names does not
    belong on this mixin.

    Scope is deliberately the whole table, archived records included: an
    archived catalog entry keeps its name reserved.
    """

    _name = "catalog.mixin"
    _description = "Catalog Mixin"

    name = fields.Char(
        required=True,
        translate=True,
    )
    active = fields.Boolean(
        default=True,
    )

    _name_src_uniq = name_uniq_index()
