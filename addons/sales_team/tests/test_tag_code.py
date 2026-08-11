# Part of Odoo. See LICENSE file for full copyright and licensing details.

from psycopg.errors import UniqueViolation

from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger


class TestTagCode(TransactionCase):
    """`tag.mixin.code` — the value a machine matches on.

    `name` is `translate=True`, so it is a jsonb document whose value depends on
    the reader's language; that is right for a label and useless for an import,
    a filter or a data file. `code` is the plain column those match against.

    Exercised through `crm.tag`, one of the mixin's concrete consumers.
    """

    def _tag(self, **vals):
        return self.env["crm.tag"].create({"name": "Some Tag", **vals})

    def test_a_code_is_derived_from_the_name(self):
        self.assertEqual(self._tag(name="Hot Lead").code, "HOT_LEAD")

    def test_punctuation_and_case_are_normalised(self):
        self.assertEqual(self._tag(name="  très-Chaud!! ").code, "TR_S_CHAUD")

    def test_name_create_gets_a_code(self):
        """The many2many tag widget creates tags with a name and nothing else.
        A field with no answer of its own would have broken every such widget."""
        tag_id, _label = self.env["crm.tag"].name_create("Widget Made")
        self.assertEqual(self.env["crm.tag"].browse(tag_id).code, "WIDGET_MADE")

    def test_an_explicit_code_is_kept(self):
        self.assertEqual(self._tag(name="Anything", code="MY_CODE").code, "MY_CODE")

    def test_renaming_does_not_move_the_code(self):
        """The whole point: other records match on this value, so it must not
        change under them when someone edits a label."""
        tag = self._tag(name="Original")
        self.assertEqual(tag.code, "ORIGINAL")
        tag.name = "Renamed Entirely"
        self.assertEqual(tag.code, "ORIGINAL")

    def test_two_names_slugging_alike_do_not_collide(self):
        """ "Hot!" and "Hot?" are different names and one code. Resolve it here
        rather than failing the create on a value the user never typed."""
        first = self._tag(name="Hot!")
        second = self._tag(name="Hot?")
        self.assertEqual(first.code, "HOT")
        self.assertEqual(second.code, "HOT_2")

    def test_the_same_name_under_two_parents_does_not_collide(self):
        """The name rule is scoped to the parent and allows this deliberately;
        `code` is global, so it has to disambiguate."""
        left = self._tag(name="Region")
        right = self._tag(name="Zone")
        first = self._tag(name="North", parent_id=left.id)
        second = self._tag(name="North", parent_id=right.id)
        self.assertNotEqual(first.code, second.code)

    @mute_logger("odoo.db.cursor")
    def test_a_duplicate_code_is_refused(self):
        self._tag(name="First", code="SHARED")
        with self.assertRaises(UniqueViolation):
            self._tag(name="Second", code="SHARED")
            self.env.flush_all()

    def test_a_code_survives_a_batch_create(self):
        """Taken codes are read once per batch, so a data file loading many
        tags at once must still come out with distinct codes."""
        tags = self.env["crm.tag"].create(
            [{"name": "Bulk!"}, {"name": "Bulk?"}, {"name": "Bulk."}]
        )
        self.assertEqual(len(set(tags.mapped("code"))), 3)

    def test_a_strict_query_finds_the_tag_whatever_the_language(self):
        tag = self._tag(name="Findable", code="FINDABLE")
        self.assertEqual(
            self.env["crm.tag"].search([("code", "=", "FINDABLE")]),
            tag,
        )
