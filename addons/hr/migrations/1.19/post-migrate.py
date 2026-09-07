"""Post-migration: stored expressions still naming ``hr.employee.work_contact_id``.

An employee's contact is now ``partner_id``. ``work_contact_id`` is gone from
every model, but ``hr_payroll``'s payslip template still addressed its
recipient with ``object.employee_id.work_contact_id.id``.

That reference sat in ``partner_to``, not in the body, which is why it went
unnoticed longer than a broken body would: rendering a recipient that raises
does not report a template error to anyone reading mail, it just means the
payslip notification names nobody.

Rewritten as the qualified ``employee_id.work_contact_id`` rather than the bare
field name, so the pass needs no model scope and reaches the template whatever
model it is bound to -- here a ``hr.payslip``, not an ``hr.employee``.
"""

from odoo.tools.module_data import rename_in_stored_expressions

OLD = "employee_id.work_contact_id"
NEW = "employee_id.partner_id"


def migrate(cr, version):
    """Repoint stored expressions at the employee's contact.

    :param cr: database cursor
    :param version: installed module version; falsy on a fresh install
    """
    if not version:
        return

    rename_in_stored_expressions(cr, OLD, NEW)
