from odoo.tests import common

BTREE_INDEX_PY_DEFS = (True, "1", "btree", "btree_not_null")
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
    "discuss.channel.member.channel_id",
    "discuss.channel.rtc.session.channel_member_id",
    "documents.document.attachment_id",
    "account.fiscal.position.account.position_id",
    "mailing.subscription.contact_id",
    "knowledge.article.member.article_id",
    "slide.channel.forum_id",
    "hr.appraisal.skill.appraisal_id",
    "mail.presence.user_id",
    "mail.presence.guest_id",
    "res.users.settings.user_id",
    "project.collaborator.project_id",
}


@common.tagged("post_install", "-at_install")
@common.no_retry
class TestIndex(common.TransactionCase):
    def test_enforce_index_on_one2many_inverse(self):

        def ignore(o2m_field, m2o_field):
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
                    if not ignore(field, inverse_field):
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
