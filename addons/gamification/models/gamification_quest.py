from odoo import _, api, exceptions, fields, models


class GamificationQuest(models.Model):
    """Multi-step narrative journey wrapping goal definitions.

    Unlike challenges (which are flat lists of independent goals), quests
    are *ordered sequences* of steps with prerequisites, narrative context,
    and a sense of progression.  They map to Octalysis drives 1 (Epic
    Meaning) and 3 (Empowerment of Creativity) by giving users a story
    and choices.
    """

    _name = "gamification.quest"
    _description = "Gamification Quest"
    _inherit = ["mail.thread"]
    _order = "sequence, name"

    name = fields.Char("Quest Name", required=True, translate=True, tracking=True)
    description = fields.Html(
        "Story",
        translate=True,
        sanitize_attributes=False,
        help="Narrative framing for the quest (e.g., 'The Data Quality Crusade').",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    icon = fields.Image("Icon", max_width=128, max_height=128)

    # Steps
    step_ids = fields.One2many(
        "gamification.quest.step", "quest_id", string="Steps", copy=True
    )
    step_count = fields.Integer("# Steps", compute="_compute_step_count")

    # Rewards for completing the entire quest
    reward_badge_id = fields.Many2one(
        "gamification.badge",
        string="Completion Badge",
        help="Badge granted when all steps are completed.",
    )
    reward_karma = fields.Integer(
        "Completion Karma",
        default=0,
        help="Bonus karma granted on quest completion (on top of step rewards).",
    )

    # Targeting
    quest_mode = fields.Selection(
        [("solo", "Solo"), ("team", "Team")],
        default="solo",
        required=True,
        string="Mode",
    )
    difficulty = fields.Selection(
        [
            ("beginner", "Beginner"),
            ("intermediate", "Intermediate"),
            ("advanced", "Advanced"),
            ("expert", "Expert"),
        ],
        default="intermediate",
        required=True,
    )

    # Enrollment tracking
    enrollment_ids = fields.One2many(
        "gamification.quest.enrollment", "quest_id", string="Enrollments"
    )
    enrollment_count = fields.Integer("# Enrolled", compute="_compute_enrollment_count")
    completion_count = fields.Integer(
        "# Completed", compute="_compute_enrollment_count"
    )

    @api.depends("step_ids")
    def _compute_step_count(self):
        for quest in self:
            quest.step_count = len(quest.step_ids)

    @api.depends("enrollment_ids.state")
    def _compute_enrollment_count(self):
        if not self.ids:
            for q in self:
                q.enrollment_count = 0
                q.completion_count = 0
            return
        data = self.env["gamification.quest.enrollment"]._read_group(
            [("quest_id", "in", self.ids)],
            groupby=["quest_id", "state"],
            aggregates=["__count"],
        )
        enroll_map = {}
        complete_map = {}
        for quest, state, count in data:
            enroll_map[quest.id] = enroll_map.get(quest.id, 0) + count
            if state == "completed":
                complete_map[quest.id] = complete_map.get(quest.id, 0) + count
        for quest in self:
            quest.enrollment_count = enroll_map.get(quest.id, 0)
            quest.completion_count = complete_map.get(quest.id, 0)


class GamificationQuestStep(models.Model):
    """Individual step within a quest.

    Each step references a goal definition that must be met.  Steps are
    ordered by sequence and may have prerequisite steps that must be
    completed first.
    """

    _name = "gamification.quest.step"
    _description = "Quest Step"
    _order = "sequence, id"

    quest_id = fields.Many2one(
        "gamification.quest",
        required=True,
        ondelete="cascade",
        index=True,
    )
    name = fields.Char("Step Name", required=True, translate=True)
    description = fields.Text(
        "Description",
        translate=True,
        help="What the user needs to do for this step.",
    )
    sequence = fields.Integer(default=10)

    # What to accomplish
    definition_id = fields.Many2one(
        "gamification.goal.definition",
        string="Goal Definition",
        help="The goal definition this step evaluates. "
        "Leave empty for manually-verified steps.",
    )
    target_goal = fields.Float(
        "Target",
        default=1,
        help="Target value for the goal (e.g., 10 leads, 5 invoices).",
    )

    # Prerequisites (other steps in the same quest)
    prerequisite_ids = fields.Many2many(
        "gamification.quest.step",
        "gamification_quest_step_prereq_rel",
        "step_id",
        "prereq_id",
        string="Prerequisites",
        domain="[('quest_id', '=', quest_id), ('id', '!=', id)]",
        help="Steps that must be completed before this one unlocks.",
    )

    # Rewards per step
    karma_reward = fields.Integer("Step Karma", default=0)
    badge_id = fields.Many2one(
        "gamification.badge",
        string="Step Badge",
        help="Optional badge for completing this step.",
    )

    # Skill tree link
    skill_node_id = fields.Many2one(
        "gamification.skill.node",
        string="Skill Node",
        ondelete="set null",
        help="Skill tree node this step contributes to.",
    )

    @api.constrains("prerequisite_ids")
    def _check_no_self_prerequisite(self):
        """Prevent a step from being its own prerequisite."""
        for step in self:
            if step in step.prerequisite_ids:
                raise exceptions.ValidationError(
                    _("A step cannot be its own prerequisite.")
                )


class GamificationQuestEnrollment(models.Model):
    """Tracks a user's progress through a quest.

    One enrollment per user per quest.  Each enrollment has step
    completion records that track which steps are done.
    """

    _name = "gamification.quest.enrollment"
    _description = "Quest Enrollment"
    _order = "create_date desc"
    _rec_name = "quest_id"

    quest_id = fields.Many2one(
        "gamification.quest",
        required=True,
        index=True,
        ondelete="cascade",
    )
    user_id = fields.Many2one(
        "res.users",
        required=True,
        index=True,
        ondelete="cascade",
        default=lambda self: self.env.uid,
    )
    state = fields.Selection(
        [
            ("in_progress", "In Progress"),
            ("completed", "Completed"),
            ("abandoned", "Abandoned"),
        ],
        default="in_progress",
        required=True,
        index=True,
    )
    progress_percent = fields.Float(
        "Progress %", compute="_compute_progress", store=True
    )

    # Step completions
    completion_ids = fields.One2many(
        "gamification.quest.step.completion",
        "enrollment_id",
        string="Step Completions",
    )

    _user_quest_uniq = models.UniqueIndex(
        "(user_id, quest_id)",
        "A user can only enroll in a quest once.",
    )

    @api.depends("completion_ids", "quest_id.step_ids")
    def _compute_progress(self):
        for enrollment in self:
            total = len(enrollment.quest_id.step_ids)
            done = len(enrollment.completion_ids)
            enrollment.progress_percent = round(100.0 * done / total, 1) if total else 0

    def complete_step(self, step):
        """Mark a step as completed for this enrollment.

        Validates prerequisites, creates the completion record, grants
        step rewards, and checks if the quest is now complete.

        :param step: ``gamification.quest.step`` record.
        :return: created ``gamification.quest.step.completion`` or False.
        """
        self.ensure_one()
        if self.state != "in_progress":
            return False

        # Check not already completed
        if step.id in self.completion_ids.mapped("step_id").ids:
            return False

        # Check prerequisites
        completed_step_ids = set(self.completion_ids.mapped("step_id").ids)
        for prereq in step.prerequisite_ids:
            if prereq.id not in completed_step_ids:
                raise exceptions.UserError(
                    _(
                        "Cannot complete '%(step)s': prerequisite '%(prereq)s' not yet done.",
                        step=step.name,
                        prereq=prereq.name,
                    )
                )

        # Create completion
        completion = self.env["gamification.quest.step.completion"].create(
            {
                "enrollment_id": self.id,
                "step_id": step.id,
            }
        )

        # Grant step rewards
        user = self.user_id
        if step.karma_reward:
            user.sudo()._add_karma(
                step.karma_reward,
                source=self,
                reason=_("Quest step: %s", step.name),
            )
        if step.badge_id:
            self.env["gamification.badge.user"].sudo().create(
                {
                    "user_id": user.id,
                    "badge_id": step.badge_id.id,
                }
            )._send_badge()

        # Check if quest is now complete
        total_steps = len(self.quest_id.step_ids)
        completed_steps = len(self.completion_ids)
        if completed_steps >= total_steps:
            self._complete_quest()

        return completion

    def _complete_quest(self):
        """Mark the quest as completed and grant quest-level rewards."""
        self.ensure_one()
        self.state = "completed"
        user = self.user_id
        quest = self.quest_id

        # Grant quest completion rewards
        if quest.reward_karma:
            user.sudo()._add_karma(
                quest.reward_karma,
                source=self,
                reason=_("Quest completed: %s", quest.name),
            )
        if quest.reward_badge_id:
            self.env["gamification.badge.user"].sudo().create(
                {
                    "user_id": user.id,
                    "badge_id": quest.reward_badge_id.id,
                }
            )._send_badge()

        # Log to activity feed
        self.env["gamification.activity"].sudo().create(
            {
                "activity_type": "quest_completed",
                "user_id": user.id,
                "summary": _(
                    "%(user)s completed the '%(quest)s' quest!",
                    user=user.name,
                    quest=quest.name,
                ),
                "icon": "fa fa-flag-checkered",
                "karma_gained": quest.reward_karma,
            }
        )

        # Unlock any skill-tree nodes gated on this quest.  This is the link
        # (node.quest_id) that previously left the skill tree inert.
        self.env["gamification.skill.node"].sudo()._unlock_nodes_for_quest(self)

    def action_abandon(self):
        """Abandon the quest."""
        self.filtered(lambda e: e.state == "in_progress").write(
            {
                "state": "abandoned",
            }
        )


class GamificationQuestStepCompletion(models.Model):
    """Record of completing a single quest step."""

    _name = "gamification.quest.step.completion"
    _description = "Quest Step Completion"
    _order = "completion_date desc"

    enrollment_id = fields.Many2one(
        "gamification.quest.enrollment",
        required=True,
        ondelete="cascade",
        index=True,
    )
    step_id = fields.Many2one(
        "gamification.quest.step",
        required=True,
        ondelete="cascade",
    )
    completion_date = fields.Datetime(
        default=fields.Datetime.now,
        readonly=True,
    )

    _enrollment_step_uniq = models.UniqueIndex(
        "(enrollment_id, step_id)",
        "A step can only be completed once per enrollment.",
    )
