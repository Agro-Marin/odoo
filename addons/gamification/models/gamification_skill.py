# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models


class GamificationSkillTree(models.Model):
    """Branching skill progression tree (e.g., Sales, Technical, Leadership).

    Each tree contains nodes arranged with prerequisite edges.  Users
    unlock nodes by completing linked quests or challenges, giving a
    visual map of "what's possible" and "what I've achieved."  This maps
    to Octalysis drives 2 (Accomplishment), 3 (Creativity/Choice), and
    4 (Ownership).
    """

    _name = "gamification.skill.tree"
    _description = "Gamification Skill Tree"
    _order = "sequence, name"

    name = fields.Char("Tree Name", required=True, translate=True)
    description = fields.Text("Description", translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    icon = fields.Image("Icon", max_width=128, max_height=128)
    color = fields.Integer("Color Index", default=0)

    node_ids = fields.One2many("gamification.skill.node", "tree_id", string="Nodes")
    node_count = fields.Integer("# Nodes", compute="_compute_node_count")

    @api.depends("node_ids")
    def _compute_node_count(self):
        for tree in self:
            tree.node_count = len(tree.node_ids)


class GamificationSkillNode(models.Model):
    """Individual competency node within a skill tree.

    Nodes represent specific skills or competencies.  They can be
    unlocked by completing associated quests or meeting karma thresholds.
    Prerequisite edges between nodes create the branching tree structure.
    """

    _name = "gamification.skill.node"
    _description = "Skill Tree Node"
    _order = "tree_id, level, sequence"

    name = fields.Char("Skill Name", required=True, translate=True)
    description = fields.Text("Description", translate=True)
    tree_id = fields.Many2one(
        "gamification.skill.tree",
        string="Skill Tree",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(default=10)
    level = fields.Integer(
        "Tree Level",
        default=1,
        help="Vertical position in the tree (1 = root, higher = deeper).",
    )

    # Prerequisites
    prerequisite_ids = fields.Many2many(
        "gamification.skill.node",
        "gamification_skill_node_prereq_rel",
        "node_id",
        "prereq_id",
        string="Prerequisites",
        domain="[('tree_id', '=', tree_id), ('id', '!=', id)]",
    )
    dependent_ids = fields.Many2many(
        "gamification.skill.node",
        "gamification_skill_node_prereq_rel",
        "prereq_id",
        "node_id",
        string="Unlocks",
        readonly=True,
    )

    # Unlock conditions
    karma_threshold = fields.Integer(
        "Karma Threshold",
        default=0,
        help="Minimum karma required to unlock (0 = no karma requirement).",
    )
    quest_id = fields.Many2one(
        "gamification.quest",
        string="Required Quest",
        ondelete="set null",
        help="Quest that must be completed to unlock this node.",
    )

    # Rewards
    karma_reward = fields.Integer("Unlock Karma", default=0)
    badge_id = fields.Many2one(
        "gamification.badge",
        string="Unlock Badge",
        ondelete="set null",
    )

    # Tracking
    unlock_ids = fields.One2many(
        "gamification.skill.node.unlock", "node_id", string="Unlocks"
    )
    unlock_count = fields.Integer("# Unlocked", compute="_compute_unlock_count")

    @api.depends("unlock_ids")
    def _compute_unlock_count(self):
        if not self.ids:
            for node in self:
                node.unlock_count = 0
            return
        data = self.env["gamification.skill.node.unlock"]._read_group(
            [("node_id", "in", self.ids)],
            groupby=["node_id"],
            aggregates=["__count"],
        )
        count_map = {node.id: count for node, count in data}
        for node in self:
            node.unlock_count = count_map.get(node.id, 0)

    def check_unlock_for_user(self, user):
        """Check if a user meets the conditions to unlock this node.

        :param user: ``res.users`` record.
        :return: True if all conditions are met.
        """
        self.ensure_one()
        Unlock = self.env["gamification.skill.node.unlock"]

        # Already unlocked?
        if Unlock.search_count(
            [
                ("node_id", "=", self.id),
                ("user_id", "=", user.id),
            ]
        ):
            return False

        # Check prerequisites
        for prereq in self.prerequisite_ids:
            if not Unlock.search_count(
                [
                    ("node_id", "=", prereq.id),
                    ("user_id", "=", user.id),
                ]
            ):
                return False

        # Check karma threshold
        if self.karma_threshold and user.karma < self.karma_threshold:
            return False

        # Check quest completion
        if self.quest_id:
            completed = self.env["gamification.quest.enrollment"].search_count(
                [
                    ("quest_id", "=", self.quest_id.id),
                    ("user_id", "=", user.id),
                    ("state", "=", "completed"),
                ]
            )
            if not completed:
                return False

        return True

    def unlock_for_user(self, user):
        """Unlock this node for a user, granting rewards.

        :param user: ``res.users`` record.
        :return: created unlock record, or False if conditions not met.
        """
        self.ensure_one()
        if not self.check_unlock_for_user(user):
            return False

        Unlock = self.env["gamification.skill.node.unlock"]
        unlock = Unlock.create(
            {
                "node_id": self.id,
                "user_id": user.id,
            }
        )

        # Grant rewards
        if self.karma_reward:
            user.sudo()._add_karma(
                self.karma_reward,
                reason=_("Skill unlocked: %s", self.name),
            )
        if self.badge_id:
            self.env["gamification.badge.user"].sudo().create(
                {
                    "user_id": user.id,
                    "badge_id": self.badge_id.id,
                }
            )._send_badge()

        # Log to activity feed
        self.env["gamification.activity"].sudo().create(
            {
                "activity_type": "skill_unlocked",
                "user_id": user.id,
                "summary": _(
                    "%(user)s unlocked skill '%(skill)s'",
                    user=user.name,
                    skill=self.name,
                ),
                "icon": "fa fa-puzzle-piece",
                "karma_gained": self.karma_reward,
            }
        )

        return unlock


class GamificationSkillNodeUnlock(models.Model):
    """Record of a user unlocking a skill tree node."""

    _name = "gamification.skill.node.unlock"
    _description = "Skill Node Unlock"
    _order = "unlock_date desc"

    node_id = fields.Many2one(
        "gamification.skill.node",
        required=True,
        ondelete="cascade",
        index=True,
    )
    user_id = fields.Many2one(
        "res.users",
        required=True,
        ondelete="cascade",
        index=True,
    )
    unlock_date = fields.Datetime(
        default=fields.Datetime.now,
        readonly=True,
    )

    _user_node_uniq = models.UniqueIndex(
        "(user_id, node_id)",
        "A user can only unlock a skill node once.",
    )
