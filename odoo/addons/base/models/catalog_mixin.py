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


def no_name_uniq_index():
    """Opt a catalog out of the inherited name-uniqueness rule.

    ``_table_objects`` collects every definition up the MRO and keys them by
    attribute name, so an inheritor can replace ``_name_src_uniq`` but has no
    way to remove it. Replacing it with an index whose definition is empty is
    the removal: ``Index.apply_to_database`` drops whatever index the table
    already carries under that name and then returns without creating one, so
    the opt-out also *undoes* the rule on an existing database rather than
    leaving a stale index enforcing it.

    Reach for this only when duplicate names are a legitimate state rather
    than an oversight. ``product.attribute`` is the case that motivates it:
    ``product`` ships eight attributes of its own, and a second "Size" whose
    values are shoe sizes is a different dimension, not the same one entered
    twice.

    :rtype: odoo.models.UniqueIndex
    """
    return models.UniqueIndex(lambda registry: "")


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

    Uniqueness is the default rather than an option to switch on: an inheritor
    that says nothing gets it. One that scopes names to a parent redeclares
    ``_name_src_uniq`` with that scope, and one for which duplicate names are a
    legitimate state declares :func:`no_name_uniq_index` -- explicitly, because
    that is a claim about the data worth making in one line rather than by
    omission.

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
