from odoo.exceptions import AccessError
from odoo.tests import new_test_user, tagged

from odoo.addons.website_slides.tests.common import SlidesCase


@tagged("post_install", "-at_install")
class TestCourseAccessRequest(SlidesCase):
    """Asking to join a course on invitation is an approval request.

    The course holds one request per partner asking (mixin.approval.subjects). The
    course responsible is asked through an activity that still carries the requesting
    partner, so the Grant / Refuse buttons keep working; an approval enrolls the
    partner, and the request records who decided.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.access_channel = (
            cls.env["slide.channel"]
            .with_user(cls.user_officer)
            .create(
                {
                    "name": "Course On Invitation",
                    "channel_type": "training",
                    "enroll": "invite",
                    "visibility": "public",
                    "is_published": True,
                }
            )
        )
        cls.requester = cls.user_portal.partner_id

    def _ask(self, user=None):
        return self.access_channel.with_user(
            user or self.user_portal
        ).action_request_access()

    def _request(self):
        return self.access_channel.sudo()._get_approval_request(
            f"access:{self.requester.id}"
        )

    def test_a_request_asks_the_responsible_and_names_the_partner(self):
        self.assertEqual(self._ask(), {"done": True})

        request = self._request()
        self.assertEqual(request.state, "pending")
        self.assertEqual(request.request_owner_id, self.user_portal)
        self.assertTrue(
            self.access_channel.with_user(self.user_portal).has_requested_access
        )
        activity = self.access_channel.sudo().activity_ids.filtered(
            lambda activity: activity.approver_id.request_id == request
        )
        self.assertEqual(activity.user_id, self.user_officer)
        self.assertEqual(activity.request_partner_id, self.requester)

    def test_asking_twice_is_already_requested(self):
        self._ask()

        self.assertEqual(self._ask(), {"error": "Already Requested"})
        self.assertEqual(len(self.access_channel.sudo().approval_request_ids), 1)

    def test_the_responsible_granting_enrolls_the_partner(self):
        self._ask()

        self.access_channel.with_user(self.user_officer).action_grant_access(
            self.requester.id
        )

        request = self._request()
        self.assertEqual(request.state, "approved")
        self.assertEqual(
            request.approver_ids.filtered("decision_date").decided_by_user_id,
            self.user_officer,
        )
        self.assertIn(
            self.requester, self.access_channel.sudo().channel_partner_ids.partner_id
        )
        self.assertFalse(self.access_channel.sudo().activity_ids)
        self.assertFalse(
            self.access_channel.with_user(self.user_portal).has_requested_access
        )

    def test_the_responsible_refusing_enrolls_nobody(self):
        self._ask()

        self.access_channel.with_user(self.user_officer).action_refuse_access(
            self.requester.id
        )

        self.assertEqual(self._request().state, "refused")
        self.assertNotIn(
            self.requester, self.access_channel.sudo().channel_partner_ids.partner_id
        )

    def test_another_officer_may_grant(self):
        officer = new_test_user(
            self.env,
            login="access_request_other_officer",
            groups="base.group_user,website_slides.group_website_slides_officer",
        )
        self._ask()

        self.access_channel.with_user(officer).action_grant_access(self.requester.id)

        self.assertEqual(self._request().state, "approved")
        self.assertIn(
            self.requester, self.access_channel.sudo().channel_partner_ids.partner_id
        )

    def test_an_employee_cannot_grant(self):
        self._ask()

        with self.assertRaises(AccessError):
            self.access_channel.with_user(self.user_emp).action_grant_access(
                self.requester.id
            )

        self.assertEqual(self._request().state, "pending")
        self.assertNotIn(
            self.requester, self.access_channel.sudo().channel_partner_ids.partner_id
        )

    def test_an_open_course_raises_no_request(self):
        self.assertEqual(
            self.channel.with_user(self.user_emp).action_request_access(),
            {"done": False},
        )
        self.assertFalse(self.channel.sudo().approval_request_ids)

    def test_a_request_kept_as_an_activity_is_backfilled(self):
        self.access_channel.sudo().activity_schedule(
            "mail.mail_activity_data_todo",
            summary="Access Request",
            user_id=self.user_officer.id,
            request_partner_id=self.requester.id,
        )

        self.env["slide.channel"]._backfill_access_requests()

        request = self._request()
        self.assertEqual(request.state, "pending")
        self.assertEqual(request.request_owner_id, self.user_portal)
        activities = self.access_channel.sudo().activity_ids
        self.assertEqual(len(activities), 1)
        self.assertEqual(activities.approver_id.request_id, request)
        self.assertEqual(activities.request_partner_id, self.requester)
