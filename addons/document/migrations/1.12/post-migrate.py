"""Post-migration: stored expressions still naming the ``documents.document`` model.

The 19.0 rename of ``documents.document`` to ``document.document`` updated the
module's XML, and the upgrade reloaded every record that XML owns -- except the
ones marked ``noupdate``. ``mail.template`` is entirely noupdate, so
``document.mail_template_document_share`` kept
``object.env['documents.document']`` and raised ``KeyError`` the moment anyone
shared a document, which is the only time that template is rendered.

Nothing in the upgrade log reports this: the record loads fine, it is only the
expression inside it that names a model the registry no longer has.

Idempotent: the rewrite is whole-word and stops matching once it has run.
"""

from odoo.tools.module_data import rename_in_stored_expressions

OLD_MODEL = "documents.document"
NEW_MODEL = "document.document"


def migrate(cr, version):
    """Repoint stored expressions at the renamed model.

    :param cr: database cursor
    :param version: installed module version; falsy on a fresh install
    """
    if not version:
        return

    rename_in_stored_expressions(cr, OLD_MODEL, NEW_MODEL)
