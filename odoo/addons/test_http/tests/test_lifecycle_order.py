"""Runtime proof of the request-lifecycle ordering the architecture front door
states (`doc/architecture/ARCHITECTURE.md`).

That page's "Request lifecycle (HTTP)" section makes three claims a source scan
cannot settle, because each is about *when* something happens rather than about
what the source contains:

1. ``retrying()`` commits, and the commit is the **last** thing it does once the
   callable returns -- ``_serve_db``'s ``finally`` only closes the cursor.
2. The session is written by ``Dispatcher.post_dispatch`` ->
   ``Request._save_session()``, and therefore **before** that commit.
3. A ``readonly`` route that writes runs its handler a **second** time.

``test_architecture_doc`` gates all three by grepping: it asserts
``env.cr.commit()`` appears in ``service/transaction.py``, that ``cr.commit()``
does *not* appear in ``http/_serve.py``, and that ``_save_session()`` appears in
``post_dispatch``'s body. Every one of those can hold while the *order* is wrong
-- move the commit above the dispatcher call and all three still pass. Ordering
is exactly the property a text search cannot see, which is the same argument
``mixin_coupling_check`` makes about ``self``-calls and ``env_surface_check``
about ``self.env``, applied to control flow.

Claim 3 is already covered behaviourally by
``TestHttpReadonlyPromotion``/``TestHttpRetryReplay`` in ``test_models.py``;
this module covers 1 and 2, which nothing observed.
"""

import threading
from unittest.mock import patch

import odoo
import odoo.tests.cursor
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.test_http.tests.test_common import TestHttpBase


@tagged("post_install", "-at_install")
class TestHttpLifecycleOrder(TestHttpBase):
    """Observe commit and session-save on the thread that served the request."""

    def setUp(self):
        super().setUp()
        self.events: list[tuple[int, str]] = []

    def _instrument(self):
        """Record ``(thread, event)`` for the two calls whose order is claimed.

        **Both cursor classes must be patched, and this is the trap.** Under
        ``HttpCase`` the request's ``env.cr`` is a :class:`odoo.tests.cursor.TestCursor`,
        which subclasses ``BaseCursor`` -- *not* ``Cursor`` -- and overrides
        ``commit()`` to close a savepoint instead of committing. Patching only
        ``odoo.db.cursor.Cursor.commit`` therefore records nothing on the serving
        thread, and the test reads as "``retrying()`` never commits" when what
        actually happened is that the harness substituted the cursor. That is a
        false negative pointing at the framework, which is the worst kind: the
        first version of this file hit it.

        ``retrying()``'s call site is ``env.cr.commit()`` either way, so the
        *ordering* being asserted is the real one; only the work the commit does
        differs between a served request and a test-served request.
        """
        events = self.events
        real_commit = odoo.db.cursor.Cursor.commit
        real_test_commit = odoo.tests.cursor.TestCursor.commit
        real_save = odoo.http.request_class.Request._save_session

        def commit(cr, *args, **kwargs):
            events.append((threading.get_ident(), "commit"))
            return real_commit(cr, *args, **kwargs)

        def test_commit(cr, *args, **kwargs):
            events.append((threading.get_ident(), "commit"))
            return real_test_commit(cr, *args, **kwargs)

        def save_session(request, *args, **kwargs):
            events.append((threading.get_ident(), "save_session"))
            return real_save(request, *args, **kwargs)

        return (
            patch.object(odoo.db.cursor.Cursor, "commit", commit),
            patch.object(odoo.tests.cursor.TestCursor, "commit", test_commit),
            patch.object(
                odoo.http.request_class.Request, "_save_session", save_session
            ),
        )

    def _serving_thread_events(self) -> list[str]:
        """The event sequence on whichever thread saved the session."""
        threads = {tid for tid, event in self.events if event == "save_session"}
        self.assertEqual(
            len(threads),
            1,
            f"expected exactly one serving thread, saw {len(threads)}",
        )
        (serving,) = threads
        return [event for tid, event in self.events if tid == serving]

    def test_session_is_saved_before_the_commit(self):
        """The page's ordering claim, observed rather than grepped."""
        self.authenticate("admin", "admin")
        milky_way = self.env.ref("test_http.milky_way")
        self.events.clear()

        commit_patch, test_commit_patch, save_patch = self._instrument()
        with commit_patch, test_commit_patch, save_patch:
            res = self.url_open(
                f"/test_http/{milky_way.id}/setname?readonly=0",
                {
                    "name": "Ordering Way",
                    "csrf_token": odoo.http.Request.csrf_token(self),
                },
            )
        res.raise_for_status()

        sequence = self._serving_thread_events()
        self.assertIn("save_session", sequence)
        self.assertIn(
            "commit",
            sequence,
            "the serving thread never committed; retrying() no longer commits",
        )
        self.assertLess(
            sequence.index("save_session"),
            sequence.index("commit"),
            f"the session must be saved before the commit, got {sequence}",
        )

    def test_commit_is_the_last_thing_on_the_serving_thread(self):
        """ "``env.cr.commit()`` is the last thing ``retrying()`` does."

        If ``_serve_db`` ever committed again in its ``finally``, or the
        dispatcher gained a post-commit hook that writes, this ordering would
        change and nothing else would notice.
        """
        self.authenticate("admin", "admin")
        milky_way = self.env.ref("test_http.milky_way")
        self.events.clear()

        commit_patch, test_commit_patch, save_patch = self._instrument()
        with commit_patch, test_commit_patch, save_patch:
            res = self.url_open(
                f"/test_http/{milky_way.id}/setname?readonly=0",
                {
                    "name": "Last Way",
                    "csrf_token": odoo.http.Request.csrf_token(self),
                },
            )
        res.raise_for_status()

        sequence = self._serving_thread_events()
        self.assertEqual(
            sequence[-1],
            "commit",
            f"something ran after retrying()'s commit, got {sequence}",
        )

    @mute_logger("odoo.http._serve")
    def test_promotion_reruns_the_handler_and_still_saves_before_committing(self):
        """The read-only path: two handler runs, and the ordering still holds.

        ``TestHttpReadonlyPromotion`` proves the double-run; what it does not
        show is that the *promoted* attempt keeps the documented order. A replay
        that committed before saving would lose the session of every request
        that took the promotion path.
        """
        self.authenticate("admin", "admin")
        milky_way = self.env.ref("test_http.milky_way")
        self.events.clear()

        commit_patch, test_commit_patch, save_patch = self._instrument()
        with commit_patch, test_commit_patch, save_patch:
            res = self.url_open(
                f"/test_http/{milky_way.id}/setname?readonly=1",
                {
                    "name": "Promoted Way",
                    "csrf_token": odoo.http.Request.csrf_token(self),
                },
            )
        res.raise_for_status()

        sequence = self._serving_thread_events()
        self.assertLess(
            sequence.index("save_session"),
            sequence.index("commit"),
            f"the promoted attempt committed before saving, got {sequence}",
        )
        self.assertEqual(sequence[-1], "commit", f"got {sequence}")

        milky_way.invalidate_recordset()
        self.assertEqual(milky_way.name, "Promoted Way")
