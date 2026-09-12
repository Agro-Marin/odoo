def migrate(cr, version):
    """Drop the wizard rows the model left behind when it was transient.

    `base.module.install.request` becomes a persistent record that carries an
    approval request. What sits in its table today are dialog leftovers the
    transient vacuum had not reached yet: none of them was ever asked of anybody,
    so none of them becomes a request.
    """
    if not version:
        return
    cr.execute("DELETE FROM base_module_install_request")
