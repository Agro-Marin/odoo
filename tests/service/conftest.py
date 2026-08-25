"""Shared fixtures and process-hygiene guards for the service suite.

This suite is process-free but NOT state-free: the code under test reaches for
module globals (``lifecycle.server``), thread-local attributes
(``rpc_model_method``, the thread NAME) and ``odoo.tools.config``.  A test that
leaves any of those altered silently changes the meaning of every test that
runs after it, and the failure surfaces somewhere else entirely.

That is not hypothetical.  ``lifecycle.start()`` assigns ``lifecycle.server``
itself, so ``patch`` never restored it, and the MagicMock left behind made four
``test_metrics`` exposition tests unparseable — hidden only because alphabetical
collection happens to put ``test_metrics`` before ``test_server``.  Reversing the
order, or shuffling it, failed in bulk.

:func:`_no_global_state_leak` closes that class of bug at the source: it FAILS
the test that leaks rather than the innocent test downstream.  Add a name here
when a new piece of process-global state joins the suite.
"""

import os
import random
import threading

import pytest

SHUFFLE_SEED_VAR = "ODOO_SERVICE_TEST_SHUFFLE_SEED"


def pytest_collection_modifyitems(session, config, items):
    """Shuffle this suite when ``ODOO_SERVICE_TEST_SHUFFLE_SEED`` is set.

    Order-dependence here is not theoretical — two independent instances shipped
    and were only masked by alphabetical collection.  One made four
    ``test_metrics`` tests depend on ``test_server`` not having run yet; the
    other made ``test_model``'s ``patch("odoo.http")`` depend on an earlier test
    having triggered a lazy import, so selecting a single test from that file
    failed outright.

    Opt-in via env var rather than always-on, and seeded rather than random, so a
    CI failure names a seed that reproduces it exactly.  ``pytest-randomly``
    would cover this, but it is process-global and this repo's other tiers have
    not been audited for order-independence — scoping the shuffle to the suite
    that HAS been audited keeps the signal trustworthy.
    """
    raw = os.environ.get(SHUFFLE_SEED_VAR)
    if not raw:
        return
    try:
        seed = int(raw)
    except ValueError:
        seed = abs(hash(raw)) % (2**32)
    random.Random(seed).shuffle(items)


def pytest_report_header(config):
    """Put the shuffle seed in the header so a CI failure is reproducible."""
    raw = os.environ.get(SHUFFLE_SEED_VAR)
    if raw:
        return f"service suite: collection shuffled with {SHUFFLE_SEED_VAR}={raw}"
    return None


@pytest.fixture(autouse=True)
def _no_global_state_leak():
    """Fail the test that leaves process-global state altered.

    Deliberately a post-condition on the CULPRIT rather than a restore: silently
    putting the value back would keep the suite green while leaving a test that
    mutates a global it does not own — which is a defect in the test whether or
    not anything currently trips over it.  The message names the leak so the fix
    (usually adding it to the test's own ``patch`` list) is obvious.

    Scope is deliberately narrow: cheap-to-read state that the suite has already
    been bitten by.  Threads are excluded on purpose — several tests legitimately
    leave a bounded stderr-drain thread behind, so watching them would mean
    encoding exceptions here instead of catching real leaks.

    A guard is only armed if nothing downstream disarms it.  ``test_server.py``
    used to install an ``autouse`` fixture that restored ``rpc_model_method``
    for all 266 of its tests; conftest fixtures are OUTER, so that restore tore
    down first and this check could never observe a leak in the suite's largest
    file — where one (the ``log_handler`` fixture) was in fact live.  Tests that
    genuinely own one of these names must say so with ``monkeypatch``, per the
    message below, never with a blanket restore.
    """
    from odoo.service import lifecycle

    thread = threading.current_thread()
    missing = object()

    def snapshot():
        return {
            "lifecycle.server": lifecycle.server,
            "lifecycle.server_phoenix": lifecycle.server_phoenix,
            "current_thread().name": thread.name,
            "current_thread().rpc_model_method": getattr(
                thread, "rpc_model_method", missing
            ),
            # Stamped by ``_listen_thread`` on whichever thread drives it (the
            # MainThread, under pytest) and read by ``ThreadedServer.process_limit``
            # to decide a thread is over its time limit.  Leaked, it makes every
            # later reader see a permanently over-limit thread.
            "current_thread().start_time": getattr(thread, "start_time", missing),
            # Read by ``_metrics.service_metrics`` to bucket live threads by
            # kind.  A test that stamps it and does not restore it makes every
            # later ``service_metrics()`` count the MainThread as an http
            # worker.  It was being save/restored by hand in ``test_metrics``,
            # which is the spelling the message below argues against.
            "current_thread().type": getattr(thread, "type", missing),
        }

    before = snapshot()
    # ``model._PUBLIC_METHOD_CACHE`` is keyed by CLASS OBJECT, so a test that
    # resolves a method on a locally-defined class pins that class for the life
    # of the process.  Watching the key set (not the contents) catches the leak
    # without objecting to the legitimate warm-up every RPC test performs on the
    # models it shares.
    from odoo.service import model as _model_mod

    classes_before = set(_model_mod._PUBLIC_METHOD_CACHE)

    yield

    after = snapshot()
    strays = set(_model_mod._PUBLIC_METHOD_CACHE) - classes_before
    if strays:
        pytest.fail(
            "this test left classes in odoo.service.model._PUBLIC_METHOD_CACHE, "
            "which is keyed by class object and never evicted:\n"
            + "\n".join(f"  {c!r}" for c in strays)
            + "\nPop them in a fixture teardown, as TestGetPublicMethodCache does.",
            pytrace=False,
        )
    leaked = {k: (before[k], after[k]) for k in before if before[k] is not after[k]}
    # `is not` above catches identity changes; fall back to equality so an equal
    # but freshly-built value (a new str with the same text) is not a false positive.
    leaked = {k: v for k, v in leaked.items() if v[0] != v[1]}
    if leaked:
        detail = "\n".join(
            f"  {name}: {old!r} -> {new!r}" for name, (old, new) in leaked.items()
        )
        pytest.fail(
            "this test left process-global state altered, which changes the "
            "meaning of every test that runs after it:\n"
            f"{detail}\n"
            "Restore it — usually by adding the name to this test's own patch "
            "list, so `patch` owns the teardown.",
            pytrace=False,
        )


