from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase


class TestWriteGroups(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_group = cls.env.ref("test_access_rights.test_group")
        cls.plain_user = cls._new_user("plain")
        cls.gated_user = cls._new_user("gated", cls.test_group)
        cls.record = cls.env["test_access_right.some_obj"].create({"val": 1})

    @classmethod
    def _new_user(cls, login, *groups):
        return cls.env["res.users"].create(
            {
                "login": login,
                "name": login,
                "group_ids": [
                    Command.set(
                        [cls.env.ref("base.group_user").id]
                        + [group.id for group in groups]
                    )
                ],
            }
        )

    def test_write_denied_without_the_group(self):
        with self.assertRaises(AccessError):
            self.record.with_user(self.plain_user).write({"write_gated": 2})

    def test_write_allowed_with_the_group(self):
        record = self.record.with_user(self.gated_user)
        record.write({"write_gated": 2})
        self.assertEqual(record.write_gated, 2)

    def test_attribute_assignment_is_gated_too(self):
        record = self.record.with_user(self.plain_user)
        with self.assertRaises(AccessError):
            record.write_gated = 2

    def test_attribute_assignment_on_many_records_is_gated_too(self):
        others = self.env["test_access_right.some_obj"].create([{"val": 2}, {"val": 3}])
        with self.assertRaises(AccessError):
            others.with_user(self.plain_user).write_gated = 2

    def test_a_field_default_does_not_trip_the_gate(self):
        created = (
            self.env["test_access_right.some_obj"]
            .with_user(self.plain_user)
            .create({"val": 9})
        )
        self.assertEqual(created.val, 9)

    def test_a_context_default_does_trip_the_gate(self):
        model = self.env["test_access_right.some_obj"].with_user(self.plain_user)
        with self.assertRaises(AccessError):
            model.with_context(default_write_gated=3).create({"val": 1})

    def test_create_denied_without_the_group(self):
        with self.assertRaises(AccessError):
            self.env["test_access_right.some_obj"].with_user(self.plain_user).create(
                {"write_gated": 2}
            )

    def test_read_stays_allowed_without_the_group(self):
        self.assertEqual(self.record.with_user(self.plain_user).write_gated, 0)

    def test_ungated_field_stays_writable(self):
        record = self.record.with_user(self.plain_user)
        record.write({"val": 5})
        self.assertEqual(record.val, 5)

    def test_sudo_bypasses_the_gate(self):
        self.record.with_user(self.plain_user).sudo().write({"write_gated": 3})
        self.assertEqual(self.record.write_gated, 3)

    def test_no_access_spec_denies_everyone(self):
        with self.assertRaises(AccessError):
            self.record.with_user(self.gated_user).write({"write_gated_never": 1})

    def test_read_groups_deny_before_write_groups_are_consulted(self):
        record = self.record.with_user(self.plain_user)
        record.check_access("read")
        with self.assertRaises(AccessError):
            record.read(["read_and_write_gated"])

    def test_write_groups_deny_a_field_whose_read_groups_admit(self):
        record = self.record.with_user(self.gated_user)
        self.assertEqual(record.read(["read_and_write_gated"])[0]["id"], record.id)
        with self.assertRaises(AccessError):
            record.write({"read_and_write_gated": 1})

    def test_both_specs_satisfied_allows_the_write(self):
        user = self._new_user(
            "both", self.test_group, self.env.ref("base.group_system")
        )
        record = self.record.with_user(user)
        record.write({"read_and_write_gated": 4})
        self.assertEqual(record.read_and_write_gated, 4)

    def test_fields_get_reports_readonly_without_the_group(self):
        description = (
            self.env["test_access_right.some_obj"]
            .with_user(self.plain_user)
            .fields_get(["write_gated", "val"], ["readonly"])
        )
        self.assertTrue(description["write_gated"]["readonly"])
        self.assertFalse(description["val"]["readonly"])

    def test_fields_get_reports_writable_with_the_group(self):
        description = (
            self.env["test_access_right.some_obj"]
            .with_user(self.gated_user)
            .fields_get(["write_gated"], ["readonly"])
        )
        self.assertFalse(description["write_gated"]["readonly"])

    def test_predicate_receives_the_records_being_written(self):
        seen = []
        field = self.env["test_access_right.some_obj"]._fields["write_gated_on_stored"]
        original = field.write_groups
        field.write_groups = lambda records: seen.append(records) or True
        try:
            self.record.with_user(self.plain_user).write({"write_gated_on_stored": 1})
        finally:
            field.write_groups = original
        self.assertEqual(seen, [self.record.with_user(self.plain_user)])

    def test_predicate_can_allow_create_and_deny_write(self):
        model = self.env["test_access_right.some_obj"].with_user(self.plain_user)
        created = model.create({"write_gated_on_stored": 1})
        self.assertEqual(created.write_gated_on_stored, 1)
        with self.assertRaises(AccessError):
            created.write({"write_gated_on_stored": 2})

    def test_fields_get_calls_the_predicate_with_an_empty_recordset(self):
        seen = []
        field = self.env["test_access_right.some_obj"]._fields["write_gated_on_stored"]
        original = field.write_groups
        field.write_groups = lambda records: seen.append(records) or True
        try:
            self.env["test_access_right.some_obj"].with_user(
                self.plain_user
            ).fields_get(["write_gated_on_stored"], ["readonly"])
        finally:
            field.write_groups = original
        self.assertEqual(len(seen), 1)
        self.assertFalse(seen[0].ids)
        self.assertEqual(seen[0]._name, "test_access_right.some_obj")

    def test_predicate_honours_the_group(self):
        record = self.record.with_user(self.gated_user)
        record.write({"write_gated_on_stored": 7})
        self.assertEqual(record.write_gated_on_stored, 7)

    def test_gate_propagates_to_a_delegated_field(self):
        field = self.env["test_access_right.inherits"]._fields["write_gated"]
        self.assertTrue(field.inherited)
        self.assertEqual(field.write_groups, "test_access_rights.test_group")
        delegate = self.env["test_access_right.inherits"].create(
            {"some_id": self.record.id}
        )
        with self.assertRaises(AccessError):
            delegate.with_user(self.plain_user).write({"write_gated": 4})

    def test_error_names_the_write_groups(self):
        user = self.gated_user
        user.group_ids -= self.test_group
        user.group_ids += self.env.ref("base.group_no_one")
        with self.assertRaises(AccessError) as capture:
            self.record.with_user(user).write({"write_gated": 2})
        self.assertIn("write allowed for groups 'Test Group'", str(capture.exception))

    def test_no_access_sentinel_is_reusable_for_writes(self):
        field = self.env["test_access_right.some_obj"]._fields["write_gated_never"]
        self.assertEqual(field.write_groups, fields.NO_ACCESS)
