import odoo.tests
from odoo.exceptions import AccessError
from odoo.fields import Command


@odoo.tests.tagged("post_install", "-at_install")
class TestFieldGetEquivalenceDB(odoo.tests.TransactionCase):
    _MIXED_FIELDS = (
        "count",
        "number",
        "amount",
        "truth",
        "lang",
        "date",
        "moment",
        "foo",
        "text",
        "comment0",
        "currency_id",
    )

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rec = cls.env["test_orm.mixed"].create(
            {
                "count": 7,
                "number": 3.5,
                "amount": 12.0,
                "truth": True,
                "date": "2020-01-02",
                "moment": "2020-01-02 03:04:05",
                "foo": "hello",
                "text": "multi\nline",
                "comment0": "<p>hi</p>",
            }
        )
        cls.user = cls.env["res.users"].create(
            {
                "name": "geteq user",
                "login": "geteq_user",
                "group_ids": [Command.set([cls.env.ref("base.group_user").id])],
            }
        )

    def test_real_field_acl_raises_denies_and_bypasses_per_fast_path_type(self):
        self.assertFalse(self.user.has_group("base.group_system"))
        rec_admin = self.rec
        rec_user = self.rec.with_user(self.user)
        for fname in self._MIXED_FIELDS:
            field = type(self.rec)._fields[fname]
            with self.subTest(field=fname):
                getattr(rec_user, fname)
                self.patch(field, "groups", "base.group_system")
                with self.assertRaises(AccessError):
                    getattr(rec_user, fname)
                self.assertEqual(
                    getattr(rec_user.sudo(), fname), getattr(rec_admin, fname)
                )
                getattr(rec_admin, fname)

    def test_real_translate_true_per_language_matches_convert_to_record(self):
        self.env["res.lang"]._activate_lang("fr_FR")
        rec = (
            self.env["test_orm.related_translation_1"]
            .with_context(lang="en_US")
            .create({"name": "Knife", "html": "<p>Knife</p>"})
        )
        rec.with_context(lang="fr_FR").write({"name": "Couteau"})
        seen = {}
        for lang, expected in (("en_US", "Knife"), ("fr_FR", "Couteau")):
            r = rec.with_context(lang=lang)
            field = r._fields["name"]
            got = r.name
            self.assertEqual(got, expected)
            cache_val = field._get_cache(r.env)[r.id]
            self.assertEqual(got, field.convert_to_record(cache_val, r))
            seen[lang] = got
        self.assertNotEqual(seen["en_US"], seen["fr_FR"])

    def test_real_translate_true_new_record_falls_back_to_en_us(self):
        self.env["res.lang"]._activate_lang("fr_FR")
        rec = (
            self.env["test_orm.related_translation_1"]
            .with_context(lang="en_US")
            .new({"name": "English"})
        )
        self.assertEqual(rec.name, "English")
        other = rec.with_context(lang="fr_FR")
        self.assertEqual(other.name, "English", "expected en_US fallback, not False")