def fake_pg_cursor(*, fetchone=None, fetchone_sequence=None, fetchall=(), execute=None):
    """A ``MagicMock`` cursor that is safe as BOTH a context manager and a value.

    ``odoo.service.db`` opens its maintenance cursor two different ways —
    ``with db.cursor() as cr`` and ``closing(db.cursor())``, the latter yielding
    the cursor object itself — so a stand-in has to satisfy both.  Hand-rolled
    versions of this appear a dozen times across the suite and disagree about
    which: some set ``__enter__``/``__exit__``, some set only
    ``cursor.return_value``, one sets both and then overwrites it.

    ``fetchone_sequence`` answers successive reads in order, for the callers that
    make several — ``_warn_on_connection_budget`` reads three settings, the
    faketime check reads two clocks.  Without it those sites had to hand-roll the
    whole cursor, which is how the copies below drifted apart in the first place.

    ``fetchone`` defaults to ``None`` — "no row" — and that default is the point.
    A bare ``MagicMock().fetchone()`` returns a MagicMock, which is TRUTHY, so a
    stray ``if cr.fetchone():`` in the code under test silently takes the
    row-exists branch.  That is precisely what turned a real ``_create_empty_database``
    defect into three tests failing with a baffling ``DatabaseExists`` instead of
    a clean signal.
    """
    from unittest.mock import MagicMock

    cr = MagicMock()
    if fetchone_sequence is not None:
        cr.fetchone.side_effect = list(fetchone_sequence)
    else:
        cr.fetchone.return_value = fetchone
    cr.fetchall.return_value = fetchall
    if execute is not None:
        cr.execute.side_effect = execute
    cr.__enter__ = MagicMock(return_value=cr)
    cr.__exit__ = MagicMock(return_value=False)
    return cr


def fake_pg_connection(cursor=None, **cursor_kwargs):
    """A connection whose ``cursor()`` yields :func:`fake_pg_cursor` both ways.

    Returns ``(connection, cursor)`` so a test can assert on the statements the
    cursor saw without reaching back through the mock chain.
    """
    from unittest.mock import MagicMock

    cr = cursor if cursor is not None else fake_pg_cursor(**cursor_kwargs)
    conn = MagicMock()
    conn.cursor.return_value = cr
    return conn, cr


def retrying_env(*, on_commit=None, closed=False):
    """A minimal ``Environment`` stand-in for ``odoo.service.transaction.retrying``.

    ``retrying`` reads a narrow, fixed set of attributes off the env and its
    cursor — ``cr.closed``, ``cr.commit_count``, ``flush``/``commit``/``rollback``,
    ``transaction.reset``, ``registry.reset_changes``/``signal_changes``/``values``
    and ``env._`` — and every one of them has to be present or the call fails for
    a reason unrelated to the test.  Four hand-built copies of that block existed
    (three in ``test_retrying_postcommit``, one in ``test_model``), differing only
    in what ``commit`` does.

    ``on_commit`` receives the env, so a caller expresses just the difference:

        retrying_env()                                    # a clean commit
        retrying_env(on_commit=_durable_then_raise)       # COMMIT landed, a hook blew up
        retrying_env(on_commit=_durable_then_close)       # COMMIT landed, a hook closed cr
        retrying_env(closed=True)                         # cursor already back in the pool

    ``commit_count`` is what tells a failed COMMIT from a committed one whose
    post-commit hook raised, so a stand-in that starts it anywhere but 0 — or
    forgets to bump it — inverts the branch under test.  Real cursors carry it
    from ``BaseCursor.__init__``.
    """
    from unittest.mock import MagicMock

    env = MagicMock()
    env.cr._closed = closed
    env.cr.closed = closed
    env.cr.flush = MagicMock()
    env.cr.rollback = MagicMock()
    env.cr.commit_count = 0
    env.cr.commit = MagicMock(
        side_effect=(lambda: on_commit(env)) if on_commit is not None else None
    )
    env.transaction.reset = MagicMock()
    env.registry.reset_changes = MagicMock()
    env.registry.signal_changes = MagicMock()
    env.registry.values.return_value = []
    env._.side_effect = lambda tmpl, *args: tmpl % args if args else tmpl
    return env


def durable_then_raise(exc=None):
    """``commit`` side effect: the SQL COMMIT lands, then a hook raises."""
    error = exc if exc is not None else RuntimeError("post-commit hook failed")

    def _commit(env):
        env.cr.commit_count += 1  # the transaction is now durable
        raise error

    return _commit


def durable_then_close(env):
    """``commit`` side effect: the SQL COMMIT lands, then a hook closes the cursor.

    Returns normally — which is the whole point.  ``retrying``'s last line is
    ``if not env.cr.closed: env.registry.signal_changes()``, so a hook that closes
    the cursor WITHOUT raising skips the announcement for a transaction that is
    already durable.
    """
    env.cr.commit_count += 1
    env.cr.closed = True
