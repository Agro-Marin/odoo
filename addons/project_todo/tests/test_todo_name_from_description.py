from odoo.tests.common import TransactionCase


class TestTodoNameFromDescription(TransactionCase):
    def _name_for(self, description):
        return self.env["project.task"].create({"description": description}).name

    def test_description_with_no_text_falls_back_to_untitled(self):
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
        self.assertEqual(
            self._name_for("<ul><li>first bullet</li><li>second</li></ul>"),
            "first bullet",
        )

    def test_inline_markup_is_kept_as_text(self):
        self.assertEqual(self._name_for("<p><b>Bold</b> title</p>"), "Bold title")

    def test_asterisks_are_content_not_markup(self):
        self.assertEqual(
            self._name_for("<p>Buy 2 * 4 planks at 3*5cm</p>"),
            "Buy 2 * 4 planks at 3*5cm",
        )

    def test_long_first_line_is_truncated(self):
        self.assertEqual(len(self._name_for("<p>%s</p>" % ("x" * 300))), 100)
        self.assertTrue(self._name_for("<p>%s</p>" % ("x" * 300)).endswith("..."))
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
        helper = self.env["project.task"]._todo_name_from_description
        self.assertEqual(helper(False), "")
        self.assertEqual(helper(""), "")
        self.assertEqual(helper("<p><br></p>"), "")
        self.assertEqual(helper("not even html"), "not even html")
