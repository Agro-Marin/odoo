import odoo.tests
from odoo import Command


@odoo.tests.tagged("post_install", "-at_install")
class TestTranslationWritePropagation(odoo.tests.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.lang"]._activate_lang("fr_FR")
        cls.Model = cls.env["test_orm.prefetch"]

    def stored(self, record):
        record.flush_recordset(["name"])
        self.env.cr.execute(
            "SELECT name FROM test_orm_prefetch WHERE id = %s", (record.id,)
        )
        return self.env.cr.fetchone()[0]

    def test_echo_language_follows_the_write(self):
        record = self.Model.with_context(lang="fr_FR").create({"name": "Couteau"})
        self.assertEqual(
            self.stored(record),
            {"en_US": "Couteau", "fr_FR": "Couteau"},
            "sanity: creating in fr_FR materialises both keys",
        )

        record.with_context(lang="fr_FR").name = "Grand Couteau"

        self.assertEqual(
            self.stored(record), {"en_US": "Grand Couteau", "fr_FR": "Grand Couteau"}
        )

    def test_authored_translation_is_never_clobbered(self):
        record = self.Model.create({"name": "Knife"})
        record.with_context(lang="fr_FR").name = "Couteau"

        record.with_context(lang="fr_FR").name = "Petit Couteau"

        self.assertEqual(
            self.stored(record), {"en_US": "Knife", "fr_FR": "Petit Couteau"}
        )

    def test_authored_translation_survives_a_source_write(self):
        record = self.Model.create({"name": "Knife"})
        record.with_context(lang="fr_FR").name = "Couteau"

        record.with_context(lang="en_US").name = "Steel Knife"

        self.assertEqual(
            self.stored(record), {"en_US": "Steel Knife", "fr_FR": "Couteau"}
        )

    def test_first_translation_of_a_source_only_record_creates_it(self):
        record = self.Model.create({"name": "Knife"})
        self.assertEqual(
            self.stored(record), {"en_US": "Knife"}, "sanity: only the source key"
        )

        record.with_context(lang="fr_FR").name = "Couteau"

        self.assertEqual(self.stored(record), {"en_US": "Knife", "fr_FR": "Couteau"})

    def test_update_field_translations_still_writes_one_language(self):
        record = self.Model.with_context(lang="fr_FR").create({"name": "Couteau"})

        record.update_field_translations("name", {"fr_FR": "Couteau de Chef"})

        self.assertEqual(
            self.stored(record), {"en_US": "Couteau", "fr_FR": "Couteau de Chef"}
        )

    def test_batch_write_decides_per_record(self):
        echo = self.Model.with_context(lang="fr_FR").create({"name": "Couteau"})
        translated = self.Model.create({"name": "Knife"})
        translated.with_context(lang="fr_FR").name = "Fourchette"
        source_only = self.Model.create({"name": "Spoon"})

        records = echo | translated | source_only
        records.with_context(lang="fr_FR").write({"name": "Commun"})

        self.assertEqual(
            self.stored(echo),
            {"en_US": "Commun", "fr_FR": "Commun"},
            "the echo follows",
        )
        self.assertEqual(
            self.stored(translated),
            {"en_US": "Knife", "fr_FR": "Commun"},
            "the authored translation keeps its source term",
        )
        self.assertEqual(
            self.stored(source_only),
            {"en_US": "Spoon", "fr_FR": "Commun"},
            "a source-only record gains a translation",
        )

    def test_single_language_database_is_untouched(self):
        record = self.Model.create({"name": "Knife"})

        record.with_context(lang="en_US").name = "Steel Knife"

        self.assertEqual(self.stored(record), {"en_US": "Steel Knife"})

    def _deactivate_source_language(self):
        """Take `en_US` out of the installed set, whatever else is installed.

        The echo the caller is about to test is decided by
        `res.lang._get_data(code="en_US")`, which answers for *active*
        languages, so the record really does have to be deactivated. Modules
        may hold a language and refuse that: `website` raises when one is still
        listed on a site, and `test_import_export` depends on `website` for
        `MockRequest`, which is enough to make this test fail in any run wide
        enough to install it. Release the holders first rather than assume the
        narrow install set.
        """
        english = self.env.ref("base.lang_en")
        replacement = self.env["res.lang"].search(
            [("code", "!=", "en_US"), ("active", "=", True)], limit=1
        )
        self.assertTrue(replacement, "setUpClass activates fr_FR")
        self.env["res.partner"].with_context(active_test=False).search([]).write(
            {"lang": replacement.code}
        )
        websites = self.env.get("website")
        if websites is not None:
            for website in websites.sudo().with_context(active_test=False).search([]):
                if english in website.language_ids:
                    website.write(
                        {
                            "default_lang_id": replacement.id,
                            "language_ids": [
                                Command.set((website.language_ids - english).ids)
                                if website.language_ids - english
                                else Command.set(replacement.ids)
                            ],
                        }
                    )
        english.active = False

    def test_uninstalled_source_language_is_not_an_echo_anchor(self):
        self.env["res.lang"]._activate_lang("es_ES")
        self._deactivate_source_language()
        record = self.Model.create({"name": "Knife"})

        record.with_context(lang="fr_FR").name = "Couteau"
        record.with_context(lang="es_ES").name = "Cuchillo"
        self.assertEqual(
            self.stored(record),
            {"en_US": "Cuchillo", "es_ES": "Cuchillo", "fr_FR": "Couteau"},
            "sanity: the es_ES write mirrored itself into the unused source key",
        )

        record.with_context(lang=None).name = "Sans Langue"

        self.assertEqual(
            self.stored(record),
            {"en_US": "Sans Langue", "es_ES": "Cuchillo", "fr_FR": "Couteau"},
            "the authored Spanish term must survive a write to the source key",
        )
