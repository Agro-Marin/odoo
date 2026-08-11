import re
from random import randint

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import SQL

from odoo.addons.base.models.catalog_mixin import name_uniq_index

_CODE_SEPARATORS = re.compile(r"[^A-Z0-9]+")


class TagMixin(models.AbstractModel):
    """A colour-coded label with a stable code: the flat tag.

    ``catalog.mixin`` (translated unique name, archivable) plus the two things
    every tag in the tree adds to it by hand: a colour index -- the same
    ``randint(1, 11)`` default written out about thirty times -- and a ``code``
    for anything that has to *match* the tag rather than display it.

    Flat on purpose. This mixin used to be the hierarchical one, and its name
    said nothing about that: a model inheriting "tag.mixin" silently acquired
    ``_parent_store``, a ``parent_path`` column, a recursion constraint and a
    name rule scoped to a parent it had never heard of. Nesting now lives in
    :class:`tag.nested.mixin`, and the plain name means the plain thing.

    Roughly seventeen tag models in the tree are flat; two are nested.

    **When you need ``code``, and when you do not.** Not every name-based
    lookup is unsafe, and the distinction is worth stating because the safe
    case is the common one.

    *Resolve-or-create is fine on ``name``.* Creating a tag writes the term
    into every active language at once, so two callers running under different
    languages converge on one row rather than making two::

        es_MX creates "Periodo 2027"  ->  {"en_US": "Periodo 2027",
                                           "es_MX": "Periodo 2027"}
        en_US searches "Periodo 2027" ->  finds that same row

    That pattern is self-consistent by construction, and a cron in ``en_US``
    racing a user in ``es_MX`` does not duplicate.

    *Looking up a tag you did not create is what needs ``code``.* Once anyone
    edits the label, the term you were matching on may be gone -- and **how**
    it was edited decides which languages lose it, which is why no single
    "search in language X" rule saves you. Both paths measured on a tag created
    as "3001" with ``es_MX`` active::

        plain write in es_MX ("rename this tag")
            {"en_US": "Periodo tres mil uno", "es_MX": "Periodo tres mil uno"}
            search "3001" -> nothing, in either language

        translation dialog (update_field_translations)
            {"en_US": "3001", "es_MX": "Periodo tres mil uno"}
            search "3001" -> found in en_US, nothing in es_MX

    A plain write to a field carrying no distinct translations yet is taken as
    correcting the term itself, so it moves every language; the dialog is taken
    as translating, so it moves one. Pinning a lookup to the source term
    therefore survives the second and not the first.

    ``code`` survives both, because nothing about renaming a label touches it.
    So: an import keyed on a label, a filter, a server action, an XML record
    pointing at a tag someone else maintains -- those match on ``code``.
    """

    _name = "tag.mixin"
    _inherit = ["catalog.mixin"]
    _description = "Tag (coloured label with a stable code)"
    _order = "name, id"

    def _get_default_color(self):
        return randint(1, 11)

    name = fields.Char(string="Tag Name")
    active = fields.Boolean(
        help="Archive a tag to hide it without deleting it.",
    )
    color = fields.Integer(
        string="Color",
        default=_get_default_color,
        aggregator=False,
    )
    code = fields.Char(
        string="Code",
        compute="_compute_code",
        store=True,
        readonly=False,
        copy=False,
        index="btree",
        help=(
            "Stable identifier for imports, filters and data files. Unlike the "
            "name it is never translated, so it means the same thing to every "
            "reader."
        ),
    )
    # Plain UNIQUE over a plain column, which is the whole point of the field.
    # `name` is `translate=True`, hence jsonb, hence a rule that has to index an
    # expression over the source term and still only holds *within a parent*.
    # Identity is a different question from display, and this is where it lives.
    _code_uniq = models.Constraint(
        "unique(code)",
        "A tag with this code already exists.",
    )

    @api.depends("name")
    def _compute_code(self):
        """Derive a code from the name, once, for tags that have none.

        ``readonly=False`` plus the "already has one" guard mean this only ever
        *fills a blank*: a code set by a user or a data file is never
        recomputed, and renaming a tag does not silently change the value other
        records match against. The dependency on ``name`` exists to schedule the
        compute for a new record, not to follow the name around afterwards.

        Being stored and computed is also what backfills an existing database:
        Odoo computes a newly added stored column for every row, so tags that
        predate this field get a code from their name without a migration
        script.

        Collisions get a numeric suffix rather than being left to the UNIQUE.
        Two different names can slug to one code -- "Hot!" and "Hot?", or the
        same name under two parents, which the name rule allows on purpose --
        and a create failing on a value the user never typed is a bad error.
        Taken codes are read once per batch, which matters when a data file
        loads a hundred tags at once.
        """
        pending = self.filtered(lambda tag: not tag.code and tag.name)
        self.filtered(lambda tag: not tag.code and not tag.name).code = False
        if not pending:
            return
        taken = {
            code
            for [code] in self.env.execute_query(
                SQL(
                    "SELECT code FROM %s WHERE code IS NOT NULL",
                    SQL.identifier(self._table),
                )
            )
        }
        for tag in pending:
            base = self._code_from_name(tag.name) or "TAG"
            candidate, suffix = base, 1
            while candidate in taken:
                suffix += 1
                candidate = f"{base}_{suffix}"
            taken.add(candidate)
            tag.code = candidate

    @api.model
    def _code_from_name(self, name):
        """Slug a display name into a code: upper case, ASCII-ish, underscores.

        Reads whatever ``name`` returns for the current user, which is the
        source term on create -- the record is being made in some language and
        that is the one term it has.
        """
        return _CODE_SEPARATORS.sub("_", (name or "").upper()).strip("_")[:64]


