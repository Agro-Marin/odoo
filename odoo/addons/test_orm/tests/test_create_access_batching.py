from odoo.tests import TransactionCase


class CreateAccessBatchingCase(TransactionCase):
    """``create()`` must not check record access once per record.

    A ``bypass_search_access`` many2one made ``create()`` call
    ``check_access("read")`` on the comodel once per value, each on a
    one-record recordset. With any ``ir.rule`` on the comodel that costs one
    SELECT per record, because a recordset of one has nothing to prefetch with.

    Asserted as a *marginal* cost -- N=2 against N=200 -- because an absolute
    query count at N=1 cannot see this class of defect at all.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env["res.users"].create(
            {
                "name": "Bypass Tester",
                "login": "bypass_tester",
                "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
            }
        )
        cls.targets = cls.env["test_orm.bypass.target"].create(
            [{"name": f"t{i}"} for i in range(200)]
        )
        cls.env["ir.rule"].create(
            {
                "name": "bypass target rule",
                "model_id": cls.env["ir.model"]._get("test_orm.bypass.target").id,
                "domain_force": "[('name', '!=', 'nope')]",
                "groups": [(6, 0, [cls.env.ref("base.group_user").id])],
                "perm_read": True,
                "perm_write": False,
                "perm_create": False,
                "perm_unlink": False,
            }
        )
        cls.env.flush_all()

    def _create_as_user(self, fname, count):
        holder = self.env["test_orm.bypass.holder"].with_user(self.user)
        self.env.invalidate_all()
        before = self.env.cr.sql_log_count
        holder.create(
            [{"name": f"h{i}", fname: self.targets[i].id} for i in range(count)]
        )
        self.env.flush_all()
        return self.env.cr.sql_log_count - before

    def _warm(self):
        # ir.model.access / ir.rule are ormcached; a first call through either
        # field pays for filling them, which would land on whichever arm runs
        # first rather than on the thing under test.
        self._create_as_user("target_id", 1)
        self._create_as_user("plain_target_id", 1)

    def test_the_access_check_does_not_scale_with_the_batch(self):
        self._warm()
        small = self._create_as_user("target_id", 2)
        large = self._create_as_user("target_id", 200)
        self.assertLess(
            large - small,
            50,
            f"create() cost {large} queries for 200 records against {small} for 2; "
            f"the bypass_search_access check is being made once per record",
        )

    def test_it_costs_what_a_plain_many2one_costs(self):
        self._warm()
        bypass = self._create_as_user("target_id", 200)
        plain = self._create_as_user("plain_target_id", 200)
        self.assertLessEqual(
            bypass - plain,
            5,
            f"a bypass_search_access many2one cost {bypass} queries where a plain "
            f"one cost {plain}; the access check is not batched",
        )

    def test_a_forbidden_target_is_still_refused(self):
        from odoo.exceptions import AccessError

        forbidden = self.env["test_orm.bypass.target"].create({"name": "nope"})
        self.env.flush_all()
        holder = self.env["test_orm.bypass.holder"].with_user(self.user)
        with self.assertRaises(AccessError):
            holder.create(
                [
                    {"name": "ok", "target_id": self.targets[0].id},
                    {"name": "bad", "target_id": forbidden.id},
                ]
            )

    def test_a_falsy_value_still_checks_model_access(self):
        holder = self.env["test_orm.bypass.holder"].with_user(self.user)
        records = holder.create([{"name": "n", "target_id": False}])
        self.assertTrue(records)
