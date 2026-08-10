"""Install hooks for api_transport.

This module *is* ``agromarin/api_communication``, relocated into the core fork so
that odoo/ and enterprise/ modules can depend on it, and renamed to say what it
is. A database that already has ``api_communication`` installed must therefore be
taken over rather than have a second copy installed alongside it.

What has to happen before anything else loads, and why:

* **The module row.** The *old* row is marked ``uninstalled``; the new one is
  left strictly alone. Without this both modules sit installed declaring the same
  models. Renaming the old row into the new one is the obvious move and is wrong:
  Odoo is mid-install on api_transport's row and holds a reference to it, so
  deleting it kills the load with ``MissingError``. Marking the old row drops no
  data — the tables stay and ownership transfers through the ir_model_data
  re-tag.
* **Every ir_model_data row.** All 404 of them on a production restore. Field,
  model, constraint and inherit rows (~358) would self-heal through reflection,
  but the rest would not, and the two failure modes differ: ``noupdate`` records
  are exempt from the orphan sweep and instead abort the load on a UNIQUE
  constraint, while views, menus, actions, ACLs and rules are swept — deleted and
  re-created with new ids, orphaning anything holding the old one. Re-tagging all
  of them is simpler than reasoning about which is which, and strictly safer.
* **Two xml ids embed the old module name** and are remapped by name as well as
  by module, so ``marin``'s reference to the privilege keeps resolving.
* **The system-parameter keys.** The seven ``api_communication.*`` parameters are
  renamed in place rather than re-seeded, because an administrator may have tuned
  them and a fresh seed would silently reinstate the shipped defaults.

Odoo builds the module graph before this hook runs, so it still loads the module
in ``init`` mode (see ``odoo/modules/loading.py``), where ``noupdate="1"`` does
**not** suppress writes. Renaming the parameter rows here is therefore necessary
but not sufficient — the data load then puts the shipped default straight over
the renamed row. Measured: a ``log_retention_days`` tuned to 999 came back as 90.
So the values are stashed here and restored by ``post_init_hook``, which is the
only place that runs after the data load.

``pre_init_hook`` rather than a migration script: to this database api_transport
is a new module being *installed*, and migration scripts do not run on install.
"""

import logging

_logger = logging.getLogger(__name__)

_OLD = "api_communication"
_NEW = "api_transport"

# xml ids whose *name* also changed, not just the module prefix.
_RENAMED_XMLIDS = {
    "module_category_api_communication": "module_category_api_transport",
    "res_groups_privilege_api_communication": "res_groups_privilege_api_transport",
}

_PARAM_SUFFIXES = [
    "retry_batch_size",
    "retry_processing_timeout",
    "log_retention_days",
    "max_cache_entries",
    "max_payload_size_limit",
    "max_duplicate_window_seconds",
    "timestamp_future_tolerance",
    "allow_none_signature",
]


def _takeover_module_row(env) -> bool:
    """Rename the installed api_communication module row to this module.

    :param env: Odoo environment
    :return: True when a takeover happened (an old install was present)
    :rtype: bool
    """
    # Guard on *state*, not on the row existing. While the old directory is
    # still on the addons path Odoo creates an `uninstalled` row for it on every
    # database, so "a row exists" is not evidence of anything to take over —
    # acting on it deleted the row this very install was using and the load died
    # with MissingError out of ir_module._compute_description_html.
    # `state <> ALL(%s)` with a list, not `NOT IN %s` with a tuple: this fork
    # runs psycopg 3, where the latter is a syntax error at parameter binding.
    env.cr.execute(
        "SELECT state FROM ir_module_module WHERE name = %s AND state <> ALL(%s)",
        (_OLD, ["uninstalled", "uninstallable", "to remove"]),
    )
    row = env.cr.fetchone()
    if not row:
        return False  # fresh database, or the old module was never installed

    # Retire the OLD row; never touch the new one. Odoo is mid-install on
    # api_transport's own row and holds a reference to it, so deleting or
    # renaming into it breaks the load the same way acting on an uninstalled old
    # row did. Marking the old row `uninstalled` drops no data — the tables and
    # rows stay exactly where they are and this module now owns them through the
    # ir_model_data re-tag below. It is not `to remove`, which would schedule a
    # real uninstall and run the old module's uninstall_hook.
    env.cr.execute(
        "UPDATE ir_module_module SET state = 'uninstalled' WHERE name = %s",
        (_OLD,),
    )
    _logger.info(
        "api_transport: taking over %s (was state=%s); its records are being "
        "re-tagged to this module and its tables are left untouched",
        _OLD,
        row[0],
    )
    return True


