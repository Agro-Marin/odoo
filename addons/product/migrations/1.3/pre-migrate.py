r"""Pre-migration for a method rename that shipped without one:
``product.template(.product).action_open_documents`` -> ``action_view_documents``
(commit 47bf4ebf5e71).

The button is invoked from view arch by name, and four modules that depend on
``product`` locate it to place their own buttons (``stock``, ``purchase``,
``sale``, ``mrp``). So the rename does not fail quietly at runtime the way an
unreferenced method would -- it takes the registry down during ``-u all``: the
parent form reloads with the new name while the children still hold the old
locator in ``ir_ui_view``, and combining them raises "Element
<button name='action_open_documents'> cannot be located in parent view".

Rewritten from ``product``'s pre-migrate, not from each child's, because this
runs before any of them reload: ``product`` is loaded first, so the stored
locators are already correct by the time its own views are validated.

Scoped to the two product models on purpose. ``documents_hr`` carries the same
rename on ``hr.employee`` and its own view is the only thing referencing it, so
it self-heals when that module reloads -- an unscoped whole-word sweep of this
token would reach across modules for no gain. Within that scope the ``\y``
(Postgres word boundary) form is still used, following
``stock/migrations/1.4/pre-migrate.py``, which fixed the identical
``action_open_reference`` -> ``action_view_reference`` lapse.
"""

_OLD = "action_open_documents"
_NEW = "action_view_documents"
_MODELS = ("product.template", "product.product")


def migrate(cr, version):
    """Rewrite stored references to the old method name on product models.

    :param cr: database cursor
    :param version: installed module version; falsy on a fresh install
    """
    if not version:
        return  # fresh install: nothing stored yet holds the old name

    cr.execute(
        rf"""
        UPDATE ir_ui_view
           SET arch_db = regexp_replace(
                   arch_db::text, '\y{_OLD}\y', '{_NEW}', 'g'
               )::jsonb
         WHERE model = ANY(%s)
           AND arch_db::text ~ '\y{_OLD}\y'
        """,
        (list(_MODELS),),
    )

    # Server actions on these models may call the button's method from their
    # Python code -- 15 exist on product models today, 5 of them invoking some
    # action_* method, so the surface is real rather than hypothetical.
    cr.execute(
        rf"""
        UPDATE ir_act_server s
           SET code = regexp_replace(s.code, '\y{_OLD}\y', '{_NEW}', 'g')
          FROM ir_model m
         WHERE m.id = s.model_id
           AND m.model = ANY(%s)
           AND s.code ~ '\y{_OLD}\y'
        """,
        (list(_MODELS),),
    )
