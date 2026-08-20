from odoo.tests import tagged, users

from odoo.addons.mail.tests.common import MailCommon


@tagged("mail_tools", "res_partner")
class TestMailTools(MailCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls._test_email = "alfredoastaire@test.example.com"
        cls.test_partner = cls.env["res.partner"].create(
            {
                "country_id": cls.env.ref("base.be").id,
                "email": cls._test_email,
                "name": "Alfred Astaire",
                "phone": "0456334455",
            }
        )

    @users("employee")
    def test_find_partner_from_emails(self):
        Partner = self.env["res.partner"]
        test_partner = Partner.browse(self.test_partner.ids)
        self.assertEqual(test_partner.email, self._test_email)

        sources = [
            self._test_email,
            f'"Norbert Poiluchette" <{self._test_email}>',
            "fredoastaire@test.example.com",
        ]
        expected_partners = [
            test_partner,
            test_partner,
            self.env["res.partner"],
        ]
        for source, expected_partner in zip(sources, expected_partners, strict=False):
            with self.subTest(source=source):
                found = Partner._mail_find_partner_from_emails([source])
                self.assertEqual(found, [expected_partner])

        found = Partner._mail_find_partner_from_emails(
            ["alfred_astaire@test.example.com"]
        )
        self.assertEqual(found, [self.env["res.partner"]])

        test_partner.sudo().write(
            {"email": f'"Alfred Mighty Power Astaire" <{self._test_email}>'}
        )

        sources = [
            self._test_email,
            f'"Norbert Poiluchette" <{self._test_email}>',
        ]
        expected_partners = [
            test_partner,
            test_partner,
        ]
        for source, expected_partner in zip(sources, expected_partners, strict=False):
            with self.subTest(source=source):
                found = Partner._mail_find_partner_from_emails([source])
                self.assertEqual(found, [expected_partner])

        found = Partner._mail_find_partner_from_emails(
            ["alfred_astaire@test.example.com"]
        )
        self.assertEqual(found, [self.env["res.partner"]])

    def test_mail_find_partner_from_emails_alias_localpart(self):
        self.env["mail.alias"].create(
            [
                {
                    "alias_name": "test_localpart",
                    "alias_domain_id": self.env.company.alias_domain_id.id,
                    "alias_incoming_local": True,
                    "alias_model_id": self.env.ref("mail.model_res_partner").id,
                }
            ]
        )

        found = self.env["mixin.mail.thread"]._partner_find_from_emails_single(
            ["test_localpart@gmail.com"], no_create=False
        )
        self.assertFalse(
            found, f"Found {found.email} / {found.name} instead of empty recordset"
        )

        self.env["ir.config_parameter"].set_param(
            "mail.catchall.domain.allowed", "tartopoils.com, brutijus.com"
        )
        for test_email, email_normalized, done in [
            ('"Customer" <test_localpart@gmail.com>', "test_localpart@gmail.com", True),
            (
                '"Customer" <test_localpart@tartopoils.com>',
                "test_localpart@tartopoils.com",
                False,
            ),
            (
                '"Customer" <test_localpart@brutijus.com>',
                "test_localpart@brutijus.com",
                False,
            ),
            (
                '"Customer" <test_localpart@brutijus.fr.com>',
                "test_localpart@brutijus.fr.com",
                True,
            ),
        ]:
            with self.subTest(check="Allowed domain support", test_email=test_email):
                found = self.env["mixin.mail.thread"]._partner_find_from_emails_single(
                    [test_email], no_create=False
                )
                if not done:
                    self.assertFalse(
                        found,
                        f"Found {found.email} / {found.name} instead of empty recordset",
                    )
                else:
                    self.assertTrue(found, "Should have created a partner")
                    self.assertEqual(found.email_normalized, email_normalized)
                    self.assertEqual(found.name, "Customer")

        found = self.env["mixin.mail.thread"]._partner_find_from_emails_single(
            ['"Customer" <test_no_localpart@gmail.com>'], no_create=False
        )
        self.assertTrue(found, "Should have created a partner")
        self.assertEqual(found.email_normalized, "test_no_localpart@gmail.com")
        self.assertEqual(found.name, "Customer")

        test_list = [
            '"Customer" <test_localpart@gmail.com>',
            '"Customer" <test_localpart@tartopoils.com>',
            '"Customer" <test_localpart@brutijus.com>',
            '"Customer" <test_localpart@brutijus.fr.com>',
        ]

        found = self.env["mixin.mail.thread"]._partner_find_from_emails_single(
            test_list, no_create=False
        )
        self.assertEqual(
            len(found),
            2,
            "Should have found 2 partners, as tartopoils.com and brutijus.com are limiting local part alias recognition, limiting alias conflict check to those domains",
        )
        self.assertEqual(
            found.mapped("email_normalized"),
            ["test_localpart@gmail.com", "test_localpart@brutijus.fr.com"],
            "Found Partners have wrong normalized email addresses",
        )

    @users("employee")
    def test_mail_find_partner_from_emails_followers(self):
        linked_record = (
            self.env["res.partner"].sudo().create({"name": "Record for followers"})
        )
        follower_partner = (
            self.env["res.partner"]
            .sudo()
            .create(
                {
                    "email": self._test_email,
                    "name": "Duplicated, follower of record",
                }
            )
        )
        linked_record.message_subscribe(partner_ids=follower_partner.ids)
        test_partner = self.test_partner.with_env(self.env)

        cases = [(self._test_email, True), (self._test_email, False)]
        for source, follower_check in cases:
            expected_partner = follower_partner if follower_check else test_partner
            with self.subTest(source=source, follower_check=follower_check):
                partner = self.env["res.partner"]._mail_find_partner_from_emails(
                    [source], records=linked_record if follower_check else None
                )[0]
                self.assertEqual(partner, expected_partner)

        encapsulated_test_email = f'"Robert Astaire" <{self._test_email}>'
        (follower_partner + test_partner).sudo().write(
            {"email": encapsulated_test_email}
        )
        cases = [
            (self._test_email, True),
            (self._test_email, False),
            (encapsulated_test_email, True),
            (encapsulated_test_email, False),
            (f'"AnotherName" <{self._test_email}', True),
            (
                f'"AnotherName" <{self._test_email}',
                False,
            ),
        ]
        for source, follower_check in cases:
            expected_partner = follower_partner if follower_check else test_partner
            with self.subTest(source=source, follower_check=follower_check):
                partner = self.env["res.partner"]._mail_find_partner_from_emails(
                    [source], records=linked_record if follower_check else None
                )[0]
                self.assertEqual(
                    partner,
                    expected_partner,
                    "Mail: formatted email is recognized through usage of normalized email",
                )

        _test_email_2 = '"Robert Astaire" <not.alfredoastaire@test.example.com>'
        (follower_partner + test_partner).sudo().write(
            {"email": f"{self._test_email}, {_test_email_2}"}
        )
        cases = [
            (self._test_email, True, follower_partner),
            (self._test_email, False, test_partner),
            (_test_email_2, True, self.env["res.partner"]),
            (_test_email_2, False, self.env["res.partner"]),
            (
                "not.alfredoastaire@test.example.com",
                True,
                self.env["res.partner"],
            ),
            (
                "not.alfredoastaire@test.example.com",
                False,
                self.env["res.partner"],
            ),
            (
                f"{self._test_email}, {_test_email_2}",
                True,
                follower_partner,
            ),
            (
                f"{self._test_email}, {_test_email_2}",
                False,
                test_partner,
            ),
        ]
        for source, follower_check, expected_partner in cases:
            with self.subTest(source=source, follower_check=follower_check):
                partner = self.env["res.partner"]._mail_find_partner_from_emails(
                    [source], records=linked_record if follower_check else None
                )[0]
                self.assertEqual(
                    partner,
                    expected_partner,
                    "Mail (FIXME): partial recognition of multi email through email_normalize",
                )

        self.user_employee.sudo().write(
            {
                "email": '"Alfred Astaire" <%s>'
                % self.env.user.partner_id.email_normalized
            }
        )
        found = self.env["res.partner"]._mail_find_partner_from_emails(
            [self.env.user.partner_id.email_formatted]
        )
        self.assertEqual(found, [self.env.user.partner_id])

    def test_mail_find_partner_from_emails_multicompany(self):
        Partner = self.env["res.partner"]
        self.test_partner.company_id = self.company_2
        self.test_partner.write({"name": "Original - Company2"})

        test_partner_no_company = self.test_partner.copy(
            {"name": "NoCompany", "company_id": False}
        )
        test_partner_company_2 = self.test_partner
        test_partner_company_3 = test_partner_no_company.copy(
            {"name": "Company3", "company_id": self.company_3.id}
        )
        records = [
            None,
            *Partner.create(
                [
                    {"name": "Company 2 contact", "company_id": self.company_2.id},
                    {"name": "Company 3 contact", "company_id": self.company_3.id},
                    {"name": "No restrictions", "company_id": False},
                ]
            ),
        ]
        expected_partners = [
            (
                test_partner_no_company,
                "W/out reference record, prefer non-specific partner.",
            ),
            (test_partner_company_2, "Prefer same company as reference record."),
            (test_partner_company_3, "Prefer same company as reference record."),
            (
                test_partner_no_company,
                "Prefer non-specific partner for non-specific records.",
            ),
        ]
        for record, (expected, msg) in zip(records, expected_partners, strict=False):
            with self.subTest(record=record.name if record else "NoRecord"):
                found = Partner._mail_find_partner_from_emails(
                    [self._test_email], records=record
                )
                self.assertEqual(
                    found,
                    [expected],
                    f"Found {found[0].name} instead of {expected[0].name}: {msg}",
                )


@tagged("mail_tools", "mail_init")
class TestMailUtils(MailCommon):
    def test_migrate_icp_to_domain(self):
        self.env["ir.config_parameter"].set_param(
            "mail.catchall.domain", "test.migration.com"
        )
        self.env["ir.config_parameter"].set_param("mail.bounce.alias", "migrate+bounce")
        self.env["ir.config_parameter"].set_param(
            "mail.catchall.alias", "migrate+catchall"
        )
        self.env["ir.config_parameter"].set_param(
            "mail.default.from", "migrate+default_from"
        )

        existing = self.env["mail.alias.domain"].search(
            [("name", "=", "test.migration.com")]
        )
        self.assertFalse(existing)

        new = self.env["mail.alias.domain"]._migrate_icp_to_domain()
        self.assertEqual(new.name, "test.migration.com")
        self.assertEqual(new.bounce_alias, "migrate+bounce")
        self.assertEqual(new.catchall_alias, "migrate+catchall")
        self.assertEqual(new.default_from, "migrate+default_from")

        again = self.env["mail.alias.domain"]._migrate_icp_to_domain()
        self.assertEqual(again.name, "test.migration.com")

        existing = self.env["mail.alias.domain"].search(
            [("name", "=", "test.migration.com")]
        )
        self.assertEqual(len(existing), 1, "Should not migrate twice")


@tagged("mail_tools")
class TestMailBannedEmails(MailCommon):
    """OdooBot's address is only worth banning while it is OdooBot's alone."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.root = cls.env.ref("base.partner_root").sudo()
        if not cls.root.email_normalized:
            cls.root.email = "odoobot@test.example.com"
        cls.root_email = cls.root.email_normalized

    def test_root_email_is_banned_when_only_odoobot_uses_it(self):
        banned = self.env["res.partner"]._mail_get_banned_emails([self.root_email])
        self.assertIn(self.root_email, banned)

    def test_root_email_is_not_banned_when_a_real_partner_shares_it(self):
        self.env["res.partner"].create(
            {"name": "Shares OdooBot address", "email": self.root_email}
        )
        banned = self.env["res.partner"]._mail_get_banned_emails([self.root_email])
        self.assertNotIn(
            self.root_email,
            banned,
            "an active partner using that address must stay suggestable",
        )

    def test_archived_partner_does_not_unban_root_email(self):
        self.env["res.partner"].create(
            {
                "name": "Archived sharer",
                "email": self.root_email,
                "active": False,
            }
        )
        banned = self.env["res.partner"]._mail_get_banned_emails([self.root_email])
        self.assertIn(self.root_email, banned)
