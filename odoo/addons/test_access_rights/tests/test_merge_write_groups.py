from odoo import Command
from odoo.tests.common import TransactionCase


class TestMergeWriteGroups(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plain_user = cls._new_user("merge_plain")
        cls.gated_user = cls._new_user(
            "merge_gated", cls.env.ref("test_access_rights.test_group")
        )

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

    def _merge_as(self, user):
        Obj = self.env["test_access_right.some_obj"]
        src = Obj.create({"val": 3, "write_gated": 5, "write_gated_on_stored": 6})
        dst = Obj.create({"val": 0})
        merger = self.env["mixin.merge"].with_user(user)
        merger._update_values_generic(src.with_user(user), dst.with_user(user))
        dst.invalidate_recordset()
        return dst

    def test_merge_keeps_the_destination_value_of_a_field_the_user_may_not_write(
        self,
    ):
        dst = self._merge_as(self.plain_user)

        self.assertEqual(dst.val, 3)
        self.assertEqual(dst.write_gated, 0)
        self.assertEqual(dst.write_gated_on_stored, 0)

    def test_merge_fills_a_gated_field_the_user_may_write(self):
        dst = self._merge_as(self.gated_user)

        self.assertEqual(
            (dst.val, dst.write_gated, dst.write_gated_on_stored), (3, 5, 6)
        )
