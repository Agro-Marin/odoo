// @ts-check
/** @odoo-module native */

/** @module @web/core/py_js/py_errors */

/**
 * The interpreter's error type, in a leaf module of its own.
 *
 * It lives here rather than in ``py_builtin`` because ``py_args`` -- which
 * every ``PyDate``/``PyTimeDelta`` constructor calls -- needs nothing from
 * ``py_builtin`` but this class. Importing the whole module for it closed the
 * cycle ``py_date -> py_args -> py_builtin -> py_date``, and ``py_builtin``
 * reads the date classes while evaluating its own body (``BUILTINS.datetime``,
 * the temporal type-name table). Entering that cycle at ``py_date``,
 * ``py_timedelta`` or ``py_utils`` therefore threw "Cannot access 'PyDate'
 * before initialization" at load time; it only ever worked because the bundle
 * happened to reach ``py.js`` first.
 *
 * Re-exported by ``py_builtin`` for its established import path.
 */
export class EvaluationError extends Error {}
