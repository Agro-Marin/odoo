import logging
import re

from odoo import models
from odoo.tests import common

_logger = logging.getLogger(__name__)

BTREE_INDEX_PY_DEFS = (True, "1", "btree", "btree_not_null")

_LEADING_COLUMN_RE = re.compile(
    r"""
    \(\s*
    (?P<column>\w+)               # the leading column, a plain identifier
    (?:\s+(?:ASC|DESC))?          # its direction, which does not change what
                                  # the index can serve
    (?P<rest>[,)])                # a comma (composite) or the closing paren
    """,
    re.VERBOSE | re.IGNORECASE,
)


def leading_index_columns(model) -> set[str]:
    columns: set[str] = set()
    for table_object in getattr(model, "_table_objects", {}).values():
        if not isinstance(table_object, models.Index):
            continue
        try:
            definition = table_object.get_definition(model.pool)
        except Exception:
            _logger.debug(
                "could not render the definition of %s on %s",
                table_object.name,
                getattr(model, "_name", model),
                exc_info=True,
            )
            continue
        clause = re.sub(
            r"^\s*(UNIQUE\s+)?INDEX\s*", "", definition, flags=re.IGNORECASE
        )
        if re.match(r"^\s*USING\s+(?!btree\b)", clause, flags=re.IGNORECASE):
            continue
        clause = re.sub(r"^\s*USING\s+btree\s*", "", clause, flags=re.IGNORECASE)
        match = _LEADING_COLUMN_RE.match(clause)
        if not match:
            continue
        column = match.group("column")
        condition = clause[match.end() :]
        if "where" in condition.lower():
            if not re.search(
                rf"WHERE\s+{re.escape(column)}\s+IS\s+NOT\s+NULL\s*$",
                condition,
                flags=re.IGNORECASE,
            ):
                continue
        columns.add(column)
    return columns


BTREE_INDEX_IGNORE_MODELS = {
    "res.company",
    "stock.warehouse",
    "event.type",
    "event.type.mail",
    "event.type.ticket",
    "ir.sequence",
    "ir.sequence.date_range",
    "ir.module.module",
    "ir.module.module.dependency",
    "ir.module.module.exclusion",
}
BTREE_INDEX_IGNORE_FIELDS = {
    "mail.message.res_id",
    "ir.attachment.res_id",
    "spreadsheet.revision.res_id",
    "discuss.channel.rtc.session.channel_member_id",
    "documents.document.attachment_id",
    "account.fiscal.position.account.position_id",
    "mailing.subscription.contact_id",
    "knowledge.article.member.article_id",
    "slide.channel.forum_id",
    "hr.appraisal.skill.appraisal_id",
    "res.users.settings.user_id",
    "project.collaborator.project_id",
}


@common.tagged("post_install", "-at_install")
@common.no_retry
class TestIndex(common.TransactionCase):
    def test_enforce_index_on_one2many_inverse(self):
        def ignore(o2m_field, m2o_field, comodel):
            if not comodel._auto or comodel._abstract:
                return True
            if comodel.is_transient():
                return True
            if not m2o_field.is_column:
                return True
            if o2m_field.comodel_name in BTREE_INDEX_IGNORE_MODELS:
                return True
            if str(m2o_field) in BTREE_INDEX_IGNORE_FIELDS:
                return True
            if m2o_field.index in BTREE_INDEX_PY_DEFS:
                return True
            if m2o_field.name in leading_index_columns(comodel):
                return True
            ir_model_id = self.env["ir.model"]._get_id(comodel._name)
            modules = (
                self.env["ir.model.data"]
                .search_fetch(
                    [("model", "=", "ir.model"), ("res_id", "=", ir_model_id)],
                    ["module"],
                )
                .mapped("module")
            )
            return bool(modules) and all("test" in module for module in modules)

        fields_to_index = set()
        for model_name in self.env.registry:
            model = self.env[model_name]
            for field in model._fields.values():
                if field.type == "one2many" and field.inverse_name:
                    comodel = self.env[field.comodel_name]
                    inverse_field = comodel._fields[field.inverse_name].base_field
                    if not ignore(field, inverse_field, comodel):
                        fields_to_index.add(f"{inverse_field} (inverse of {field})")
        if fields_to_index:
            msg = (
                "The following fields should be indexed with a btree index,\n"
                "as they are inverse of an One2many field:\n"
                "- if the field is sparse -> 'btree_not_null'\n"
                "- if the field is Required or low fraction of False/NULL values -> True or 'btree'\n"
                f"- if not sure -> 'btree_not_null': \n{'\n'.join(sorted(fields_to_index))}"
            )
            self.fail(msg)
