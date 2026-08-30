import unittest

from markupsafe import Markup

from odoo.tools.translate import get_translation


def _render(source, args):
    return get_translation("base", "en_US", source, args)


class TestOneShotIterableArguments(unittest.TestCase):
    EXPECTED = "items: a, b, and c"

    def test_a_list_argument_is_formatted_as_a_list(self):
        self.assertEqual(_render("items: %s", (["a", "b", "c"],)), self.EXPECTED)

    def test_a_generator_argument_renders_the_same_as_a_list(self):
        generator = (letter for letter in ["a", "b", "c"])
        self.assertEqual(_render("items: %s", (generator,)), self.EXPECTED)

    def test_a_map_argument_renders_the_same_as_a_list(self):
        self.assertEqual(
            _render("items: %s", (map(str, ["a", "b", "c"]),)), self.EXPECTED
        )

    def test_a_one_shot_iterable_works_as_a_named_argument_too(self):
        generator = (letter for letter in ["a", "b", "c"])
        self.assertEqual(_render("items: %(xs)s", {"xs": generator}), self.EXPECTED)

    def test_the_result_does_not_depend_on_the_other_arguments(self):
        without = _render("%s", ((x for x in ["a", "b"]),))
        with_markup = _render("%s / %s", (Markup("<b>x</b>"), (x for x in ["a", "b"])))
        self.assertEqual(without, "a and b")
        self.assertEqual(with_markup, Markup("<b>x</b> / a and b"))


class TestArgumentHandlingIsOtherwiseUnchanged(unittest.TestCase):
    def test_scalars_pass_through(self):
        self.assertEqual(_render("hello %s", ("world",)), "hello world")
        self.assertEqual(_render("%s-%s", (1, 2)), "1-2")

    def test_a_string_is_a_value_not_a_list_of_characters(self):
        self.assertEqual(_render("%s", ("abc",)), "abc")

    def test_markup_inside_an_iterable_escapes_its_siblings(self):
        rendered = _render("items: %s", ([Markup("<i>a</i>"), "b<"],))
        self.assertEqual(rendered, Markup("items: <i>a</i> and b&lt;"))

    def test_no_arguments_returns_the_source(self):
        self.assertEqual(_render("plain", ()), "plain")


if __name__ == "__main__":
    unittest.main()
