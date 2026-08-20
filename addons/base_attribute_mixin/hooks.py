import logging

from odoo import api

_logger = logging.getLogger(__name__)

# The module this one was renamed from. Its records are adopted rather than
# left behind; see pre_init_hook.
_RENAMED_FROM = "base_attribute"


def adopt_renamed_module(cr) -> int:
    """Take over everything the pre-rename ``base_attribute`` module owned.

    This module started life as ``base_attribute`` in the agromarin tree and
    was renamed on the way into core. A database that installed the old name
    still has an ``ir_module_module`` row for it, ``ir_model_data`` rows owning
    the three mixins' fields and constraints, and dependency rows naming it --
    while the module itself no longer exists on disk.

    Left alone that is not merely untidy. The orphaned rows own
    ``ir.model.fields`` records for ``mixin.attribute`` and friends, so the day
    anyone uninstalls the ghost -- or a module-list refresh decides to reap it
    -- those fields are unlinked and their columns go with them, on models this
    module is now responsible for.

    Three moves, in this order:

    1. ``ir_model_data`` rows change module, so the records they own become
       ours. Any row already under our own name is dropped first: at
       pre-init this module has loaded nothing, so such a row can only be a
       leftover from an earlier attempt, and it would otherwise collide with
       the unique ``(module, name)`` index.
    2. Dependency rows naming the old module are repointed, so consumers'
       declared graph matches the one on disk.
    3. The ghost row is marked ``uninstalled`` rather than deleted, which
       leaves an auditable trace. By then it owns nothing, so retiring it
       cannot cascade into a record.

    Idempotent, and a no-op on a database that never had the old name.

    :param cr: database cursor
    :return: number of ``ir_model_data`` rows adopted
    """
    cr.execute(
        "SELECT 1 FROM ir_module_module WHERE name = %s AND state != 'uninstalled'",
        (_RENAMED_FROM,),
    )
    if not cr.fetchone():
        return 0

    cr.execute(
        """
        DELETE FROM ir_model_data
         WHERE module = 'base_attribute_mixin'
           AND name IN (SELECT name FROM ir_model_data WHERE module = %s)
        """,
        (_RENAMED_FROM,),
    )
    cr.execute(
        "UPDATE ir_model_data SET module = 'base_attribute_mixin' WHERE module = %s",
        (_RENAMED_FROM,),
    )
    adopted = cr.rowcount

    cr.execute(
        "UPDATE ir_module_module_dependency SET name = 'base_attribute_mixin' "
        "WHERE name = %s",
        (_RENAMED_FROM,),
    )
    repointed = cr.rowcount

    cr.execute(
        "UPDATE ir_module_module SET state = 'uninstalled' WHERE name = %s",
        (_RENAMED_FROM,),
    )

    _logger.info(
        "base_attribute_mixin: adopted %s record(s) and %s dependency row(s) "
        "from the pre-rename %s module, which is now retired",
        adopted,
        repointed,
        _RENAMED_FROM,
    )
    return adopted


def pre_init_hook(env: api.Environment) -> None:
    """Adopt the pre-rename module's records before this one loads.

    It has to be a hook rather than a migration: a database carrying the old
    name *installs* this module rather than upgrading it, and migration scripts
    do not run on install.

    :param env: Odoo environment (pre-load: this module's models are not in the
        registry yet, so only raw ``ir_model_data`` SQL is used).
    """
    adopt_renamed_module(env.cr)
