from odoo import _, api, models


class ResUsers(models.Model):
    _inherit = "res.users"

    @api.model_create_multi
    def create(self, vals_list):
        """Trigger automatic subscription based on user groups"""
        users = super().create(vals_list)
        users._enroll_in_group_channels()
        return users

    def write(self, vals):
        """Trigger automatic subscription based on updated user groups"""
        res = super().write(vals)
        if "group_ids" in vals:
            self._enroll_in_group_channels()
        return res

    def _enroll_in_group_channels(self):
        """Enroll each user in the channels their own groups grant them.

        Read from ``all_group_ids`` after the write rather than from the write's
        commands: hand-parsing them covered ``Command.LINK`` and ``Command.SET``
        only, so a plain list of ids -- which the ORM accepts for any x2many --
        raised ``TypeError: 'int' object is not subscriptable``, a group held by
        implication was invisible, and a multi-user write enrolled every user
        written into the channels matching the *union* of their groups.
        """
        if not self.all_group_ids:
            return
        channels = (
            self.env["slide.channel"]
            .sudo()
            .search([("enroll_group_ids", "in", self.all_group_ids.ids)])
        )
        for user in self:
            matching = channels.filtered(
                lambda channel, user=user: channel.enroll_group_ids & user.all_group_ids
            )
            if matching:
                matching._action_add_members(user.partner_id)

    def get_gamification_redirection_data(self):
        res = super().get_gamification_redirection_data()
        res.append({"url": "/slides", "label": _("See our eLearning")})
        return res
