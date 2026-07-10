from odoo import Command
from odoo.exceptions import AccessError, LockError
from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger


class TestORM(TransactionCase):
    """test special behaviors of ORM CRUD functions"""

    @mute_logger("odoo.models")
    def test_access_deleted_records(self):
        """Verify that accessing deleted records works as expected"""
        c1 = self.env["res.partner.category"].create({"name": "W"})
        c2 = self.env["res.partner.category"].create({"name": "Y"})
        c1.unlink()

        # read() skips deleted records: the search()->read() sequence is not
        # transactional client-side, so a concurrent deletion must not raise
        # (e.g. when simply opening a list view).
        # /!\ unprivileged user, to catch former side effects of ir.rules!
        user = self.env["res.users"].create(
            {
                "name": "test user",
                "login": "test2",
                "group_ids": [Command.set([self.ref("base.group_user")])],
            }
        )
        cs = (c1 + c2).with_user(user)
        self.assertEqual(
            [{"id": c2.id, "name": "Y"}],
            cs.read(["name"]),
            "read() should skip deleted records",
        )
        self.assertEqual([], cs[0].read(["name"]), "read() should skip deleted records")

        # Deleting an already deleted record should be simply ignored
        self.assertTrue(c1.unlink(), "Re-deleting should be a no-op")

    @mute_logger("odoo.models")
    def test_access_partial_deletion(self):
        """Check accessing a record from a recordset where another record has been deleted."""
        Model = self.env["res.country"]
        display_name_field = Model._fields["display_name"]
        self.assertTrue(
            display_name_field.compute and not display_name_field.store,
            "test assumption not satisfied",
        )

        # access regular field when another record from the same prefetch set has been deleted
        records = Model.create(
            [
                {"name": name[0], "code": name[1]}
                for name in (["Foo", "ZV"], ["Bar", "ZX"], ["Baz", "ZY"])
            ]
        )
        for record in records:
            _ = record.name
            record.unlink()

        # access computed field when another record from the same prefetch set has been deleted
        records = Model.create(
            [
                {"name": name[0], "code": name[1]}
                for name in (["Foo", "ZV"], ["Bar", "ZX"], ["Baz", "ZY"])
            ]
        )
        for record in records:
            _ = record.display_name
            record.unlink()

    @mute_logger("odoo.models", "odoo.addons.base.models.ir_rule")
    def test_access_filtered_records(self):
        """Verify that accessing filtered records works as expected for non-admin user"""
        p1 = self.env["res.partner"].create({"name": "W"})
        p2 = self.env["res.partner"].create({"name": "Y"})
        user = self.env["res.users"].create(
            {
                "name": "test user",
                "login": "test2",
                "group_ids": [Command.set([self.ref("base.group_user")])],
            }
        )

        partner_model = self.env["ir.model"].search([("model", "=", "res.partner")])
        self.env["ir.rule"].create(
            {
                "name": "Y is invisible",
                "domain_force": [("id", "!=", p1.id)],
                "model_id": partner_model.id,
            }
        )

        # search as unprivileged user
        partners = self.env["res.partner"].with_user(user).search([])
        self.assertNotIn(p1, partners, "W should not be visible...")
        self.assertIn(p2, partners, "... but Y should be visible")

        # read as unprivileged user
        with self.assertRaises(AccessError):
            p1.with_user(user).read(["name"])
        # write as unprivileged user
        with self.assertRaises(AccessError):
            p1.with_user(user).write({"name": "foo"})
        # unlink as unprivileged user
        with self.assertRaises(AccessError):
            p1.with_user(user).unlink()

        # Prepare mixed case
        p2.unlink()
        # read mixed records: some deleted and some filtered
        with self.assertRaises(AccessError):
            (p1 + p2).with_user(user).read(["name"])
        # delete mixed records: some deleted and some filtered
        with self.assertRaises(AccessError):
            (p1 + p2).with_user(user).unlink()

    def test_read(self):
        partner = self.env["res.partner"].create({"name": "MyPartner1"})
        result = partner.read()
        self.assertIsInstance(result, list)

    @mute_logger("odoo.models")
    def test_search_read(self):
        partner = self.env["res.partner"]

        # simple search_read
        partner.create({"name": "MyPartner1"})
        found = partner.search_read([("name", "=", "MyPartner1")], ["name"])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["name"], "MyPartner1")
        self.assertIn("id", found[0])

        # search_read correct order
        partner.create({"name": "MyPartner2"})
        found = partner.search_read(
            [("name", "like", "MyPartner")], ["name"], order="name"
        )
        self.assertEqual(len(found), 2)
        self.assertEqual(found[0]["name"], "MyPartner1")
        self.assertEqual(found[1]["name"], "MyPartner2")
        found = partner.search_read(
            [("name", "like", "MyPartner")], ["name"], order="name desc"
        )
        self.assertEqual(len(found), 2)
        self.assertEqual(found[0]["name"], "MyPartner2")
        self.assertEqual(found[1]["name"], "MyPartner1")

        # search_read that finds nothing
        found = partner.search_read([("name", "=", "Does not exists")], ["name"])
        self.assertEqual(len(found), 0)

        # search_read with an empty array of fields
        found = partner.search_read([], [], limit=1)
        self.assertEqual(len(found), 1)
        for field in ("id", "name", "display_name", "email"):
            self.assertIn(field, found[0])

        # search_read without fields
        found = partner.search_read([], False, limit=1)
        self.assertEqual(len(found), 1)
        for field in ("id", "name", "display_name", "email"):
            self.assertIn(field, found[0])

    @mute_logger("odoo.db")
    def test_exists(self):
        partner = self.env["res.partner"]

        # check that records obtained from search exist
        recs = partner.search([])
        self.assertTrue(recs)
        self.assertEqual(recs.exists(), recs)

        # check that new records exist by convention
        recs = partner.new({})
        self.assertTrue(recs.exists())

        # check that there is no record with id 0
        recs = partner.browse([0])
        self.assertFalse(recs.exists())

    def test_lock_for_update(self):
        partner = self.env["res.partner"]
        p1, p2 = partner.search([], limit=2)

        # lock p1
        p1.lock_for_update(allow_referencing=True)
        p1.lock_for_update(allow_referencing=False)

        with self.env.registry.cursor() as cr:
            recs = (p1 + p2).with_env(partner.env(cr=cr))
            with self.assertRaises(LockError):
                recs.lock_for_update()
            sub_p2 = recs[1]
            sub_p2.lock_for_update()

            # parent transaction and read, but cannot lock the p2 records
            p2.invalidate_model()
            self.assertTrue(p2.name)
            with self.assertRaises(LockError):
                p2.lock_for_update()

            # can still read from parent after locks and lock failures
            p1.invalidate_model()
            self.assertTrue(p1.name)

        # can lock p2 now
        p2.lock_for_update()

        # cannot lock inexisting record
        inexisting = partner.create({"name": "inexisting"})
        inexisting.unlink()
        self.assertFalse(inexisting.exists())
        with self.assertRaises(LockError):
            inexisting.lock_for_update()

    def test_try_lock_for_update(self):
        partner = self.env["res.partner"]
        p1, p2, *_other = recs = partner.search([], limit=4)

        # lock p1
        self.assertEqual(p1.try_lock_for_update(allow_referencing=True), p1)
        self.assertEqual(p1.try_lock_for_update(allow_referencing=False), p1)

        with self.env.registry.cursor() as cr:
            sub_recs = (p1 + p2).with_env(partner.env(cr=cr))
            self.assertEqual(sub_recs.try_lock_for_update(), sub_recs[1])

        self.assertEqual(recs.try_lock_for_update(limit=1), p1)
        self.assertEqual(recs.try_lock_for_update(), recs)

        # check that order is preserved when limiting
        self.assertEqual(recs[::-1].try_lock_for_update(limit=1), recs[-1])

    def test_write_duplicate(self):
        p1 = self.env["res.partner"].create({"name": "W"})
        (p1 + p1).write({"name": "X"})

    def test_m2m_store_trigger(self):
        group_user = self.env.ref("base.group_user")

        user = self.env["res.users"].create(
            {
                "name": "test",
                "login": "test_m2m_store_trigger",
                "group_ids": [Command.set([])],
            }
        )
        self.assertTrue(user.share)

        group_user.write({"user_ids": [Command.link(user.id)]})
        self.assertFalse(user.share)

        group_user.write({"user_ids": [Command.unlink(user.id)]})
        self.assertTrue(user.share)

    def test_create_multi(self):
        """create for multiple records"""
        # assumption: 'res.bank' does not override 'create'
        vals_list = [{"name": name} for name in ("Foo", "Bar", "Baz")]
        vals_list[0]["email"] = "foo@example.com"
        for vals in vals_list:
            record = self.env["res.bank"].create(vals)
            self.assertEqual(len(record), 1)
            self.assertEqual(record.name, vals["name"])
            self.assertEqual(record.email, vals.get("email", False))

        records = self.env["res.bank"].create([])
        self.assertFalse(records)

        records = self.env["res.bank"].create(vals_list)
        self.assertEqual(len(records), len(vals_list))
        for record, vals in zip(records, vals_list, strict=False):
            self.assertEqual(record.name, vals["name"])
            self.assertEqual(record.email, vals.get("email", False))

        # create countries and states
        vals_list = [
            {
                "name": "Foo",
                "state_ids": [
                    Command.create({"name": "North Foo", "code": "NF"}),
                    Command.create({"name": "South Foo", "code": "SF"}),
                    Command.create({"name": "West Foo", "code": "WF"}),
                    Command.create({"name": "East Foo", "code": "EF"}),
                ],
                "code": "ZV",
            },
            {
                "name": "Bar",
                "state_ids": [
                    Command.create({"name": "North Bar", "code": "NB"}),
                    Command.create({"name": "South Bar", "code": "SB"}),
                ],
                "code": "ZX",
            },
        ]
        foo, bar = self.env["res.country"].create(vals_list)
        self.assertEqual(foo.name, "Foo")
        self.assertCountEqual(foo.mapped("state_ids.code"), ["NF", "SF", "WF", "EF"])
        self.assertEqual(bar.name, "Bar")
        self.assertCountEqual(bar.mapped("state_ids.code"), ["NB", "SB"])


