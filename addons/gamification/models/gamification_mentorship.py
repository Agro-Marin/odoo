from odoo import _, api, exceptions, fields, models


class GamificationMentorship(models.Model):
    """Mentor-mentee pairing for guided gamification progression.

    Creates a structured relationship where experienced users guide
    newcomers.  Mentors earn karma when their mentee hits milestones,
    creating a win-win dynamic (Octalysis drives 1 + 5: Epic Meaning
    + Social Influence).
    """

    _name = "gamification.mentorship"
    _description = "Gamification Mentorship"
    _inherit = ["mail.thread"]
    _order = "create_date desc"
    _rec_name = "display_name"

    mentor_id = fields.Many2one(
        "res.users",
        string="Mentor",
        required=True,
        index=True,
        ondelete="cascade",
        tracking=True,
    )
    mentee_id = fields.Many2one(
        "res.users",
        string="Mentee",
        required=True,
        index=True,
        ondelete="cascade",
        tracking=True,
    )
    state = fields.Selection(
        [
            ("active", "Active"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
        ],
        default="active",
        required=True,
        tracking=True,
        index=True,
    )
    start_date = fields.Date(
        "Start Date",
        default=fields.Date.today,
        readonly=True,
    )
    end_date = fields.Date("End Date", tracking=True)
    description = fields.Text(
        "Goals",
        help="What the mentor and mentee aim to achieve together.",
    )

    # Karma rewards
    mentor_karma_per_milestone = fields.Integer(
        "Mentor Karma per Milestone",
        default=25,
        help="Karma granted to the mentor when the mentee reaches a new rank.",
    )
    mentor_karma_on_completion = fields.Integer(
        "Mentor Karma on Completion",
        default=100,
        help="Karma bonus for the mentor when the mentorship is completed.",
    )
    mentee_milestones_reached = fields.Integer(
        "Milestones Reached",
        default=0,
        readonly=True,
        help="Number of rank-ups the mentee achieved during this mentorship.",
    )
    total_mentor_karma = fields.Integer(
        "Total Mentor Karma Earned",
        default=0,
        readonly=True,
    )

    # Completion
    completion_badge_id = fields.Many2one(
        "gamification.badge",
        string="Completion Badge",
        help="Badge granted to both mentor and mentee on completion.",
    )

    _mentor_mentee_uniq = models.UniqueIndex(
        "(mentor_id, mentee_id) WHERE state = 'active'",
        "A user can only have one active mentorship with the same partner.",
    )

    @api.depends("mentor_id", "mentee_id")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = _(
                "%(mentor)s mentoring %(mentee)s",
                mentor=rec.mentor_id.name or "",
                mentee=rec.mentee_id.name or "",
            )

    @api.constrains("mentor_id", "mentee_id")
    def _check_not_self_mentoring(self):
        """Prevent self-mentoring."""
        for rec in self:
            if rec.mentor_id == rec.mentee_id:
                raise exceptions.ValidationError(_("A user cannot mentor themselves."))

    def action_complete(self):
        """Mark the mentorship as completed and grant rewards."""
        for rec in self.filtered(lambda r: r.state == "active"):
            rec.state = "completed"
            rec.end_date = fields.Date.today()

            # Grant completion karma to mentor
            if rec.mentor_karma_on_completion:
                rec.mentor_id.sudo()._add_karma(
                    rec.mentor_karma_on_completion,
                    source=rec,
                    reason=_("Mentorship completed with %s", rec.mentee_id.name),
                )
                rec.total_mentor_karma += rec.mentor_karma_on_completion

            # Grant completion badge to both
            if rec.completion_badge_id:
                BadgeUser = self.env["gamification.badge.user"].sudo()
                for user in (rec.mentor_id, rec.mentee_id):
                    BadgeUser.create(
                        {
                            "user_id": user.id,
                            "badge_id": rec.completion_badge_id.id,
                        }
                    )._send_badge()

    def action_cancel(self):
        """Cancel the mentorship."""
        self.filtered(lambda r: r.state == "active").write(
            {
                "state": "cancelled",
                "end_date": fields.Date.today(),
            }
        )

    def _on_mentee_rank_up(self, mentee):
        """Called when a mentee reaches a new rank during an active mentorship.

        Grants karma to the mentor and increments the milestone counter.

        :param mentee: ``res.users`` record of the mentee.
        """
        active_mentorships = self.search(
            [
                ("mentee_id", "=", mentee.id),
                ("state", "=", "active"),
            ]
        )
        for rec in active_mentorships:
            if rec.mentor_karma_per_milestone:
                rec.mentor_id.sudo()._add_karma(
                    rec.mentor_karma_per_milestone,
                    source=rec,
                    reason=_(
                        "Mentee %(mentee)s reached %(rank)s",
                        mentee=mentee.name,
                        rank=mentee.rank_id.name or "a new rank",
                    ),
                )
                rec.mentee_milestones_reached += 1
                rec.total_mentor_karma += rec.mentor_karma_per_milestone

    @api.model
    def get_suggested_mentors(self, limit=5):
        """Suggest potential mentors for the current user.

        Returns users with higher karma who are not already mentoring
        the current user.

        :param int limit: max suggestions.
        :return: list of dicts with user_id, user_name, karma, rank_name.
        """
        user = self.env.user
        # Exclude users already mentoring this user
        existing_mentor_ids = (
            self.search(
                [
                    ("mentee_id", "=", user.id),
                    ("state", "=", "active"),
                ]
            )
            .mapped("mentor_id")
            .ids
        )

        mentors = self.env["res.users"].search(
            [
                ("active", "=", True),
                ("share", "=", False),
                ("karma", ">", user.karma),
                ("id", "!=", user.id),
                ("id", "not in", existing_mentor_ids),
                ("company_id", "=", user.company_id.id),
            ],
            order="karma desc",
            limit=limit,
        )
        return [
            {
                "user_id": m.id,
                "user_name": m.name,
                "karma": m.karma,
                "rank_name": m.rank_id.name or "",
            }
            for m in mentors
        ]
