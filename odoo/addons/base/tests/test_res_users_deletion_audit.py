from unittest.mock import patch

from odoo.tests.common import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestResUsersDeletionBatch(TransactionCase):
    """RUD-T1: _gc_portal_users batch_size slicing and lock-skip contract.

    The cron-drain must process at most `batch_size` queued deletions per run
    (leaving the rest `todo`), and must skip a request already flipped out of
    `todo` by a concurrent run without re-processing or erroring.
    """

    def _queue_portal_user(self, login):
        user = new_test_user(self.env, login=login, groups="base.group_portal")
        request = self.env["res.users.deletion"].create(
            {"user_id": user.id, "state": "todo"}
        )
        return user, request

    @mute_logger("odoo.addons.base.models.res_users_deletion")
    def test_batch_size_limits_users_processed_per_run(self):
        Deletion = self.env["res.users.deletion"]
        requests = self.env["res.users.deletion"]
        for i in range(3):
            _user, req = self._queue_portal_user(f"rud_batch_{i}")
            requests |= req

        # Neutralise _commit_progress: no real commit in a test transaction, and
        # a positive return keeps the loop going (mirrors the non-cron path which
        # returns inf). This isolates the batch_size slicing logic.
        with patch.object(
            self.env["ir.cron"].__class__,
            "_commit_progress",
            lambda self, *a, **k: float("inf"),
        ):
            Deletion._gc_portal_users(batch_size=2)

        states = requests.mapped("state")
        self.assertEqual(
            states.count("done"),
            2,
            "exactly batch_size (2) requests must be processed per run (RUD-T1)",
        )
        self.assertEqual(
            states.count("todo"),
            1,
            "the request beyond batch_size must remain todo for the next run",
        )

    @mute_logger("odoo.addons.base.models.res_users_deletion")
    def test_request_already_out_of_todo_is_skipped(self):
        Deletion = self.env["res.users.deletion"]
        _user, request = self._queue_portal_user("rud_skip")
        # Simulate a concurrent run having already finished this request.
        request.state = "done"

        with patch.object(
            self.env["ir.cron"].__class__,
            "_commit_progress",
            lambda self, *a, **k: float("inf"),
        ):
            # search([state=todo]) excludes it, so it is never re-processed and
            # the run completes without error.
            Deletion._gc_portal_users(batch_size=50)

        self.assertEqual(request.state, "done", "a non-todo request must be left as-is")


@tagged("post_install", "-at_install")
class TestResUsersDeletionUserIdInt(TransactionCase):
    """RUD-L1: res.users.deletion.user_id_int must retain the original user id
    after the user is deleted (user_id is ondelete='set null'), since it is the
    only remaining trace of which user the deletion request was for.
    """

    def test_user_id_int_preserved_after_user_deletion(self):
        user = new_test_user(
            self.env, login="rud_doomed_user", groups="base.group_portal"
        )
        uid = user.id
        request = self.env["res.users.deletion"].create({"user_id": uid})
        self.assertEqual(request.user_id_int, uid)

        # Deleting the user nulls user_id (ondelete='set null') and re-fires the
        # _compute_user_id_int compute.
        user.unlink()
        self.env.invalidate_all()

        self.assertFalse(request.user_id, "user_id is nulled by the FK ondelete")
        self.assertEqual(
            request.user_id_int,
            uid,
            "user_id_int must survive the user deletion (RUD-L1 regression)",
        )