class TestInherits(TransactionCase):
    """test the orm on models that use _inherits, e.g. res.users -> res.partner"""

    def test_default(self):
        """`default_get` cannot return a dictionary or a new id"""
        defaults = self.env["res.users"].default_get(["partner_id"])
        if "partner_id" in defaults:
            self.assertIsInstance(defaults["partner_id"], (bool, int))

    def test_create(self):
        """creating a user should automatically create a new partner"""
        partners_before = self.env["res.partner"].search([])
        user_foo = self.env["res.users"].create({"name": "Foo", "login": "foo"})

        self.assertNotIn(user_foo.partner_id, partners_before)

    def test_create_with_ancestor(self):
        """creating a user with a specific 'partner_id' should not create a new partner"""
        partner_foo = self.env["res.partner"].create({"name": "Foo"})
        partners_before = self.env["res.partner"].search([])
        user_foo = self.env["res.users"].create(
            {"partner_id": partner_foo.id, "login": "foo"}
        )
        partners_after = self.env["res.partner"].search([])

        self.assertEqual(partners_before, partners_after)
        self.assertEqual(user_foo.name, "Foo")
        self.assertEqual(user_foo.partner_id, partner_foo)

    @mute_logger("odoo.models")
    def test_read(self):
        """inherited fields should be read without any indirection"""
        user_foo = self.env["res.users"].create({"name": "Foo", "login": "foo"})
        (user_values,) = user_foo.read()
        (partner_values,) = user_foo.partner_id.read()

        self.assertEqual(user_values["name"], partner_values["name"])
        self.assertEqual(user_foo.name, user_foo.partner_id.name)

    @mute_logger("odoo.models")
    def test_copy(self):
        """copying a user should automatically copy its partner, too"""
        user_foo = self.env["res.users"].create(
            {
                "name": "Foo",
                "login": "foo",
                "employee": True,
            }
        )
        (foo_before,) = user_foo.read()
        del foo_before["create_date"]
        del foo_before["write_date"]
        user_bar = user_foo.copy({"login": "bar"})
        (foo_after,) = user_foo.read()
        del foo_after["create_date"]
        del foo_after["write_date"]
        self.assertEqual(foo_before, foo_after)

        self.assertEqual(user_bar.name, "Foo (copy)")
        self.assertEqual(user_bar.login, "bar")
        self.assertEqual(user_foo.employee, user_bar.employee)
        self.assertNotEqual(user_foo.id, user_bar.id)
        self.assertNotEqual(user_foo.partner_id.id, user_bar.partner_id.id)

    @mute_logger("odoo.models")
    def test_copy_with_ancestor(self):
        """copying a user with 'parent_id' in defaults should not duplicate the partner"""
        user_foo = self.env["res.users"].create(
            {"login": "foo", "name": "Foo", "signature": "Foo"}
        )
        partner_bar = self.env["res.partner"].create({"name": "Bar"})

        (foo_before,) = user_foo.read()
        del foo_before["create_date"]
        del foo_before["write_date"]
        del foo_before["login_date"]
        partners_before = self.env["res.partner"].search([])
        user_bar = user_foo.copy({"partner_id": partner_bar.id, "login": "bar"})
        (foo_after,) = user_foo.read()
        del foo_after["create_date"]
        del foo_after["write_date"]
        del foo_after["login_date"]
        partners_after = self.env["res.partner"].search([])

        self.assertEqual(foo_before, foo_after)
        self.assertEqual(partners_before, partners_after)

        self.assertNotEqual(user_foo.id, user_bar.id)
        self.assertEqual(user_bar.partner_id.id, partner_bar.id)
        self.assertEqual(user_bar.login, "bar", "login is given from copy parameters")
        self.assertFalse(
            user_bar.password,
            "password should not be copied from original record",
        )
        self.assertEqual(user_bar.name, "Bar", "name is given from specific partner")
        self.assertEqual(
            user_bar.signature, user_foo.signature, "signature should be copied"
        )

    @mute_logger("odoo.models")
    def test_write_date(self):
        """modifying inherited fields must update write_date"""
        user = self.env.user
        write_date_before = user.write_date

        # write base64 image
        user.write(
            {
                "image_1920": "R0lGODlhAQABAIAAAP///////yH5BAEKAAEALAAAAAABAAEAAAICTAEAOw=="
            }
        )
        write_date_after = user.write_date
        self.assertNotEqual(write_date_before, write_date_after)


