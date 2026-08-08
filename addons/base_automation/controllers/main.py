from odoo.http import Controller, request, route

from odoo.addons.base_automation.models.base_automation import (
    get_webhook_request_payload,
)


class BaseAutomationController(Controller):

    @route(
        ["/web/hook/<string:rule_uuid>"],
        type="http",
        auth="public",
        methods=["GET", "POST"],
        csrf=False,
        save_session=False,
    )
    def call_webhook_http(self, rule_uuid, **kwargs):
        """Execute an automation webhook"""
        # Filter on the trigger, not the UUID alone: every base.automation gets a
        # webhook_uuid whatever its trigger, so matching by UUID made rules the
        # admin never published (blank, hidden `url`) executable over HTTP.
        # limit=1 because two rules sharing a UUID would otherwise blow up on
        # ensure_one() inside the verifier and surface as a 500.
        rule = (
            request.env["base.automation"]
            .sudo()
            .search(
                [
                    ("webhook_uuid", "=", rule_uuid),
                    ("trigger", "=", "on_webhook"),
                ],
                limit=1,
            )
        )
        if not rule:
            return request.make_json_response({"status": "error"}, status=404)

        # Authenticate / rate-check before doing any work. remote_addr is the
        # ProxyFix-corrected peer (trust X-Forwarded-For only via proxy_mode).
        ok, status, message = rule._verify_webhook_request(
            headers=dict(request.httprequest.headers),
            body=request.httprequest.get_data(as_text=False),
            remote_addr=request.httprequest.remote_addr,
        )
        if not ok:
            return request.make_json_response(
                {"status": "error", "message": message}, status=status
            )

        data = get_webhook_request_payload()
        try:
            rule._execute_webhook(data)
        except Exception:
            return request.make_json_response({"status": "error"}, status=500)
        return request.make_json_response({"status": "ok"}, status=200)
