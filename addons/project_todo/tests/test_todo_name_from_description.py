# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests.common import TransactionCase


class TestTodoNameFromDescription(TransactionCase):
    """A to-do created with a description but no title derives one from it.

    The To-Do form requires a title, so this path is only reached over RPC or
    from another module — which is exactly why it needs a test: nothing in the
    UI would surface a regression here.
    """

    def _name_for(self, description):
        return self.env["project.task"].create({"description": description}).name

    def test_description_with_no_text_falls_back_to_untitled(self):
        """An empty editor document is ``<p><br></p>`` — truthy, but blank."""
        for description in (
            "<p><br></p>",
            "<p>   </p>",
            "<p>&nbsp;</p>",
            "<div></div>",
        ):
            with self.subTest(description=description):
                self.assertEqual(
                    self._name_for(description),
                    "Untitled to-do",
                    "a description that carries no text must not leave an empty title",
                )

    def test_no_description_falls_back_to_untitled(self):
        self.assertEqual(self.env["project.task"].create({}).name, "Untitled to-do")

    def test_first_line_only(self):
        self.assertEqual(
            self._name_for("<p>Buy the paint</p><p>and the brushes</p>"),
            "Buy the paint",
        )

    def test_first_list_item_is_the_first_line(self):
        """html2plaintext runs sibling <li> together; the title is one item."""
        self.assertEqual(
            self._name_for("<ul><li>first bullet</li><li>second</li></ul>"),
            "first bullet",
        )

    def test_inline_markup_is_kept_as_text(self):
        self.assertEqual(self._name_for("<p><b>Bold</b> title</p>"), "Bold title")

    def test_asterisks_are_content_not_markup(self):
        """A stray strip of '*' silently rewrites arithmetic and dimensions."""
        self.assertEqual(
            self._name_for("<p>Buy 2 * 4 planks at 3*5cm</p>"),
            "Buy 2 * 4 planks at 3*5cm",
        )

    def test_long_first_line_is_truncated(self):
        self.assertEqual(len(self._name_for("<p>%s</p>" % ("x" * 300))), 100)
        self.assertTrue(self._name_for("<p>%s</p>" % ("x" * 300)).endswith("..."))
        # exactly at the limit, nothing is cut
        self.assertEqual(self._name_for("<p>%s</p>" % ("x" * 100)), "x" * 100)

    def test_derivation_is_skipped_when_a_title_is_given(self):
        task = self.env["project.task"].create(
            {
                "name": "My title",
                "description": "<p>Something else</p>",
            }
        )
        self.assertEqual(task.name, "My title")

    def test_derivation_is_skipped_for_project_tasks(self):
        """A task inside a project is not a to-do; its title is not derived."""
        project = self.env["project.project"].create({"name": "P"})
        task = self.env["project.task"].create(
            {
                "name": "Real task",
                "project_id": project.id,
                "description": "<p>Not a to-do</p>",
            }
        )
        self.assertEqual(task.name, "Real task")

    def test_helper_is_pure(self):
        """The helper reports emptiness rather than inventing a title, so the
        caller decides what the fallback is."""
        helper = self.env["project.task"]._todo_name_from_description
        self.assertEqual(helper(False), "")
        self.assertEqual(helper(""), "")
        self.assertEqual(helper("<p><br></p>"), "")
        self.assertEqual(helper("not even html"), "not even html")
