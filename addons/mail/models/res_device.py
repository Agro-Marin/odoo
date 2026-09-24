from odoo import models
from odoo.libs.debug_log import DebugLog

_debug = DebugLog(__name__)


class ResDevice(models.Model):
    _inherit = "res.device"

    def _notify_new_device(self) -> None:
        super()._notify_new_device()
        self.check_singleton()
        user = self.user_id
        if not user.email or not self.browser:
            # a script signing in without keeping cookies is a new device at
            # every login: only a browser is worth an alert
            _debug.logic(
                "new_device_alert_skipped",
                reason="no_email_or_browser",
                email=bool(user.email),
                browser=self.browser,
                platform=self.platform,
            )
            return
        if user._get_mfa_type():
            # the second factor's own alert already covers a new browser
            _debug.logic("new_device_alert_skipped", reason="mfa")
            return
        if not self.with_context(active_test=False).search_count(
            [("user_id", "=", user.id), ("id", "!=", self.id)], limit=1
        ):
            _debug.logic("new_device_alert_skipped", reason="first_device")
            return
        user._notify_security_setting_update(
            subject=self.env._("New Sign-in to your Account"),
            content=self.env._(
                "A device never used before, %(device)s, signed in to your account.",
                device=self.display_name,
            ),
        )
        _debug.lifecycle("new_device_alert_sent", user=user.id, device=self.id)
