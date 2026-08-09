from odoo import _, models
from odoo.exceptions import AccessError
from odoo.tools.misc import str2bool


class ResUsersApikeys(models.Model):
    """Allow portal users to mint API keys when ``portal.allow_api_keys`` is enabled."""

    _inherit = "res.users.apikeys"

    def _check_generate_access(self):
        """Widen the base internal-only policy: portal users may hold keys if the admin opted in.

        - Internal users: defer to parent (default Odoo policy).
        - Portal users with ``portal.allow_api_keys`` enabled: allowed.
        - Anonymous / public with the feature enabled: rejected with a clearer
          message than the parent's.

        :raises AccessError: if the caller is neither internal nor a portal
                             user with the feature enabled.
        """
        try:
            return super()._check_generate_access()
        except AccessError:
            # str2bool, not bool(): get_param returns the *string* the settings
            # form stored, and bool("False") is True -- which granted portal
            # users API keys precisely when an admin had turned the toggle off.
            allow_portal = str2bool(
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("portal.allow_api_keys"),
                default=False,
            )
            if not allow_portal:
                raise
            if self.env.user._is_portal():
                return None
            raise AccessError(
                _("Only internal and portal users can create API keys")
            ) from None
