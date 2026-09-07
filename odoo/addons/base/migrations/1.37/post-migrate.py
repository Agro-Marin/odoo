"""Post-migration: stored expressions still reading a contact's ``phone``.

``phone`` left ``res.partner``, and with it ``res.users`` and ``res.company``,
for ``phone_ids`` -- a number is now a record several contacts can share. An
expression that still reads ``.phone`` raises instead of returning an empty
string.

The refactor updated every XML source. What it could not update is the copies
already in the database: ``mail.template`` bodies and QWeb layouts are
``noupdate``, so no upgrade ever rewrites them. Because two of the affected
records are the standard notification layouts that wrap ordinary outgoing mail,
the symptom was not one broken feature but notification email failing to render
at all; the rest are the recruitment, event and portal-signup templates.

This lives in ``base`` rather than in each owning module because the field that
moved is ``base``'s, and each expression already says which record it reads, so
one pass fixes every module's copy without any of them depending on the others.

**Why a list of holders rather than a blanket rewrite of ``.phone``:**
``phone`` is still a live field on ``event.registration`` and on
``phone.blacklist.remove``, so rewriting the name wherever it appears would
corrupt those. Only expressions reading a partner, a user or a company are
rewritten, named here because SQL cannot resolve what the prefix refers to.

That makes this best-effort rather than exhaustive, which is why it is not the
guarantee: ``mail.tests.test_mail_template_references`` walks every stored
template against the live registry and fails on a reference this list missed.
It is what found the ``user_id`` and ``event_organizer`` holders below, after a
text search for the company ones had reported the database clean.
"""

from odoo.tools.module_data import rename_in_stored_expressions

# Expressions whose prefix resolves to a partner, a user or a company.
PHONE_HOLDERS = ("company", "company_id", "user_id", "event_organizer")
PRIMARY_NUMBER = "phone_ids._primary().number"


def migrate(cr, version):
    """Repoint stored expressions at the contact's phone records.

    :param cr: database cursor
    :param version: installed module version; falsy on a fresh install
    """
    if not version:
        return

    for holder in PHONE_HOLDERS:
        rename_in_stored_expressions(
            cr, f"{holder}.phone", f"{holder}.{PRIMARY_NUMBER}"
        )
