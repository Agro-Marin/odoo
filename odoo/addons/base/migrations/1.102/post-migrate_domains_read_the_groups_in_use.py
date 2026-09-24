"""An access domain reads the principal's groups as `group_ids`.

`user.all_group_ids` is every group the user holds anywhere; since grants can
be limited to some companies (authorization plan P2), the groups that count
are those held in the companies in use, which the evaluation context names
`group_ids`. The modules' own rows change with their files; this moves every
row the database holds, custom and noupdate ones included, and does nothing
on a second run.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        """
        UPDATE ir_access
           SET domain = replace(domain, 'user.all_group_ids.ids', 'group_ids')
         WHERE domain LIKE '%user.all_group_ids.ids%'
        """
    )
    _logger.info("base 1.102: %s access domains read the groups in use", cr.rowcount)
