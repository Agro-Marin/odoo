"""Post-migration for the deadline_met type change repair (1.11).

``project.task.deadline_met`` changed from Boolean to Selection
(``met``/``missed``) without a data migration, so existing databases kept the
stringified boolean keys ``'true'``/``'false'`` in the varchar column. Those
are invalid selection values: the "Deadline Missed" filter matches nothing and
reports read garbage until each row happens to be recomputed.

Rewrite the legacy keys with the same tri-state logic as
``_compute_deadline_met``: closed tasks with a deadline become ``met`` or
``missed`` depending on ``date_closed``; everything else resets to NULL
(no deadline, or not yet closed).

Runs POST-migrate, not pre-migrate: on a database jumping straight from a
pre-``ead96a9906e9`` state to this version, ``deadline_met`` is still a
Postgres ``boolean`` column when pre-migrate scripts run — the ORM's schema
sync (which ``CAST``s it to varchar, producing the legacy ``'true'``/
``'false'`` text this script expects) only happens between pre- and
post-migrate. Running this as pre-migrate would crash the whole upgrade
with "invalid input syntax for type boolean: 'met'" on exactly the
databases that need the repair most.

Deliberately raw SQL rather than ``env.add_to_compute`` on the affected rows:
the CASE mirrors ``_compute_deadline_met`` (tri-state + CLOSED_STATES keys) at
the cost of a second copy of that logic, but a one-shot set-based UPDATE beats
an ORM recompute over a ~21k-row backlog mid-upgrade. If the compute's
definition of met/missed changes, update this CASE to match.

Idempotent: only legacy ``'true'``/``'false'`` rows are touched, and none
remain after the first run.
"""


def migrate(cr, version):
    cr.execute(
        """
        UPDATE project_task
           SET deadline_met = CASE
                   WHEN date_end IS NOT NULL
                        AND state IN ('done', 'canceled') THEN
                       CASE
                           WHEN date_closed IS NOT NULL
                                AND date_closed <= date_end THEN 'met'
                           ELSE 'missed'
                       END
                   ELSE NULL
               END
         WHERE deadline_met IN ('true', 'false')
        """
    )
