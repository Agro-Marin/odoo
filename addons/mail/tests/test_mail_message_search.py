from unittest.mock import patch

from odoo.tests.common import tagged

from odoo.addons.mail.tests.common import MailCommon


@tagged("post_install", "-at_install")
class TestMailMessageSearchChunking(MailCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.carrier = cls.env["res.partner"].create({"name": "Carrier"})
        cls.emp_partner = cls.user_employee.partner_id
        cls.admin_partner = cls.user_admin.partner_id
        cls.comment_subtype = cls.env.ref("mail.mt_comment").id

    def _make_messages(self, pattern):
        vals = []
        for accessible in pattern:
            if accessible:
                vals.append(
                    {
                        "author_id": self.emp_partner.id,
                        "model": "res.partner",
                        "res_id": self.carrier.id,
                        "message_type": "comment",
                        "subtype_id": self.comment_subtype,
                        "body": "ok",
                    }
                )
            else:
                vals.append(
                    {
                        "author_id": self.admin_partner.id,
                        "model": "res.partner",
                        "res_id": self.carrier.id,
                        "message_type": "user_notification",
                        "body": "hidden",
                    }
                )
        return self.env["mail.message"].sudo().create(vals)

    def _search_emp(self, domain, **kw):
        return (
            self.env["mail.message"].with_user(self.user_employee).search(domain, **kw)
        )

    def test_full_scan_returns_only_accessible(self):
        pattern = [True, False, True, False, True]
        msgs = self._make_messages(pattern)
        expected = sorted(
            (m.id for m, acc in zip(msgs, pattern, strict=True) if acc), reverse=True
        )
        res = self._search_emp([("id", "in", msgs.ids)], order="id desc")
        self.assertEqual(res.ids, expected)
        res_none = self._search_emp(
            [("id", "in", msgs.ids)], order="id desc", limit=None
        )
        self.assertEqual(res_none.ids, expected)

    def test_pagination_past_long_inaccessible_run(self):
        pattern = [True] * 10 + [False] * 90
        msgs = self._make_messages(pattern)
        accessible = sorted(
            (m.id for m, acc in zip(msgs, pattern, strict=True) if acc), reverse=True
        )

        domain = [("id", "in", msgs.ids)]
        self.assertEqual(
            self._search_emp(domain, limit=5, order="id desc").ids, accessible[:5]
        )
        self.assertEqual(
            self._search_emp(domain, offset=5, limit=5, order="id desc").ids,
            accessible[5:10],
        )
        self.assertEqual(
            self._search_emp(domain, offset=8, limit=5, order="id desc").ids,
            accessible[8:10],
        )
        self.assertEqual(
            self._search_emp(domain, limit=50, order="id desc").ids, accessible
        )

    def test_interleaved_accessibility_across_chunk_boundary(self):
        pattern = [i % 3 == 0 for i in range(100)]
        msgs = self._make_messages(pattern)
        accessible = sorted(
            (m.id for m, acc in zip(msgs, pattern, strict=True) if acc), reverse=True
        )
        domain = [("id", "in", msgs.ids)]

        page = 7
        rebuilt = []
        for offset in range(0, len(accessible) + page, page):
            got = self._search_emp(domain, offset=offset, limit=page, order="id desc")
            rebuilt.extend(got.ids)
        self.assertEqual(rebuilt, accessible)

    def test_small_page_scan_is_bounded_and_thread_size_independent(self):
        small = self._make_messages([True] * 40)
        big = self._make_messages([True] * 400)

        def scan_queries(ids):
            captured = []
            real_execute = type(self.env.cr).execute

            def spy(cr, query, params=None):
                if "mail_message_res_partner_rel" in str(query):
                    captured.append(str(query))
                return real_execute(cr, query, params)

            self.env.flush_all()
            with patch.object(type(self.env.cr), "execute", spy):
                self._search_emp([("id", "in", ids)], limit=10, order="id desc")
            return captured

        small_scans = scan_queries(small.ids)
        big_scans = scan_queries(big.ids)
        self.assertEqual(len(small_scans), 1, "small thread: one candidate scan")
        self.assertEqual(
            len(big_scans),
            1,
            "large thread: still one candidate scan (no whole-thread fetch)",
        )
        self.assertIn(
            "LIMIT", big_scans[0].upper(), "the candidate scan must be SQL-bounded"
        )

    def test_message_fetch_search_term_escapes_like_metachars(self):
        Msg = self.env["mail.message"].sudo()
        common = {
            "author_id": self.emp_partner.id,
            "model": "res.partner",
            "res_id": self.carrier.id,
            "message_type": "comment",
            "subtype_id": self.comment_subtype,
        }
        literal = Msg.create({**common, "body": "discount 50% today"})
        other = Msg.create({**common, "body": "total is 5000 units"})
        domain = [("model", "=", "res.partner"), ("res_id", "=", self.carrier.id)]

        res = self.env["mail.message"]._message_fetch(domain=domain, search_term="50%")
        ids = {m["id"] for m in res["messages"]}
        self.assertIn(literal.id, ids)
        self.assertNotIn(other.id, ids, "a literal '%' must not act as a wildcard")

        res2 = self.env["mail.message"]._message_fetch(
            domain=domain, search_term="discount today"
        )
        self.assertIn(literal.id, {m["id"] for m in res2["messages"]})

    def test_message_fetch_search_by_attachment_name(self):
        record = self.env["res.partner"].create({"name": "SearchAttach"})
        with_att = record.message_post(
            body="please review",
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
            attachments=[("quarterly_report.pdf", b"data")],
        )
        plain = record.message_post(
            body="unrelated note",
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )
        res = self.env["mail.message"]._message_fetch(
            domain=[("model", "=", "res.partner"), ("res_id", "=", record.id)],
            thread=record,
            search_term="quarterly_report",
        )
        ids = {m["id"] for m in res["messages"]}
        self.assertIn(with_att.id, ids, "message must match by its attachment name")
        self.assertNotIn(plain.id, ids)
