from datetime import timedelta

from odoo import fields, http
from odoo.fields import Command, Domain
from odoo.http import request

from odoo.addons.mail.controllers.thread import ThreadController
from odoo.addons.mail.tools.discuss import Store, add_guest_to_context


class PollController(ThreadController):
    @http.route("/mail/poll/create", methods=["POST"], type="jsonrpc", auth="user")
    def poll_create(
        self,
        duration,
        option_labels,
        question,
        thread_id,
        thread_model,
        allow_multiple_options=False,
    ):
        if not request.env.user._is_internal():
            return None
        if thread_model != "discuss.channel":
            # polls are a Discuss feature: the composer only offers them in a
            # channel or a group, and only a channel can broadcast the result.
            return None
        thread = self._get_thread_with_access_for_post(thread_model, thread_id)
        if not thread:
            return None
        message = thread.message_post(
            body="", message_type="mail_poll", subtype_xmlid="mail.mt_comment"
        )
        end_dt = fields.Datetime.now() + timedelta(minutes=duration)
        poll_values = {
            "allow_multiple_options": allow_multiple_options,
            "option_ids": [
                Command.create({"option_label": label}) for label in option_labels
            ],
            "poll_end_dt": end_dt,
            "poll_question": question,
            "start_message_id": message.id,
        }
        # sudo - mail.poll: internal user can create a poll on an accessible thread.
        poll = request.env["mail.poll"].sudo().create(poll_values)
        request.env.ref("mail.ir_cron_mail_end_polls")._trigger(end_dt)
        Store(**thread._get_store_target()).add(poll).bus_send()
        return poll.id

    @http.route("/mail/poll/end", methods=["POST"], type="jsonrpc", auth="user")
    def poll_end(self, poll_id):
        poll_domain = Domain("id", "=", poll_id) & Domain("end_message_id", "=", False)
        if not request.env.user._is_admin():
            poll_domain &= Domain("create_uid", "=", request.env.user.id)
        # sudo - mail.poll: the creator of the poll or an admin can end it early.
        request.env["mail.poll"].sudo().search_fetch(poll_domain)._end_and_notify()

    @http.route("/mail/poll/delete", methods=["POST"], type="jsonrpc", auth="user")
    def poll_delete(self, poll_id):
        poll_domain = Domain("id", "=", poll_id)
        if not request.env.user._is_admin():
            poll_domain &= Domain("create_uid", "=", request.env.user.id)
        # sudo - mail.poll: the creator of the poll or an admin can delete it.
        request.env["mail.poll"].sudo().search_fetch(poll_domain).unlink()

    @http.route("/mail/poll/vote", methods=["POST"], type="jsonrpc", auth="public")
    @add_guest_to_context
    def poll_vote(self, poll_id, option_ids):
        options_domain = [("poll_id", "=", poll_id), ("id", "in", option_ids)]
        # sudo - mail.poll.option: reading the options is allowed, the right to
        # vote is what "_get_thread_with_access_for_post" validates below.
        options_sudo = (
            request.env["mail.poll.option"].sudo().search_fetch(options_domain)
        )
        start_message = options_sudo.poll_id.start_message_id
        thread = self._get_thread_with_access_for_post(
            start_message.model, start_message.res_id
        )
        if not thread:
            return
        user, guest = request.env["mail.poll.vote"]._get_current_voter()
        # sudo - mail.poll.vote: the voter can create a vote on a poll of an
        # accessible thread.
        request.env["mail.poll.vote"].sudo().create(
            [
                {
                    "option_id": option.id,
                    "guest_id": guest.id,
                    "user_id": user.id,
                }
                for option in options_sudo
            ]
        )
        Store(bus_channel=user or guest).add(
            options_sudo, ["selected_by_self"]
        ).bus_send()
        Store(**thread._get_store_target()).add(
            options_sudo.poll_id.option_ids, ["number_of_votes", "vote_percentage"]
        ).bus_send()

    @http.route(
        "/mail/poll/remove_vote", methods=["POST"], type="jsonrpc", auth="public"
    )
    @add_guest_to_context
    def poll_remove_vote(self, poll_id):
        votes_domain = [
            ("option_id.poll_id", "=", poll_id),
            ("is_self_vote", "=", True),
        ]
        # sudo - mail.poll.vote: removing and reading one's own vote is allowed.
        votes_sudo = request.env["mail.poll.vote"].sudo().search_fetch(votes_domain)
        user, guest = request.env["mail.poll.vote"]._get_current_voter()
        if not votes_sudo:
            # sudo - mail.poll: re-sending "selected_by_self" to the current
            # voter is allowed.
            poll_sudo = (
                request.env["mail.poll"].sudo().search_fetch([("id", "=", poll_id)])
            )
            Store(bus_channel=user or guest).add(
                poll_sudo.option_ids, ["selected_by_self"]
            ).bus_send()
            return
        options_sudo = votes_sudo.option_id
        poll_sudo = options_sudo.poll_id
        votes_sudo.unlink()
        Store(bus_channel=user or guest).add(
            options_sudo, ["selected_by_self"]
        ).bus_send()
        start_message = poll_sudo.start_message_id
        thread = request.env[start_message.model].browse(start_message.res_id)
        Store(**thread._get_store_target()).add(
            poll_sudo.option_ids, ["number_of_votes", "vote_percentage"]
        ).bus_send()