class TagNestedMixin(models.AbstractModel):
    """A tag that nests: parent, children, and a path for a display name.

    Everything :class:`tag.mixin` gives, plus the hierarchy — so a model opts
    into a tree by asking for one, rather than by inheriting the word "tag".

    The inheriting model declares its own ``parent_id`` and ``child_ids``,
    because a self-reference cannot name its comodel from here.

    Name uniqueness is re-scoped to the parent: two branches may each hold a
    "North", which is the point of a tree, and the flat rule would refuse the
    second. The derived declaration replaces the inherited one under the same
    attribute name — see :class:`catalog.mixin` for why that is the supported
    way to change it. ``code`` stays globally unique regardless: identity is
    not a per-branch question.
    """

    _name = "tag.nested.mixin"
    _inherit = ["tag.mixin"]
    _description = "Nested Tag (tag with a parent/child hierarchy)"
    _parent_store = True

    parent_path = fields.Char(index=True)

    _name_src_uniq = name_uniq_index(
        "parent_id",
        message="A tag with this name already exists under the same parent.",
    )

    @api.constrains("parent_id")
    def _check_parent_id(self):
        if self._has_cycle():
            raise ValidationError(_("You can not create recursive tags."))

    @api.depends("name", "parent_id.name")
    def _compute_display_name(self):
        paths = {}
        ancestor_ids = set()
        for tag in self:
            if tag.parent_path:
                paths[tag.id] = ids = [
                    int(key) for key in tag.parent_path.split("/") if key
                ]
                ancestor_ids.update(ids)
        ancestors = self.browse(ancestor_ids)
        ancestors.fetch(["name"])
        names = {tag.id: tag.name or "" for tag in ancestors}

        for tag in self:
            path_ids = paths.get(tag.id)
            if path_ids is not None:
                tag.display_name = " / ".join(names[key] for key in path_ids)
                continue
            walked = []
            seen = set()
            current = tag
            while current and current.id not in seen:
                seen.add(current.id)
                walked.append(current.name or "")
                current = current.parent_id
            tag.display_name = " / ".join(reversed(walked))

    @api.model
    def _search_display_name(self, operator, value):
        domain = super()._search_display_name(operator, value)
        if operator.endswith("like"):
            if operator.startswith("not"):
                return NotImplemented
            return [("id", "child_of", tuple(self._search(domain)))]
        return domain
