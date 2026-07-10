import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ResUsersDeletion(models.Model):
    """Queue of user-deletion requests, processed by a CRON."""

    _name = "res.users.deletion"
    _description = "Users Deletion Request"
    _rec_name = "user_id"

    # Integer copy kept because the related user may be deleted from the database.
    user_id = fields.Many2one("res.users", string="User", ondelete="set null")
    user_id_int = fields.Integer("User Id", compute="_compute_user_id_int", store=True)
    state = fields.Selection(
        [("todo", "To Do"), ("done", "Done"), ("fail", "Failed")],
        string="State",
        required=True,
        default="todo",
        help="Deletion request lifecycle: 'todo' when queued, 'done' once the "
        "user is deleted, 'fail' if deletion was attempted but could not "
        "complete (the user is then archived instead).",
    )

    @api.depends("user_id")
    def _compute_user_id_int(self) -> None:
        for user_deletion in self:
            # user_id is ondelete="set null": once the user is deleted this
            # recomputes with user_id == False. Guard the assignment to preserve
            # the captured id, the only remaining trace of the user. (RUD-L1.)
            if user_deletion.user_id:
                user_deletion.user_id_int = user_deletion.user_id.id

    @api.model
    def _gc_portal_users(self, batch_size: int = 50) -> None:
        """Remove portal users that asked to deactivate their account.

        Done in a CRON because deleting a user is heavy on large databases
        (unindexed create_uid/write_uid on every model). See
        ``res.users._deactivate_portal_user``.

        :param int batch_size: max queued deletions attempted per run; the rest
            stay ``todo`` for the next run.
        """
        delete_requests = self.search([("state", "=", "todo")])

        # Requests whose user is already gone are done.
        done_requests = delete_requests.filtered(lambda request: not request.user_id)
        done_requests.state = "done"

        todo_requests = delete_requests - done_requests
        commit_progress = self.env["ir.cron"]._commit_progress
        commit_progress(len(done_requests), remaining=len(todo_requests))

        for delete_request in todo_requests[:batch_size]:
            delete_request = delete_request.try_lock_for_update().filtered(
                lambda d: d.state == "todo"
            )
            if not delete_request:
                continue
            user = delete_request.user_id
            user_name = user.name
            partner = user.partner_id
            requester_name = delete_request.create_uid.name

            # Step 1: Delete User
            try:
                user.unlink()
                _logger.info(
                    "User #%i %r, deleted. Original request from %r.",
                    user.id,
                    user_name,
                    requester_name,
                )
                delete_request.state = "done"
                commit_progress(1)
            except Exception as e:
                self.env.cr.rollback()
                _logger.error(
                    "User #%i %r could not be deleted. Original request from %r. Related error: %s",
                    user.id,
                    user_name,
                    requester_name,
                    e,
                )
                delete_request.state = "fail"
                # Commit progress even on failure.
                if commit_progress(1):
                    continue
                break

            # Step 2: Delete Linked Partner
            #         May fail, e.g. if the partner is linked to a sale order.
            try:
                if not partner.exists():
                    if not commit_progress():
                        break
                    continue
                partner.unlink()
                _logger.info(
                    "Partner #%i %r, deleted. Original request from %r.",
                    partner.id,
                    user_name,
                    requester_name,
                )
                if not commit_progress():
                    break
            except Exception as e:
                self.env.cr.rollback()
                _logger.warning(
                    "Partner #%i %r could not be deleted. Original request from %r. Related error: %s",
                    partner.id,
                    user_name,
                    requester_name,
                    e,
                )
                if not commit_progress():  # just check if we should stop
                    break
