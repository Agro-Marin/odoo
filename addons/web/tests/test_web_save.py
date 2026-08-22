from datetime import timedelta

from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import common


@common.tagged("post_install", "-at_install", "web_unit", "web_save")
class TestWebSaveOptimisticLocking(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.c1 = cls.env["res.partner"].create(
            {"name": "Company 1", "is_company": True}
        )
        cls.c2 = cls.env["res.partner"].create(
            {"name": "Company 2", "is_company": True}
        )
        cls.c3 = cls.env["res.partner"].create(
            {"name": "Company 3", "is_company": True}
        )
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Base Partner",
                "phone": "111",
                "function": "f0",
                "parent_id": cls.c1.id,
            }
        )
        cls.env.flush_all()

    def _server_set(self, **col_vals):
        for col, val in col_vals.items():
            self.env.cr.execute(
                'UPDATE res_partner SET "%s" = %%s WHERE id = %%s' % col,
                (val, self.partner.id),
            )

    def test_no_concurrency_args(self):
        result = self.partner.web_save({"phone": "x"}, specification={"phone": {}})
        self.assertEqual(result[0]["phone"], "x")

    def test_create_ignores_locking(self):
        result = self.env["res.partner"].web_save(
            {"name": "New"},
            specification={"name": {}},
            known_values={"name": "anything"},
        )
        self.assertEqual(result[0]["name"], "New")

    def test_disjoint_change_does_not_conflict(self):
        self._server_set(function="changed-by-other")
        self.partner.web_save(
            {"phone": "222"},
            specification={"phone": {}},
            known_values={"phone": "111"},
        )
        self.assertEqual(self.partner.phone, "222")

    def test_same_field_conflict(self):
        self._server_set(phone="999")
        with self.assertRaises(UserError):
            self.partner.web_save(
                {"phone": "222"},
                specification={"phone": {}},
                known_values={"phone": "111"},
            )

    def test_same_field_same_value_no_conflict(self):
        self._server_set(phone="222")
        self.partner.web_save(
            {"phone": "222"},
            specification={"phone": {}},
            known_values={"phone": "111"},
        )
        self.assertEqual(self.partner.phone, "222")

    def test_many2one_conflict(self):
        self._server_set(parent_id=self.c2.id)
        with self.assertRaises(UserError):
            self.partner.web_save(
                {"parent_id": self.c3.id},
                specification={"parent_id": {}},
                known_values={
                    "parent_id": {"id": self.c1.id, "display_name": "Company 1"}
                },
            )

    def test_many2one_user_change_no_conflict(self):
        self.partner.web_save(
            {"parent_id": self.c3.id},
            specification={"parent_id": {}},
            known_values={"parent_id": {"id": self.c1.id, "display_name": "Company 1"}},
        )
        self.assertEqual(self.partner.parent_id, self.c3)

    def test_many2one_hidden_by_record_rule_fails_open(self):
        company_a, company_b = self.env["res.company"].create(
            [{"name": "Concurrency A"}, {"name": "Concurrency B"}]
        )
        hidden = self.env["res.partner"].create(
            {
                "name": "Hidden Parent",
                "is_company": True,
                "company_id": company_a.id,
            }
        )
        user = self.env["res.users"].create(
            {
                "name": "Concurrency User",
                "login": "concurrency_user",
                "company_id": company_b.id,
                "company_ids": [Command.set(company_b.ids)],
                "group_ids": [
                    Command.link(self.env.ref("base.group_user").id),
                    Command.link(self.env.ref("base.group_partner_manager").id),
                ],
            }
        )
        self.partner.parent_id = hidden
        self.env.flush_all()
        partner = self.partner.with_user(user)
        read_values = partner.web_read({"parent_id": {"fields": {"display_name": {}}}})
        self.assertFalse(
            read_values[0]["parent_id"],
            "the rule-hidden parent must be blanked on read, else the test "
            "no longer reproduces the baseline the client actually receives",
        )
        partner.web_save(
            {"parent_id": self.c3.id},
            specification={"parent_id": {}},
            known_values={"parent_id": False},
        )
        self.assertEqual(self.partner.parent_id, self.c3)

    def test_only_written_fields_are_checked(self):
        self._server_set(parent_id=self.c2.id)
        self.partner.web_save(
            {"phone": "222"},
            specification={"phone": {}},
            known_values={
                "phone": "111",
                "parent_id": {"id": self.c1.id, "display_name": "Company 1"},
            },
        )
        self.assertEqual(self.partner.phone, "222")

    def test_empty_known_values_skips_check(self):
        self._server_set(phone="999")
        self.partner.web_save(
            {"phone": "222"},
            specification={"phone": {}},
            known_values={},
        )
        self.assertEqual(self.partner.phone, "222")

    def test_translated_field_no_false_conflict(self):
        category = self.env["res.partner.category"].create({"name": "Original"})
        self.env.flush_all()
        self.assertTrue(category._fields["name"].translate)
        category.web_save(
            {"name": "Renamed"},
            specification={"name": {}},
            known_values={"name": "Original"},
        )
        self.assertEqual(category.name, "Renamed")

    def test_translated_field_fails_open(self):
        category = self.env["res.partner.category"].create({"name": "Original"})
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE res_partner_category SET name = %s WHERE id = %s",
            ('{"en_US": "Changed Elsewhere"}', category.id),
        )
        category.web_save(
            {"name": "Renamed"},
            specification={"name": {}},
            known_values={"name": "Original"},
        )
        self.assertEqual(category.name, "Renamed")

    def test_uncomparable_baseline_shape_fails_open(self):
        for baseline in ({"weird": 1}, ["a"], ("a",), {"a"}, b"a"):
            with self.subTest(baseline=baseline):
                self.partner.ref = "OLD"
                self.env.flush_all()
                self.partner.web_save(
                    {"ref": "MINE"},
                    specification={"ref": {}},
                    known_values={"ref": baseline},
                )
                self.assertEqual(self.partner.ref, "MINE")

    def test_uncomparable_baseline_still_detects_real_conflict(self):
        self.partner.write({"ref": "OLD", "function": "OLDFN"})
        self.env.flush_all()
        self._server_set(ref="CHANGED ELSEWHERE")
        with self.assertRaises(UserError):
            self.partner.web_save(
                {"ref": "MINE", "function": "MINEFN"},
                specification={"ref": {}},
                known_values={"ref": "OLD", "function": {"bad": "shape"}},
            )

    def test_scalar_baselines_still_compare(self):
        self.partner.ref = "OLD"
        self.env.flush_all()
        self._server_set(ref="CHANGED ELSEWHERE")
        with self.assertRaises(UserError):
            self.partner.web_save(
                {"ref": "MINE"},
                specification={"ref": {}},
                known_values={"ref": "OLD"},
            )

    def test_legacy_last_write_date_fallback(self):
        stale = self.partner.write_date - timedelta(seconds=10)
        self._server_set(write_date=self.partner.write_date + timedelta(seconds=5))
        with self.assertRaises(UserError):
            self.partner.web_save(
                {"phone": "222"},
                specification={"phone": {}},
                last_write_date=stale.isoformat(),
            )

    def test_multirecord_web_save_writes_all(self):
        recs = self.c1 + self.c2
        result = recs.web_save({"phone": "9"}, specification={"phone": {}})
        self.assertEqual([r["phone"] for r in result], ["9", "9"])
        self.assertEqual(recs.mapped("phone"), ["9", "9"])

    def test_multirecord_web_save_rejects_last_write_date(self):
        recs = self.c1 + self.c2
        with self.assertRaises(ValueError):
            recs.web_save(
                {"phone": "9"},
                specification={"phone": {}},
                last_write_date="2020-01-01T00:00:00.000Z",
            )

    def _server_set_on(self, record, **col_vals):
        for col, val in col_vals.items():
            self.env.cr.execute(
                'UPDATE res_partner SET "%s" = %%s WHERE id = %%s' % col,
                (val, record.id),
            )

    def test_multirecord_known_values_conflict(self):
        recs = self.c1 + self.c2 + self.c3
        self.c1.phone = self.c2.phone = self.c3.phone = "start"
        self.env.flush_all()
        self._server_set_on(self.c2, phone="999")
        with self.assertRaises(UserError):
            recs.web_save(
                {"phone": "new"},
                specification={"phone": {}},
                known_values={
                    self.c1.id: {"phone": "start"},
                    self.c2.id: {"phone": "start"},
                    self.c3.id: {"phone": "start"},
                },
            )
        self.env.cr.execute(
            "SELECT phone FROM res_partner WHERE id = %s", (self.c1.id,)
        )
        self.assertEqual(self.env.cr.fetchone()[0], "start")

    def test_multirecord_known_values_no_conflict(self):
        recs = self.c1 + self.c2
        result = recs.web_save(
            {"phone": "same"},
            specification={"phone": {}},
            known_values={
                self.c1.id: {"phone": self.c1.phone or False},
                self.c2.id: {"phone": self.c2.phone or False},
            },
        )
        self.assertEqual([r["phone"] for r in result], ["same", "same"])

    def test_multirecord_disjoint_change_no_conflict(self):
        recs = self.c1 + self.c2
        self._server_set_on(self.c2, function="changed-by-other")
        recs.web_save(
            {"phone": "999"},
            specification={"phone": {}},
            known_values={
                self.c1.id: {"phone": self.c1.phone or False},
                self.c2.id: {"phone": self.c2.phone or False},
            },
        )
        self.assertEqual(recs.mapped("phone"), ["999", "999"])

    def test_multirecord_missing_baseline_fails_open(self):
        recs = self.c1 + self.c2
        self._server_set_on(self.c2, phone="concurrent")
        recs.web_save(
            {"phone": "999"},
            specification={"phone": {}},
            known_values={self.c1.id: {"phone": self.c1.phone or False}},
        )
        self.assertEqual(recs.mapped("phone"), ["999", "999"])

    def test_multirecord_same_value_no_conflict(self):
        recs = self.c1 + self.c2
        self._server_set_on(self.c2, phone="target")
        result = recs.web_save(
            {"phone": "target"},
            specification={"phone": {}},
            known_values={
                self.c1.id: {"phone": self.c1.phone or False},
                self.c2.id: {"phone": "old"},
            },
        )
        self.assertEqual([r["phone"] for r in result], ["target", "target"])

    def test_single_selected_row_massedit_still_checked(self):
        self._server_set_on(self.c1, phone="999")
        with self.assertRaises(UserError):
            self.c1.web_save(
                {"phone": "new"},
                specification={"phone": {}},
                known_values={self.c1.id: {"phone": "start"}},
            )
        self.env.cr.execute(
            "SELECT phone FROM res_partner WHERE id = %s", (self.c1.id,)
        )
        self.assertEqual(self.env.cr.fetchone()[0], "999")

    def test_single_selected_row_massedit_no_false_conflict(self):
        self.c1.phone = "start"
        self.env.flush_all()
        result = self.c1.web_save(
            {"phone": "new"},
            specification={"phone": {}},
            known_values={self.c1.id: {"phone": "start"}},
        )
        self.assertEqual(result[0]["phone"], "new")

    def test_web_save_multi_writes_all_no_locking(self):
        recs = self.c1 + self.c2
        result = recs.web_save_multi(
            [{"phone": "a1"}, {"phone": "a2"}],
            specification={"phone": {}},
        )
        self.assertEqual([r["phone"] for r in result], ["a1", "a2"])
        self.assertEqual(recs.mapped("phone"), ["a1", "a2"])

    def test_web_save_multi_per_record_no_conflict(self):
        recs = self.c1 + self.c2
        result = recs.web_save_multi(
            [{"phone": "a1"}, {"phone": "a2"}],
            specification={"phone": {}},
            known_values={
                self.c1.id: {"phone": self.c1.phone or False},
                self.c2.id: {"phone": self.c2.phone or False},
            },
        )
        self.assertEqual([r["phone"] for r in result], ["a1", "a2"])

    def test_web_save_multi_per_record_conflict(self):
        recs = self.c1 + self.c2
        self.c1.phone = self.c2.phone = "start"
        self.env.flush_all()
        self._server_set_on(self.c2, phone="999")
        with self.assertRaises(UserError):
            recs.web_save_multi(
                [{"phone": "a1"}, {"phone": "a2"}],
                specification={"phone": {}},
                known_values={
                    self.c1.id: {"phone": "start"},
                    self.c2.id: {"phone": "start"},
                },
            )
        self.env.cr.execute(
            "SELECT phone FROM res_partner WHERE id = %s", (self.c1.id,)
        )
        self.assertEqual(self.env.cr.fetchone()[0], "start")

    def test_web_save_multi_same_value_no_conflict(self):
        recs = self.c1 + self.c2
        self._server_set_on(self.c2, phone="a2")
        result = recs.web_save_multi(
            [{"phone": "a1"}, {"phone": "a2"}],
            specification={"phone": {}},
            known_values={
                self.c1.id: {"phone": self.c1.phone or False},
                self.c2.id: {"phone": "old"},
            },
        )
        self.assertEqual([r["phone"] for r in result], ["a1", "a2"])

    def test_stale_field_in_vals_raises_usererror(self):
        with self.assertRaises(UserError):
            self.partner.web_save(
                {"phone": "222", "stale_field_zz": 1},
                specification={"phone": {}},
            )
        with self.assertRaises(UserError):
            self.env["res.partner"].web_save(
                {"name": "New", "stale_field_zz": 1},
                specification={"name": {}},
            )
        self.env.cr.execute(
            "SELECT phone FROM res_partner WHERE id = %s", (self.partner.id,)
        )
        self.assertEqual(self.env.cr.fetchone()[0], "111")

    def test_x2many_virtual_command_id_raises_usererror(self):
        with self.assertRaises(UserError):
            self.partner.web_save(
                {"child_ids": [[1, "virtual_zz", {"name": "x"}]]},
                specification={"id": {}},
            )
        with self.assertRaises(UserError):
            self.partner.web_save(
                {"category_id": [[6, False, ["virtual_1"]]]},
                specification={"id": {}},
            )
        result = self.partner.web_save(
            {"child_ids": [[0, "virtual_ok", {"name": "WS Cmd Child"}]]},
            specification={"child_ids": {"fields": {"name": {}}}},
        )
        self.assertIn("WS Cmd Child", [c["name"] for c in result[0]["child_ids"]])

    def test_web_save_multi_missing_baseline_fails_open(self):
        recs = self.c1 + self.c2
        self._server_set_on(self.c2, phone="concurrent")
        recs.web_save_multi(
            [{"phone": "a1"}, {"phone": "a2"}],
            specification={"phone": {}},
            known_values={self.c1.id: {"phone": self.c1.phone or False}},
        )
        self.assertEqual(recs.mapped("phone"), ["a1", "a2"])
