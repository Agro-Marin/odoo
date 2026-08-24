from odoo import Command, api, models
from odoo.tools import str2bool


class ResUsers(models.Model):
    _inherit = "res.users"

    @api.model_create_multi
    def create(self, vals_list):
        """ Automatically subscribe employee users to default digest if activated """
        users = super().create(vals_list)
        users_to_subscribe = users.filtered_domain([('share', '=', False)])
        if not users_to_subscribe:
            return users

        get_param = self.env['ir.config_parameter'].sudo().get_param
        # str2bool, not truthiness: res.config.settings stores a Boolean
        # config_parameter as `str(bool(value))`, so unchecking "Digest Emails"
        # writes the *string* 'False' -- which is truthy. Every user created
        # after the setting was switched off went on being subscribed, and the
        # settings screen showed the box unticked the whole time because
        # `default_get` parses the same parameter properly on the way back in.
        if not str2bool(get_param('digest.default_digest_emails') or '', default=False):
            return users
        default_digest_id = get_param('digest.default_digest_id')
        # A hand-edited parameter must not be able to break every res.users
        # creation path in the database -- signup, imports, `-i` of any module
        # that seeds a user -- with a ValueError from int().
        if not (default_digest_id or '').isdigit():
            return users

        digest = self.env['digest.digest'].sudo().browse(int(default_digest_id)).exists()
        # Command.link, not `|=`: the augmented form reads every recipient the
        # digest already has just to write them all back unchanged.
        digest.user_ids = [Command.link(user.id) for user in users_to_subscribe]
        return users
