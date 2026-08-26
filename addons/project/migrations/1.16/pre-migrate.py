def migrate(cr, version):
    if not version:
        return

    cr.execute(
        """
        UPDATE ir_filters
           SET domain  = replace(domain,  '''tasks''', '''task_ids'''),
               context = replace(context, '''tasks''', '''task_ids''')
         WHERE model_id = 'project.project'
           AND (domain LIKE '%''tasks''%' OR context LIKE '%''tasks''%')
        """
    )

    cr.execute(
        """
        UPDATE ir_exports_line l
           SET name = 'task_ids' || substring(l.name from 6)
          FROM ir_exports e
         WHERE e.id = l.export_id
           AND e.resource = 'project.project'
           AND (l.name = 'tasks' OR l.name LIKE 'tasks/%')
        """
    )

    cr.execute(
        """
        UPDATE ir_act_server a
           SET update_path = 'task_ids' || substring(a.update_path from 6)
          FROM ir_model m
         WHERE m.id = a.model_id
           AND m.model = 'project.project'
           AND (a.update_path = 'tasks' OR a.update_path LIKE 'tasks.%')
        """
    )
