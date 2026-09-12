def migrate(cr, version):
    if not version:
        return

    # `mixin_recurrence` is dissolved into `resource`, which now ships
    # `mixin.recurrence.rule`. The module held no data files and no security,
    # so the only rows naming it are its own module row, the `ir.model` entry
    # for the abstract model and the external ids pointing at them. Re-point
    # them rather than letting the loader orphan the model and drop the access
    # every consumer of the mixin resolves through it.
    cr.execute(
        """
        DELETE FROM ir_model_data dissolved
              USING ir_model_data surviving
              WHERE dissolved.module = 'mixin_recurrence'
                AND surviving.module = 'resource'
                AND surviving.name = dissolved.name
        """
    )
    cr.execute(
        """
        UPDATE ir_model_data
           SET module = 'resource'
         WHERE module = 'mixin_recurrence'
        """
    )
    cr.execute(
        """
        UPDATE ir_module_module
           SET state = 'uninstalled'
         WHERE name = 'mixin_recurrence'
           AND state NOT IN ('uninstalled', 'uninstallable')
        """
    )
    # A database that had `mixin_recurrence` installed reaches `resource` with
    # the dependency row still in place; left behind it makes the graph ask for
    # a module that no longer exists on disk.
    cr.execute(
        """
        DELETE FROM ir_module_module_dependency
         WHERE name = 'mixin_recurrence'
        """
    )
