from odoo.libs.json import dumps as json_dumps
from odoo.tests import new_test_user, tagged
from odoo.tools import mute_logger

from odoo.addons.base.tests.common import HttpCaseWithUserDemo


@tagged("post_install", "-at_install", "web_http", "web_domain")
class DomainTest(HttpCaseWithUserDemo):
    def test_domain_validate(self):
        self.authenticate("demo", "demo")

        with mute_logger("odoo.http"):
            resp = self.url_open(
                "/web/domain/validate",
                headers={"Content-Type": "application/json"},
                data=json_dumps({"params": {"model": "i", "domain": []}}),
            )
        self.assertEqual(resp.json()["error"]["data"]["message"], "Invalid model: i")

        resp = self.url_open(
            "/web/domain/validate",
            headers={"Content-Type": "application/json"},
            data=json_dumps({"params": {"model": "res.users", "domain": []}}),
        )
        self.assertEqual(resp.json()["result"], True)

        resp = self.url_open(
            "/web/domain/validate",
            headers={"Content-Type": "application/json"},
            data=json_dumps(
                {
                    "params": {
                        "model": "res.users",
                        "domain": [("name", "ilike", "ad")],
                    }
                }
            ),
        )
        self.assertEqual(resp.json()["result"], True)

        resp = self.url_open(
            "/web/domain/validate",
            headers={"Content-Type": "application/json"},
            data=json_dumps({"params": {"model": "res.users", "domain": ["hop"]}}),
        )
        self.assertEqual(resp.json()["result"], False)

    def test_domain_validate_denies_portal_user(self):
        portal_user = new_test_user(
            self.env, "domain_portal_user", groups="base.group_portal"
        )
        self.authenticate("domain_portal_user", "domain_portal_user")

        with mute_logger("odoo.http"):
            resp = self.url_open(
                "/web/domain/validate",
                headers={"Content-Type": "application/json"},
                data=json_dumps({"params": {"model": "res.users", "domain": []}}),
            )
        self.assertEqual(
            resp.json()["error"]["data"]["message"],
            "This endpoint is reserved to internal users.",
        )
        self.assertFalse(portal_user._is_internal())
