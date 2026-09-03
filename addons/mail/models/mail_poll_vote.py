import typing

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo.tools import format_list

if typing.TYPE_CHECKING:
    from .discuss.mail_guest import MailGuest
    from .mail_poll_option import MailPollOption
    from odoo.addons.bus.models.res_users import ResUsers


class MailPollVote(models.Model):
    _name = "mail.poll.vote"
    _description = "Poll vote"

    guest_id: MailGuest = fields.Many2one("mail.guest", ondelete="cascade")
    is_self_vote = fields.Boolean(
        compute="_compute_is_self_vote", search="_search_is_self_vote"
    )
    option_id: MailPollOption = fields.Many2one(
        "mail.poll.option", ondelete="cascade", required=True, index=True
    )
    user_id: ResUsers = fields.Many2one("res.users", ondelete="cascade")

    _check_user_or_guest_set = models.Constraint(
        "CHECK (user_id IS NOT NULL OR guest_id IS NOT NULL)",
        "User or guest must be set.",
    )
    _unique_option_id_user_id = models.UniqueIndex(
        "(option_id, user_id)", "User can only vote once per option."
    )
    _unique_option_id_guest_id = models.UniqueIndex(
        "(option_id, guest_id)", "Guest can only vote once per option."
    )

    @api.model
    def _get_current_voter(self) -> tuple:
        """Who is voting, as (user, guest).

        `res.partner._get_current_persona()` answers with a partner, but a vote
        is keyed on the user, so the translation happens once here instead of at
        every call site.
        """
        partner, guest = self.env["res.partner"]._get_current_persona()
        return (self.env.user if partner else self.env["res.users"], guest)

    @api.model_create_multi
    def create(self, vals_list):
        votes = super().create(vals_list)
        if votes_on_closed_poll := votes.filtered(
            lambda vote: vote.option_id.poll_id.end_message_id
        ):
            raise ValidationError(
                self.env._(
                    'Cannot vote on closed poll: "%(polls)s"',
                    polls=format_list(
                        self.env,
                        votes_on_closed_poll.option_id.poll_id.mapped("poll_question"),
                    ),
                )
            )
        return votes

    @api.constrains("guest_id", "user_id")
    def _check_allow_multiple_options(self) -> None:
        result = self.env["mail.poll.vote"]._read_group(
            [
                ("option_id.poll_id", "in", self.option_id.poll_id.ids),
                ("option_id.poll_id.allow_multiple_options", "=", False),
            ],
            ["option_id.poll_id", "user_id", "guest_id"],
            ["__count"],
            [("__count", ">", 1)],
        )
        if failing_polls := self.env["mail.poll"].browse([row[0].id for row in result]):
            raise ValidationError(
                self.env._(
                    'Cannot vote on poll "%(polls)s": only one vote is allowed per user.',
                    polls=format_list(self.env, failing_polls.mapped("poll_question")),
                )
            )

    @api.depends_context("guest", "uid")
    @api.depends("user_id", "guest_id")
    def _compute_is_self_vote(self) -> None:
        user, guest = self._get_current_voter()
        self.is_self_vote = False
        for vote in self:
            if vote.user_id and user == vote.user_id:
                vote.is_self_vote = True
            if vote.guest_id and guest == vote.guest_id:
                vote.is_self_vote = True

    def _search_is_self_vote(self, operator, operand):
        if operator != "in":
            return NotImplemented
        user, guest = self._get_current_voter()
        domain_user = Domain("user_id", "=", user.id) if user else Domain.FALSE
        domain_guest = Domain("guest_id", "=", guest.id) if guest else Domain.FALSE
        return domain_user | domain_guest
