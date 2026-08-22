import re
from random import randint

from odoo import api, fields, models
from odoo.tools import SQL

_CODE_SEPARATORS = re.compile(r"[^A-Z0-9]+")


class MixinTag(models.AbstractModel):
    _name = "mixin.tag"
    _inherit = ["mixin.catalog"]
    _description = "Tag (coloured label with a stable code)"
    _order = "name, id"

    def _default_color(self):
        return randint(1, 11)

    name = fields.Char(string="Tag Name")
    active = fields.Boolean(
        help="Archive a tag to hide it without deleting it.",
    )
    color = fields.Integer(
        string="Color",
        default=_default_color,
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
    _code_uniq = models.Constraint(
        "unique(code)",
        "A tag with this code already exists.",
    )

    @api.depends("name")
    def _compute_code(self):
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
        return _CODE_SEPARATORS.sub("_", (name or "").upper()).strip("_")[:64]
