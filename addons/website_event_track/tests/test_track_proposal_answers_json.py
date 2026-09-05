import re

from odoo.tests.common import HttpCase, tagged

from odoo.addons.website_event.tests.common import TestEventOnlineCommon


@tagged("post_install", "-at_install")
class TestTrackProposalAnswersJson(TestEventOnlineCommon, HttpCase):
    def test_the_proposal_answer_is_typed_as_json(self):
        self.event_0.write({"is_published": True, "website_track_proposal": True})
        page = self.url_open(f"/event/{self.event_0.id}/track_proposal").text
        csrf = re.search(r"csrf_token\W+([0-9a-f]{64}o\d+)", page)
        self.assertTrue(csrf, "no csrf token on the proposal page")
        before = self.env["event.track"].search_count(
            [("event_id", "=", self.event_0.id)]
        )
        res = self.url_open(
            f"/event/{self.event_0.id}/track_proposal/post",
            data={
                "csrf_token": csrf.group(1),
                "tags": "",
                "track_name": "A talk",
                "partner_name": "Speaker",
                "partner_email": "speaker@example.com",
                "partner_phone": "",
                "partner_function": "",
                "description": "About the talk",
                "partner_biography": "About me",
            },
        )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIn("application/json", res.headers.get("Content-Type", ""))
        self.assertEqual(res.json(), {"success": True})
        self.assertEqual(
            self.env["event.track"].search_count([("event_id", "=", self.event_0.id)]),
            before + 1,
        )
