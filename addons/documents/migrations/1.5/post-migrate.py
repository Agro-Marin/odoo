from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    alias = env.ref(
        "documents.document_inbox_folder_mail_alias", raise_if_not_found=False
    )
    if not alias or alias.alias_parent_model_id or not alias.alias_parent_thread_id:
        return
    alias.alias_parent_model_id = env["ir.model"]._get_id("documents.document")