@tagged("post_install", "-at_install")
class TestCompanyDependent(TransactionCase):
    def test_flush_stale_flat_cache_entry_not_nulled(self):
        """Regression: a company-dependent field whose value lives only in a
        stale flat cache entry (``{id: scalar}``, the layout used before
        ``field_depends_context`` is populated) must not be flushed as SQL
        ``NULL``, which silently clears the stored value.

        ``Field.get_column_update``'s company-dependent branch skipped flat
        entries unconditionally and returned ``None``. Mirrors the same defect
        in the ``translate is True`` branch (see
        ``test_translate.TestTranslationWrite.test_flush_stale_flat_cache_entry_not_nulled``).
        """
        partner = self.env["res.partner"].create({"name": "Flat", "barcode": "BC-1"})
        field = partner._fields["barcode"]
        self.assertTrue(field.company_dependent, "barcode must be company_dependent")
        core = self.env._core

        # Reproduce the stale-flat-entry shape: a scalar value keyed directly by
        # record id, with no nested ``{(company_id,): {id: value}}`` entry.
        core.get_field_data(field).clear()
        core.cache.set_value(field, partner.id, "BC-1")

        col_val = field.get_column_update(partner)
        self.assertIsNotNone(
            col_val,
            "company-dependent field whose value lives only in a stale flat "
            "cache entry was flushed as SQL NULL",
        )
        self.assertIn("BC-1", col_val.obj.values())

    def test_orm_ondelete_restrict(self):
        # A company-dependent many2one is stored as jsonb and has no DB ON
        # DELETE action. If A.field_a (company-dependent m2o, ondelete='restrict')
        # -> B and B.field_b (m2o, ondelete='cascade') -> C, then deleting C
        # cascade-deletes B and leaves A referencing a dead row (read as NULL),
        # bypassing the ORM 'restrict'. Such a combination must not exist: move
        # the cascade logic to an unlink() override instead.
        for model in self.env.registry.values():
            for field in model._fields.values():
                if (
                    field.company_dependent
                    and field.type == "many2one"
                    and field.ondelete.lower() == "restrict"
                ):
                    for comodel_field in self.env[field.comodel_name]._fields.values():
                        self.assertFalse(
                            comodel_field.type == "many2one"
                            and comodel_field.ondelete == "cascade",
                            (
                                f"when a row for {comodel_field.comodel_name} is deleted, a row for {comodel_field.model_name} "
                                f"may also be deleted for sake of on delete cascade field {comodel_field}, which will "
                                f'bypass the ORM ondelete="restrict" check for a company dependent many2one field {field}. '
                                f"Please override the unlink method of {comodel_field.comodel_name} and do the ORM on "
                                f'delete cascade logic and remove/override the ondelete="cascade" of {comodel_field}'
                            ),
                        )
