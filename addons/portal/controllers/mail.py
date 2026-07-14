from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request
from odoo.tools import consteq

from odoo.addons.mail.controllers import mail


class MailController(mail.MailController):
    """Portal overrides for /mail/* routes: redirect share-users to /my and add token-based access."""

    @classmethod
    def _redirect_to_generic_fallback(cls, model, res_id, access_token=None, **kwargs):
        # Share (portal) users land on /my; everyone else falls through to upstream.
        if request.session.uid and request.env.user.share:
            return request.redirect("/my")
        return super()._redirect_to_generic_fallback(
            model, res_id, access_token=access_token, **kwargs
        )

    @classmethod
    def _redirect_to_record(cls, model, res_id, access_token=None, **kwargs):
        """Redirect to the portal view when the caller proves access via ``access_token``.

        If ``pid`` and ``hash`` are also given, append them to the redirect URL so
        the chatter on the destination page can identify the recipient.

        :param model: model name of the record being visualised
        :param res_id: id of the record
        :param access_token: per-record token bypassing the user's rights/rules
        :param kwargs: typically ``pid`` (res.partner id) and ``hash`` (HMAC) for
                       chatter recipient identification
        """
        # No model / res_id: nothing to redirect to, defer to parent.
        if not model or not res_id or model not in request.env:
            return super()._redirect_to_record(
                model, res_id, access_token=access_token, **kwargs
            )

        if isinstance(request.env[model], request.env.registry["portal.mixin"]):
            uid = request.session.uid or request.env.ref("base.public_user").id
            record_sudo = request.env[model].sudo().browse(res_id).exists()
            try:
                record_sudo.with_user(uid).check_access("read")
            except AccessError:
                # Constant-time token comparison: do NOT replace consteq with ==,
                # the difference is a real timing-attack vector.
                if (
                    record_sudo.access_token
                    and access_token
                    and consteq(record_sudo.access_token, access_token)
                ):
                    record_action = record_sudo._get_access_action(force_website=True)
                    if record_action["type"] == "ir.actions.act_url":
                        pid = kwargs.get("pid")
                        hash_param = kwargs.get("hash")
                        url = record_action["url"]
                        if pid and hash_param:
                            parsed = urlsplit(url)
                            # keep_blank_values=True: don't drop empty-valued
                            # params already on the access-action URL (werkzeug
                            # preserved them; stdlib parse_qsl drops them).
                            url_params = parse_qsl(
                                parsed.query, keep_blank_values=True
                            ) + [
                                ("pid", pid),
                                ("hash", hash_param),
                            ]
                            url = urlunsplit(
                                parsed._replace(query=urlencode(sorted(url_params)))
                            )
                        return request.redirect(url)
        return super()._redirect_to_record(
            model, res_id, access_token=access_token, **kwargs
        )

    # Override only to add ``website=True`` so the unfollow page renders inside the portal layout.
    @http.route("/mail/unfollow", type="http", website=True)
    def mail_action_unfollow(self, model, res_id, pid, token, **kwargs):
        return super().mail_action_unfollow(model, res_id, pid, token, **kwargs)
