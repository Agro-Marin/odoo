import odoo.tests


@odoo.tests.tagged("post_install", "-at_install")
class TestTranslationWritePropagation(odoo.tests.TransactionCase):
    """A write to a translated field carries the languages that were in sync.

    Creating a record while working in a non-source language stores the typed
    value under *both* ``en_US`` and that language.  That second key is an echo,
    not a translation anyone authored, yet nothing distinguishes it from one --
    so before this behaviour every later edit stayed local and the other
    languages kept serving a name that no longer existed.

    The rule: a write in language X also updates every language whose stored
    term is identical to X's.  Languages holding a genuinely different term were
    translated on purpose and are never touched.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.lang"]._activate_lang("fr_FR")
        cls.Model = cls.env["test_orm.prefetch"]

    def stored(self, record):
        """The raw jsonb, so an absent key is distinguishable from a translated one."""
        record.flush_recordset(["name"])
        self.env.cr.execute(
            "SELECT name FROM test_orm_prefetch WHERE id = %s", (record.id,)
        )
        return self.env.cr.fetchone()[0]

    def test_echo_language_follows_the_write(self):
        """Created in fr_FR (so en_US is an echo), renamed in fr_FR."""
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
        """A language holding its own term is left alone by a write elsewhere."""
        record = self.Model.create({"name": "Knife"})
        record.with_context(lang="fr_FR").name = "Couteau"

        record.with_context(lang="fr_FR").name = "Petit Couteau"

        self.assertEqual(
            self.stored(record), {"en_US": "Knife", "fr_FR": "Petit Couteau"}
        )

    def test_authored_translation_survives_a_source_write(self):
        """The mirror direction: writing en_US must not drag fr_FR."""
        record = self.Model.create({"name": "Knife"})
        record.with_context(lang="fr_FR").name = "Couteau"

        record.with_context(lang="en_US").name = "Steel Knife"

        self.assertEqual(
            self.stored(record), {"en_US": "Steel Knife", "fr_FR": "Couteau"}
        )

    def test_first_translation_of_a_source_only_record_creates_it(self):
        """The safety property: with no key of its own, a language falls back to
        the source term.  Writing it authors a translation -- it must not be
        mistaken for an in-sync echo and overwrite ``en_US``.
        """
        record = self.Model.create({"name": "Knife"})
        self.assertEqual(
            self.stored(record), {"en_US": "Knife"}, "sanity: only the source key"
        )

        record.with_context(lang="fr_FR").name = "Couteau"

        self.assertEqual(self.stored(record), {"en_US": "Knife", "fr_FR": "Couteau"})

    def test_update_field_translations_still_writes_one_language(self):
        """The translate dialog targets languages deliberately; it must stay exact."""
        record = self.Model.with_context(lang="fr_FR").create({"name": "Couteau"})

        record.update_field_translations("name", {"fr_FR": "Couteau de Chef"})

        self.assertEqual(
            self.stored(record), {"en_US": "Couteau", "fr_FR": "Couteau de Chef"}
        )

    def test_batch_write_decides_per_record(self):
        """One write over a mixed recordset resolves each record on its own."""
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
        """With one stored key there is nothing beside it to keep in sync."""
        record = self.Model.create({"name": "Knife"})

        record.with_context(lang="en_US").name = "Steel Knife"

        self.assertEqual(self.stored(record), {"en_US": "Steel Knife"})

    def test_uninstalled_source_language_is_not_an_echo_anchor(self):
        """With English uninstalled, ``en_US`` mirrors whichever language was
        written last, so its term matching another one is manufactured rather
        than evidence that nobody translated that language away.  Reading it as
        an echo would destroy the translation it coincides with.
        """
        self.env["res.lang"]._activate_lang("es_ES")
        self.env["res.partner"].with_context(active_test=False).search([]).write(
            {"lang": "fr_FR"}
        )
        self.env.ref("base.lang_en").active = False
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
