"""Post-migration: ``mail_template.model`` that never caught up with ``model_id``.

``model`` is a stored related on ``model_id.model``. A stored related is written
when the source changes, so a row whose ``model_id`` was repointed by an earlier
data load -- or whose source model was renamed underneath it -- keeps whatever
``model`` it had, and nothing recomputes it afterwards.

The two then disagree, and that is worse than a stale expression because it
raises nothing. ``mail.template`` renders against ``model``, so the template
browses one model using the other's ids and quietly reads whichever unrelated
records happen to carry those ids. Found on
``hr_appraisal.mail_template_appraisal_request_from_employee``, whose ``model``
still said ``res.users`` while ``model_id`` pointed at ``hr.appraisal``.

``model_id`` is the field of record: it is what the XML sets and what the form
edits, so it wins and ``model`` is rewritten from it, never the other way.

Idempotent, and a no-op wherever the two already agree.
"""


def migrate(cr, version):
    """Recompute the ``model`` column from ``model_id``.

    :param cr: database cursor
    :param version: installed module version; falsy on a fresh install
    """
    if not version:
        return

    cr.execute(
        """
        UPDATE mail_template t
           SET model = m.model
          FROM ir_model m
         WHERE m.id = t.model_id
           AND t.model IS DISTINCT FROM m.model
        """
    )
