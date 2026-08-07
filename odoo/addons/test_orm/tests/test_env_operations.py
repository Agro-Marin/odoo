from odoo.tests.common import TransactionCase


class TestSudo(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Category = cls.env["test_orm.category"]
        cls.cat = cls.Category.create({"name": "Sudo Cat"})
        cls.admin_user = cls.env.ref("base.user_admin")

    def test_sudo_enables_su(self):
        record = self.cat.with_user(self.admin_user).sudo()
        self.assertTrue(record.env.su)

    def test_sudo_preserves_user(self):
        record = self.cat.with_user(self.admin_user)
        sudo_record = record.sudo()
        self.assertEqual(sudo_record.env.uid, self.admin_user.id)
        self.assertTrue(sudo_record.env.su)

    def test_sudo_false_reverts(self):
        record = self.cat.with_user(self.admin_user).sudo()
        self.assertTrue(record.env.su)
        record2 = record.sudo(False)
        self.assertFalse(record2.env.su)

    def test_sudo_idempotent(self):
        record = self.cat.with_user(self.admin_user).sudo()
        record2 = record.sudo()
        self.assertIs(record, record2)

    def test_sudo_false_idempotent(self):
        record = self.cat.with_user(self.admin_user)
        self.assertFalse(record.env.su)
        record2 = record.sudo(False)
        self.assertIs(record, record2)


class TestWithUser(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin_user = cls.env.ref("base.user_admin")
        cls.cat = cls.env["test_orm.category"].create({"name": "User Cat"})

    def test_with_user_changes_uid(self):
        record = self.cat.with_user(self.admin_user)
        self.assertEqual(record.env.uid, self.admin_user.id)

    def test_with_user_disables_su(self):
        record = self.cat.sudo().with_user(self.admin_user)
        self.assertFalse(record.env.su)

    def test_with_user_preserves_records(self):
        record = self.cat.with_user(self.admin_user)
        self.assertEqual(record.id, self.cat.id)
        self.assertEqual(record.name, "User Cat")

    def test_with_user_false_noop(self):
        record = self.cat.with_user(False)
        self.assertEqual(record.env.uid, self.cat.env.uid)

    def test_with_user_chain(self):
        current_user = self.env.user
        record = self.cat.with_user(self.admin_user).with_user(current_user)
        self.assertEqual(record.env.uid, current_user.id)


class TestWithContext(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cat = cls.env["test_orm.category"].create({"name": "Ctx Cat"})

    def test_with_context_add(self):
        record = self.cat.with_context(custom_key="custom_value")
        self.assertEqual(record.env.context.get("custom_key"), "custom_value")

    def test_with_context_preserves_existing(self):
        record = self.cat.with_context(key1="v1")
        record2 = record.with_context(key2="v2")
        self.assertEqual(record2.env.context.get("key1"), "v1")
        self.assertEqual(record2.env.context.get("key2"), "v2")

    def test_with_context_replace(self):
        record = self.cat.with_context(key1="v1")
        record2 = record.with_context({}, key2="v2")
        self.assertNotIn("key1", record2.env.context)
        self.assertEqual(record2.env.context.get("key2"), "v2")

    def test_with_context_preserves_records(self):
        record = self.cat.with_context(custom=True)
        self.assertEqual(record.id, self.cat.id)
        self.assertEqual(record.name, "Ctx Cat")

    def test_with_context_preserves_allowed_company_ids(self):
        company_ids = [1, 2, 3]
        record = self.cat.with_context(allowed_company_ids=company_ids)
        record2 = record.with_context({}, custom=True)
        self.assertEqual(record2.env.context.get("allowed_company_ids"), company_ids)

    def test_with_context_override_value(self):
        record = self.cat.with_context(key="old")
        record2 = record.with_context(key="new")
        self.assertEqual(record2.env.context.get("key"), "new")


class TestWithCompany(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cat = cls.env["test_orm.category"].create({"name": "Company Cat"})
        cls.main_company = cls.env.ref("base.main_company")

    def test_with_company(self):
        record = self.cat.with_company(self.main_company)
        allowed = record.env.context.get("allowed_company_ids", [])
        self.assertIn(self.main_company.id, allowed)
        self.assertEqual(allowed[0], self.main_company.id)

    def test_with_company_false_noop(self):
        record = self.cat.with_company(False)
        self.assertEqual(record.env.context, self.cat.env.context)

    def test_with_company_idempotent(self):
        record = self.cat.with_company(self.main_company)
        record2 = record.with_company(self.main_company)
        self.assertIs(record, record2)


class TestWithPrefetch(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Category = cls.env["test_orm.category"]
        cls.cats = Category.create([{"name": f"PF{i}"} for i in range(5)])

    def test_with_prefetch_default(self):
        subset = self.cats[:2]
        record = subset.with_prefetch()
        self.assertEqual(tuple(record._prefetch_ids), subset._ids)

    def test_with_prefetch_custom(self):
        subset = self.cats[:2]
        all_ids = self.cats._ids
        record = subset.with_prefetch(all_ids)
        self.assertEqual(record._prefetch_ids, all_ids)
        self.assertEqual(record._ids, subset._ids)

    def test_with_prefetch_preserves_env(self):
        record = self.cats[:1].with_prefetch(self.cats._ids)
        self.assertEqual(record.env, self.cats.env)


class TestEnsureOne(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Category = cls.env["test_orm.category"]
        cls.cat = Category.create({"name": "Single Cat"})
        cls.cats = Category.create([{"name": f"Multi{i}"} for i in range(3)])

    def test_ensure_one_singleton(self):
        result = self.cat.ensure_one()
        self.assertIs(result, self.cat)

    def test_ensure_one_empty(self):
        empty = self.env["test_orm.category"]
        with self.assertRaises(ValueError):
            empty.ensure_one()

    def test_ensure_one_multi(self):
        with self.assertRaises(ValueError):
            self.cats.ensure_one()


class TestEnvironmentProperties(TransactionCase):
    def test_env_user(self):
        user = self.env.user
        self.assertEqual(user._name, "res.users")
        self.assertEqual(user.id, self.env.uid)

    def test_env_company(self):
        company = self.env.company
        self.assertEqual(company._name, "res.company")
        self.assertTrue(company)

    def test_env_registry_access(self):
        Category = self.env["test_orm.category"]
        self.assertEqual(Category._name, "test_orm.category")
        self.assertFalse(Category)

    def test_env_cr(self):
        self.assertIsNotNone(self.env.cr)

    def test_env_uid(self):
        self.assertIsInstance(self.env.uid, int)
        self.assertTrue(self.env.uid > 0)


class TestExists(TransactionCase):
    def test_exists_all_present(self):
        cats = self.env["test_orm.category"].create(
            [{"name": f"Exists{i}"} for i in range(3)]
        )
        result = cats.exists()
        self.assertEqual(result, cats)

    def test_exists_filters_deleted(self):
        cat1 = self.env["test_orm.category"].create({"name": "Keep"})
        cat2 = self.env["test_orm.category"].create({"name": "Delete"})
        both = cat1 | cat2
        cat2.unlink()
        result = both.exists()
        self.assertEqual(result, cat1)

    def test_exists_empty(self):
        empty = self.env["test_orm.category"]
        result = empty.exists()
        self.assertFalse(result)

    def test_exists_all_deleted(self):
        cat = self.env["test_orm.category"].create({"name": "Gone"})
        cat.unlink()
        result = cat.exists()
        self.assertFalse(result)


class TestNewRecords(TransactionCase):
    def test_new_basic(self):
        Category = self.env["test_orm.category"]
        record = Category.new({"name": "Virtual"})
        self.assertEqual(record.name, "Virtual")
        self.assertFalse(record.id)

    def test_new_with_origin(self):
        cat = self.env["test_orm.category"].create({"name": "Original"})
        virtual = self.env["test_orm.category"].new({"name": "Modified"}, origin=cat)
        self.assertFalse(virtual.id)
        self.assertEqual(virtual._origin, cat)

    def test_new_with_ref(self):
        Category = self.env["test_orm.category"]
        rec1 = Category.new({"name": "A"}, ref="ref1")
        rec2 = Category.new({"name": "B"}, ref="ref1")
        self.assertEqual(rec1.id, rec2.id)

    def test_origin_real_records(self):
        cat = self.env["test_orm.category"].create({"name": "Real"})
        self.assertEqual(cat._origin, cat)
