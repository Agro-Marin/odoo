"""Contract tests: facts about our DEPENDENCIES that ``odoo.service`` branches on.

Every service-layer defect found in the audit that added these tests was an
assumption mismatch, not a logic error:

* ``InvalidCatalogName`` is an ``OperationalError``  -> false (psycopg)
* the dump scanner lexes arguments like ``psql``     -> false (psql)
* ``Popen`` closes the pipes it opened               -> false (subprocess)

The *logic* those assumptions feed is covered thoroughly, by hundreds of tests.
The assumptions themselves were covered by nothing, so each one sat wrong for as
long as it took someone to run the real dependency by hand.  ``retrying()``'s
SQLSTATE vocabulary already had such a guard
(``test_model.TestRetryVocabularyMatchesPostgres``) — these apply the same idea
to the places that actually broke.

The point is WHERE a future breakage surfaces.  Asserted here, a dependency
upgrade that changes one of these facts fails in a test that names the
assumption; asserted nowhere, it silently re-opens the defect several modules
downstream, on an unauthenticated code path.

This module holds the DB-free half.  The facts that need a live PostgreSQL,
``psql`` or ``pg_dump`` live in ``tests/contract/`` (separate invocation, see
that package's docstring).

Run with::

    python -m pytest tests/service/test_contracts.py -v
"""

import errno
import inspect
import os
import pathlib
import selectors
import signal
import subprocess
import sys
import threading
import time

import psycopg
import pytest

from odoo.db import PoolError
from odoo.service import common


class TestPsycopgConnectFailureHierarchy:
    """``exp_authenticate`` must catch everything the pool can raise on connect.

    ``odoo.db.pool`` deliberately translates a connect-phase failure into its
    precise SQLSTATE class (``_probe_connectable`` / ``_database_absent``, so an
    absent database fails fast in any server locale instead of burning the ~30s
    retry).  ``odoo.service.common`` then has to catch whatever that produces.

    It used to catch ``psycopg.OperationalError``, which reads as "every
    connection problem" and is not: the one that matters here —
    ``InvalidCatalogName``, "database does not exist" — descends from
    ``ProgrammingError``.  So an absent database escaped as an RPC error while an
    existing one returned ``False``: a per-name database existence oracle on an
    ``auth="none"`` verb (``/jsonrpc``, ``/xmlrpc/common``), measured against a
    live PG 18.4 cluster.
    """

    def test_invalid_catalog_name_is_not_an_operational_error(self):
        """The single fact the oracle turned on."""
        assert not issubclass(
            psycopg.errors.InvalidCatalogName, psycopg.OperationalError
        ), (
            "InvalidCatalogName is now an OperationalError. If psycopg really "
            "changed this, odoo.service.common's comments about WHY the catch "
            "is the broad psycopg.Error tree are stale and should be revisited."
        )

    def test_invalid_catalog_name_is_a_psycopg_error(self):
        """...and the fact the fix turns on: the broad catch does cover it."""
        assert issubclass(psycopg.errors.InvalidCatalogName, psycopg.Error)

    @pytest.mark.parametrize(
        "arm", ["OperationalError", "ProgrammingError", "IntegrityError", "DataError"]
    )
    def test_psycopg_error_is_the_common_root(self, arm):
        """``except psycopg.Error`` is only a sufficient catch if every arm of the
        hierarchy really descends from it — otherwise the uniform-answer
        invariant has a hole shaped like whichever arm does not."""
        assert issubclass(
            getattr(psycopg, arm, None) or getattr(psycopg.errors, arm), psycopg.Error
        )

    def test_pool_error_is_not_a_psycopg_error(self):
        """Why the catch is a 2-tuple and not just ``psycopg.Error``.

        ``odoo.db.PoolError`` is odoo's own class for pool saturation and
        wrapped connect failures. If it ever became a ``psycopg.Error``
        subclass, listing it separately would be harmless — but a reader would
        rightly wonder why, so pin the reason.
        """
        assert not issubclass(PoolError, psycopg.Error)

    def test_every_expected_connect_failure_is_actually_caught(self):
        """``_EXPECTED_CONNECT_FAILURES`` only selects the LOG LEVEL; it must be a
        subset of what the ``except`` clause catches, or a "routine" failure
        would escape the function entirely instead of being logged quietly."""
        for cls in common._EXPECTED_CONNECT_FAILURES:
            assert issubclass(cls, (psycopg.Error, PoolError)), (
                f"{cls.__name__} is treated as a routine connect failure but is "
                f"not caught by exp_authenticate's except clause"
            )


