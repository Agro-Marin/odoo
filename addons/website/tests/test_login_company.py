from odoo import Command, http
from odoo.tests import HOST, HttpCase, new_test_user, tagged

from odoo.addons.mail.tests.common import MockEmail

_BROWSER = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


@tagged("post_install", "-at_install")
class TestLoginOutsideTheWebsiteCompany(MockEmail, HttpCase):
    def test_a_new_browser_signs_in_a_user_the_website_company_does_not_hold(self):
        # the login page runs as the website's public user, in the website's
        # company; the user signing in holds only another one
        website = self.env["website"].browse(
            self.env["website"]._get_current_website_id(HOST)
        )
        website.domain = HOST
        other = self.env["res.company"].create({"name": "Other Company"})
        user = new_test_user(
            self.env,
            login="elsewhere",
            password="elsewhere",
            email="elsewhere@example.com",
            company_id=other.id,
            company_ids=[Command.set(other.ids)],
        )
        self.assertNotIn(website.company_id, user.company_ids)
        # a device already known, so this browser is news worth an alert
        self.env["res.device"].sudo().create(
            {
                "user_id": user.id,
                "key_hash": "known",
                "platform": "linux",
                "browser": "chrome",
            }
        )

        self.authenticate(None, None, session_extra={"_trace_disable": False})
        with self.mock_mail_gateway():
            response = self.url_open(
                "/web/login",
                allow_redirects=False,
                headers={"User-Agent": _BROWSER},
                data={
                    "login": "elsewhere",
                    "password": "elsewhere",
                    "csrf_token": http.Request.csrf_token(self),
                },
            )

        self.assertEqual(response.status_code, 303, "not a 403 on the companies")
        self.assertTrue(response.next.path_url.startswith("/odoo"))
        alerts = [
            mail
            for mail in self._new_mails
            if mail.subject == "New Sign-in to your Account"
        ]
        self.assertEqual(len(alerts), 1)
        self.assertIn(
            other.name, alerts[0].body_html, "the user's own company signs it"
        )