def _retag_model_data(env) -> None:
    """Re-point every ir_model_data row from the old module to this one.

    :param env: Odoo environment
    """
    for old_name, new_name in _RENAMED_XMLIDS.items():
        env.cr.execute(
            "UPDATE ir_model_data SET module = %s, name = %s "
            "WHERE module = %s AND name = %s",
            (_NEW, new_name, _OLD, old_name),
        )
        if env.cr.rowcount:
            _logger.info(
                "api_transport: %s.%s -> %s.%s", _OLD, old_name, _NEW, new_name
            )

    env.cr.execute(
        "UPDATE ir_model_data SET module = %s WHERE module = %s", (_NEW, _OLD)
    )
    if env.cr.rowcount:
        _logger.info(
            "api_transport: re-tagged %s ir_model_data row(s) from %s",
            env.cr.rowcount,
            _OLD,
        )


_BACKUP_TABLE = "api_transport_param_takeover"


def _rename_config_parameters(env) -> None:
    """Rename the module's system parameters and stash their current values.

    Renaming the row carries the administrator's value across to the new key.
    That is necessary but **not sufficient**: the graph was built before this
    hook ran, so Odoo loads this module in ``init`` mode, where ``noupdate="1"``
    does not suppress writes — ``data/ir_config_parameter_data.xml`` then puts
    the shipped default straight over the renamed row. Measured: a
    ``log_retention_days`` tuned to 999 came back as 90.

    So the values are also stashed in a real table (not TEMP: the hooks do not
    share a session) for :func:`post_init_hook` to put back after the data load.

    :param env: Odoo environment
    """
    for suffix in _PARAM_SUFFIXES:
        env.cr.execute(
            """
            UPDATE ir_config_parameter
               SET key = %(new)s
             WHERE key = %(old)s
               AND NOT EXISTS (
                     SELECT 1 FROM ir_config_parameter WHERE key = %(new)s
                   )
            """,
            {"new": f"{_NEW}.{suffix}", "old": f"{_OLD}.{suffix}"},
        )
        if env.cr.rowcount:
            _logger.info(
                "api_transport: carried %s.%s over to %s.%s",
                _OLD,
                suffix,
                _NEW,
                suffix,
            )

    env.cr.execute(
        f"CREATE TABLE IF NOT EXISTS {_BACKUP_TABLE} "
        "(key varchar PRIMARY KEY, value text)"
    )
    env.cr.execute(
        f"INSERT INTO {_BACKUP_TABLE} (key, value) "
        "SELECT key, value FROM ir_config_parameter WHERE key = ANY(%s) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
        ([f"{_NEW}.{s}" for s in _PARAM_SUFFIXES],),
    )
    if env.cr.rowcount:
        _logger.info(
            "api_transport: stashed %s system parameter value(s) for post_init "
            "to restore after the init-mode data load overwrites them",
            env.cr.rowcount,
        )


def pre_init_hook(env):
    """Take over an installed api_communication, if there is one.

    Every step is a no-op on a database that never had it, so a fresh install
    runs through this untouched.

    :param env: Odoo environment
    """
    if not _takeover_module_row(env):
        return
    _retag_model_data(env)
    _rename_config_parameters(env)


def post_init_hook(env):
    """Restore system parameter values the init-mode data load overwrote.

    Only does anything when :func:`pre_init_hook` stashed values, i.e. on a
    takeover; a fresh install has no backup table and returns immediately.

    ``flush_all`` first: ``load_data`` writes through the ORM, so the shipped
    default can still be sitting in the cache with the old value in the
    database — a raw UPDATE would compare against the un-overwritten row, find
    nothing to change, and then lose to the pending flush. ``invalidate_all``
    afterwards so nothing serves the default from cache.

    :param env: Odoo environment
    """
    env.cr.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = %s",
        (_BACKUP_TABLE,),
    )
    if not env.cr.fetchone():
        return

    env.flush_all()
    env.cr.execute(
        f"""
        UPDATE ir_config_parameter p
           SET value = b.value
          FROM {_BACKUP_TABLE} b
         WHERE p.key = b.key
           AND p.value IS DISTINCT FROM b.value
        """
    )
    restored = env.cr.rowcount
    env.cr.execute(f"DROP TABLE {_BACKUP_TABLE}")
    env.invalidate_all()

    if restored:
        _logger.info(
            "api_transport: restored %s system parameter value(s) that the "
            "init-mode data load had reset to shipped defaults",
            restored,
        )