class TestSubprocessPipeOwnership:
    """``_run_pg_dump_streaming`` closes ``proc.stdout``/``proc.stderr`` itself
    because ``Popen`` does not, and refcounting only hides that on the success
    path.

    Both halves are stdlib behaviour, not ours, so both are pinned here: if a
    future CPython closed the pipes on ``wait()``, the explicit closes would
    become dead code, and this test is where that should surface.
    """

    def _run(self):
        return subprocess.Popen(
            [sys.executable, "-c", "import sys; sys.stdout.write('x')"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_popen_does_not_close_its_pipes_on_wait(self):
        proc = self._run()
        proc.wait()
        try:
            assert not proc.stdout.closed, "Popen.wait() now closes stdout"
            assert not proc.stderr.closed, "Popen.wait() now closes stderr"
        finally:
            proc.stdout.close()
            proc.stderr.close()

    def test_a_held_traceback_keeps_the_pipes_alive(self):
        """The mechanism that turns "just a ResourceWarning" into a real fd leak.

        On the failure path the raised exception's traceback pins the frame, and
        with it the ``Popen`` local — so the pipes survive for as long as the
        caller holds the error, which is exactly what ``_logger.exception`` and
        the HTTP error path do.  Measured pre-fix: 10 held errors, 10 retained
        pipe fds.
        """
        holder = {}

        def boom():
            proc = self._run()
            proc.wait()
            raise RuntimeError("failure path")

        try:
            boom()
        except RuntimeError as exc:
            holder["exc"] = exc

        frame = holder["exc"].__traceback__.tb_next.tb_frame
        proc = frame.f_locals["proc"]
        try:
            assert not proc.stdout.closed, (
                "a held traceback no longer keeps the frame's Popen alive; the "
                "fd-retention rationale in _run_pg_dump_streaming is stale"
            )
        finally:
            proc.stdout.close()
            proc.stderr.close()


class TestSignalsDoNotSurfaceAsEINTR:
    """PEP 475: a signal delivered mid-syscall no longer raises ``EINTR``.

    ``PreforkServer.sleep`` and the two ``Worker`` sleep loops used to carry
    ``except OSError as e: if e.args[0] != errno.EINTR: raise`` around
    ``select`` + ``empty_pipe`` + ``time.sleep``.  Since Python 3.5 the
    interpreter retries the syscall itself, so that branch was unreachable --
    and ``e.args[0]`` turns any ``OSError`` built with no arguments into a
    confusing ``IndexError`` instead.  The guards are gone; this is the
    assumption their removal rests on.
    """

    def _drain(self, fd):
        while True:
            try:
                if not os.read(fd, 4096):
                    return
            except BlockingIOError:
                return

    def test_select_read_and_sleep_survive_a_signal_storm(self):
        handled = 0

        def handler(*_args):
            nonlocal handled
            handled += 1

        previous = signal.signal(signal.SIGUSR1, handler)
        read_fd, write_fd = os.pipe()
        os.set_blocking(read_fd, False)
        selector = selectors.DefaultSelector()
        selector.register(read_fd, selectors.EVENT_READ)
        target = os.getpid()
        stop = threading.Event()

        def bombard():
            for _ in range(20):
                if stop.wait(0.02):
                    return
                os.kill(target, signal.SIGUSR1)

        sender = threading.Thread(target=bombard, daemon=True)
        sender.start()
        try:
            for _ in range(20):
                # No try/except: an EINTR here would fail the test, which is
                # the point.
                selector.select(0.2)
                self._drain(read_fd)
                time.sleep(0.01)
        finally:
            stop.set()
            sender.join(timeout=2)
            selector.close()
            os.close(read_fd)
            os.close(write_fd)
            signal.signal(signal.SIGUSR1, previous)

        assert handled, "no signal was delivered; the test proved nothing"

    def test_an_argless_oserror_has_no_args_but_does_have_errno(self):
        """Why ``e.errno`` and never ``e.args[0]``: the removed guards would
        have raised ``IndexError`` from inside an exception handler."""
        with pytest.raises(IndexError):
            OSError().args[0]
        assert OSError().errno is None


@pytest.mark.skipif(
    __import__("odoo.service._watcher", fromlist=["inotify"]).inotify is None,
    reason="inotify backend not installed",
)
class TestInotifyPrivateSurface:
    """``_InotifyInternals`` reaches into four private names of the ``inotify``
    package, two of them name-mangled.

    Recovery from ``IN_Q_OVERFLOW`` is built on them, and it is the path that
    only runs when the kernel queue has already overrun -- i.e. never in a normal
    development session, and exactly once during a branch switch, when a
    developer is least likely to read a warning carefully. A rename in a minor
    release of the library would break it at a distance.

    ``requirements-dev.txt`` pins ``inotify==0.2.12``. A pin holds the surface
    still; it does not say anything when someone lifts it. This does: these
    assertions fail in CI on the upgrade commit, naming the attribute that moved,
    rather than leaving a server that has quietly stopped noticing edits.
    """

    def _trees(self, tmp_path):
        from odoo.service._watcher import INOTIFY_LISTEN_EVENTS, InotifyTrees

        try:
            return InotifyTrees(
                [str(tmp_path)], mask=INOTIFY_LISTEN_EVENTS, block_duration_s=0.05
            )
        except OSError as exc:
            if exc.errno != errno.ENOSPC:
                raise
            # Per-USER inotify cap, shared with every editor and test run on the
            # box; not a property of this checkout.
            pytest.skip(str(exc))

    def test_inotify_trees_still_exposes_i_and_mask(self, tmp_path):
        trees = self._trees(tmp_path)
        assert hasattr(trees, "_i"), "InotifyTrees._i moved"
        assert hasattr(trees, "_mask"), "InotifyTrees._mask moved"

    def test_the_watch_descriptor_map_is_still_name_mangled_watches_r(self, tmp_path):
        trees = self._trees(tmp_path)
        mapping = getattr(trees._i, "_Inotify__watches_r", None)
        assert isinstance(mapping, dict), "Inotify.__watches_r moved or changed type"

    def test_remove_watch_still_takes_superficial(self, tmp_path):
        """``superficial=True`` is what lets a stale descriptor be dropped
        without an ``inotify_rm_watch`` the kernel would refuse."""
        trees = self._trees(tmp_path)
        parameters = inspect.signature(trees._i.remove_watch).parameters
        assert "superficial" in parameters, "Inotify.remove_watch signature changed"
        assert parameters["superficial"].default is False

    def test_the_adapter_is_the_only_place_that_reaches_in(self):
        """Structural: the private spellings must not creep back out into the
        watcher body, or this contract test stops covering them."""
        from odoo.service import _watcher

        source = pathlib.Path(_watcher.__file__).read_text(encoding="utf-8")
        body = source.split("class _InotifyInternals", 1)[1]
        after_adapter = body.split("class FSWatcherInotify", 1)[1]
        for spelling in ("_Inotify__watches_r", "._i", "._mask"):
            assert spelling not in after_adapter, (
                f"{spelling} is reached outside _InotifyInternals again"
            )
