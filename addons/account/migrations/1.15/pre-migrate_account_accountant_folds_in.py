import logging

_logger = logging.getLogger(__name__)

MODULE = "account_accountant"

# The seven views this module declared under an id `account` was already using. Sharing an
# id was legal while the two modules were separate; inside one module the second record
# would silently update the first, so they are renamed as they arrive.
RENAMED = {
    "account_journal_dashboard_kanban_view": "account_journal_dashboard_kanban_view_reconcile",
    "digest_digest_view_form": "digest_digest_view_form_bank_cash",
    "res_config_settings_view_form": "res_config_settings_view_form_fiscal_year",
    "view_account_form": "view_account_form_reconcile",
    "view_account_move_line_list": "view_account_move_line_list_accounting",
    "view_bank_statement_tree": "view_bank_statement_tree_reconcile",
    "view_move_line_payment_tree": "view_move_line_payment_tree_reconcile",
    "report_invoice_document": "report_invoice_document_signature",
    # both modules declared this access rule and they are two DIFFERENT rows:
    # account grants group_account_manager, the accountant granted
    # group_account_user, and manager does not imply user. Dropping either
    # one takes a grant away, so the accountant's keeps its record under an
    # id of its own.
    "access_account_secure_entries_wizard": "access_account_secure_entries_wizard_user",
}


def _rename_then_repoint(cr):
    for old, new in RENAMED.items():
        cr.execute(
            """
                UPDATE ir_model_data SET name = %s
                 WHERE module = %s AND name = %s
                   AND NOT EXISTS (
                       SELECT 1 FROM ir_model_data WHERE module = 'account' AND name = %s
                   )
            """,
            (new, MODULE, old, new),
        )


def _repoint_everything(cr):
    # An xmlid left behind in a module that no longer declares it is orphaned, and
    # ir_model_data._process_end DELETES the record behind it. For an ir.model.fields row
    # that drops the column and the registry re-adds it empty, so the stored values are
    # gone on a run that reports success. This module declared 122 fields.
    cr.execute(
        """
            UPDATE ir_model_data d SET module = 'account'
             WHERE d.module = %s
               AND NOT EXISTS (
                   SELECT 1 FROM ir_model_data e
                    WHERE e.module = 'account' AND e.name = d.name AND e.model = d.model
               )
        """,
        (MODULE,),
    )
    return cr.rowcount


def _drop_the_module_row(cr):
    # account absorbed it, so the module must not sit there `installed` naming code that
    # no longer exists, nor be offered for uninstall.
    cr.execute("DELETE FROM ir_model_data WHERE module = %s", (MODULE,))
    cr.execute("DELETE FROM ir_module_module_dependency WHERE name = %s", (MODULE,))
    cr.execute("DELETE FROM ir_module_module WHERE name = %s", (MODULE,))


def _rename_config_parameter(cr):
    cr.execute(
        """
            UPDATE ir_config_parameter SET key = 'account.bank_rec_payment_tolerance'
             WHERE key = 'account.bank_rec_payment_tolerance'
               AND NOT EXISTS (
                   SELECT 1 FROM ir_config_parameter
                    WHERE key = 'account.bank_rec_payment_tolerance'
               )
        """
    )


def migrate(cr, version):
    cr.execute("SELECT 1 FROM ir_module_module WHERE name = %s", (MODULE,))
    if not cr.rowcount:
        return
    _rename_then_repoint(cr)
    moved = _repoint_everything(cr)
    _rename_config_parameter(cr)
    _drop_the_module_row(cr)
    _logger.info("account_accountant folded into account: %s xmlids repointed", moved)
