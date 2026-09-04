from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPosCategorySearch(TransactionCase):
    """Finding a POS category by typing where it lives.

    Every m2m that assigns a category -- the product form, the register's
    available categories, a preparation printer -- is a name search. A
    category nested under a parent is reachable only if that search knows
    about the parent.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Category = cls.env["pos.category"]
        cls.furniture = cls.Category.create({"name": "Test Furniture"})
        cls.chairs = cls.Category.create(
            {"name": "Test Chairs", "parent_id": cls.furniture.id}
        )
        cls.stools = cls.Category.create(
            {"name": "Test Stools", "parent_id": cls.chairs.id}
        )
        cls.branch = cls.furniture + cls.chairs + cls.stools

    def _found(self, typed):
        """Search as the m2m widgets do, scoped to this test's own branch."""
        return {
            category_id
            for category_id, _label in self.Category.name_search(
                typed, domain=[("id", "in", self.branch.ids)]
            )
        }

    def test_typing_a_parent_finds_the_categories_under_it(self):
        """Typing the parent offers everything filed under it."""
        self.assertEqual(set(self.branch.ids), self._found("Test Furniture"))

    def test_typing_a_leaf_still_finds_only_that_branch(self):
        """A search for a child does not drag its siblings in."""
        self.assertEqual({self.stools.id}, self._found("Test Stools"))

    def test_a_category_reads_as_its_full_path(self):
        """The label keeps naming where the category sits."""
        self.assertEqual(
            self.stools.display_name, "Test Furniture / Test Chairs / Test Stools"
        )

    def test_the_path_follows_a_category_that_is_moved(self):
        """Re-parenting a branch renames everything under it."""
        self.chairs.parent_id = False
        self.assertEqual(self.stools.display_name, "Test Chairs / Test Stools")
        self.assertEqual({self.chairs.id, self.stools.id}, self._found("Test Chairs"))

    def test_the_label_is_translated_per_language(self):
        """A cashier reads category names in their own language.

        `pos.category.name` is translatable, so whatever backs the label has
        to be translatable too -- a stored non-translated path would freeze
        every category in the language that last wrote it.
        """
        self.env["res.lang"]._activate_lang("fr_FR")
        self.furniture.with_context(lang="fr_FR").name = "Mobilier"
        self.assertEqual(
            self.chairs.with_context(lang="fr_FR").display_name,
            "Mobilier / Test Chairs",
        )
        self.assertEqual(self.chairs.display_name, "Test Furniture / Test Chairs")

    def test_a_new_category_sorts_after_the_existing_ones(self):
        """The list orders by sequence, and the handle writes sequences.

        With no default every category starts at 0 and the list falls back to
        the name, so dragging one row renumbers it away from the rest.
        """
        newcomer = self.Category.create({"name": "Test Aardvark"})
        self.assertGreater(newcomer.sequence, self.furniture.sequence)
        self.assertGreater(newcomer.sequence, self.stools.sequence)
