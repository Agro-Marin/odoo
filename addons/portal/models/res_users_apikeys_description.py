from odoo import _, models
from odoo.exceptions import AccessError


class ResUsersApikeysDescription(models.TransientModel):
    """Allow portal users to mint API keys when ``portal.allow_api_keys`` is enabled."""

    _inherit = "res.users.apikeys.description"

    def check_access_make_key(self):
        """Override the upstream check: portal users may create keys if the admin opted in.

        - Internal users: defer to parent (default Odoo policy).
        - Portal users with ``portal.allow_api_keys`` enabled: allowed.
        - Anonymous / public: rejected with a clearer message than the parent's.

        :raises AccessError: if the caller is neither internal nor a portal user
                             with the feature enabled.
        """
        try:
            return super().check_access_make_key()
        except AccessError:
            allow_portal = bool(
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("portal.allow_api_keys")
            )
            if not allow_portal:
                raise
            if self.env.user._is_portal():
                return None
            raise AccessError(
                _("Only internal and portal users can create API keys")
            ) from None
