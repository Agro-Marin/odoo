OLD_MODULE = "document_enterprise"
NEW_MODULE = "document"


def _module_state(cr, name):
    cr.execute("SELECT state FROM ir_module_module WHERE name = %s", [name])
    row = cr.fetchone()
    return row[0] if row else None


def migrate(cr, version):
    # document_enterprise is folded into document: every record it declared
    # (wizard views, ACLs, rules, the share mail template, the digest tip, the
    # tour) is now document's own, so its ir_model_data rows move to document's
    # namespace and the module row is closed so nothing tries to load a
    # directory that is no longer on disk. Model and field reflection rows move
    # with the rest; the ORM re-reflects them under document on this upgrade.
    if _module_state(cr, OLD_MODULE) is None:
        return
    cr.execute(
        """
        UPDATE ir_model_data d
           SET module = %s
         WHERE d.module = %s
           AND NOT EXISTS (
               SELECT 1 FROM ir_model_data p
                WHERE p.module = %s AND p.name = d.name
           )
        """,
        [NEW_MODULE, OLD_MODULE, NEW_MODULE],
    )
    cr.execute("DELETE FROM ir_model_data WHERE module = %s", [OLD_MODULE])
    cr.execute(
        """
        UPDATE ir_model_constraint c SET module = t.id
          FROM ir_module_module t, ir_module_module f
         WHERE t.name = %s AND f.name = %s AND c.module = f.id
        """,
        [NEW_MODULE, OLD_MODULE],
    )
    cr.execute(
        """
        UPDATE ir_model_relation r SET module = t.id
          FROM ir_module_module t, ir_module_module f
         WHERE t.name = %s AND f.name = %s AND r.module = f.id
        """,
        [NEW_MODULE, OLD_MODULE],
    )
    cr.execute(
        """
        DELETE FROM ir_module_module_dependency
         WHERE module_id IN (SELECT id FROM ir_module_module WHERE name = %s)
            OR name = %s
        """,
        [OLD_MODULE, OLD_MODULE],
    )
    cr.execute(
        "UPDATE ir_module_module SET state = 'uninstalled' WHERE name = %s",
        [OLD_MODULE],
    )
