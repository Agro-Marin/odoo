import inspect
import logging
import unittest

from odoo.tools.translate import _LANG_FRAME_SEARCH_DEPTH, _get_lang


class _Env:
    cr = None
    uid = None

    def __init__(self, lang):
        self.lang = lang


class _PlainEngine:
    def build_message(self):
        return _get_lang(inspect.currentframe())


class _Recordset:
    def __init__(self, lang):
        self.env = _Env(lang)

    def render(self, engine):
        return engine.build_message()

    def handler_lambda(self):
        handlers = {ValueError: lambda _e: _get_lang(inspect.currentframe())}
        return handlers[ValueError](ValueError())

    def connect(self):
        return self.load_error(ValueError())

    @staticmethod
    def load_error(exc):
        return _get_lang(inspect.currentframe())


def _bare_helper():
    return _get_lang(inspect.currentframe())


class TestGetLangFrameWalk(unittest.TestCase):
    def test_context_in_calling_frame(self):
        context = {"lang": "fr_FR"}  # noqa: F841 - read out of the frame under test
        self.assertEqual(_get_lang(inspect.currentframe()), "fr_FR")

    def test_kwargs_context_in_calling_frame(self):
        kwargs = {"context": {"lang": "nl_NL"}}  # noqa: F841 - read out of the frame
        self.assertEqual(_get_lang(inspect.currentframe()), "nl_NL")

    def test_context_in_outer_frame(self):
        context = {"lang": "es_MX"}  # noqa: F841 - read out of an outer frame
        self.assertEqual(_bare_helper(), "es_MX")

    def test_env_of_outer_recordset_frame(self):
        self.assertEqual(_Recordset("de_DE").render(_PlainEngine()), "de_DE")

    def test_env_reached_through_lambda_frame(self):
        self.assertEqual(_Recordset("pt_BR").handler_lambda(), "pt_BR")

    def test_env_reached_through_staticmethod_frame(self):
        self.assertEqual(_Recordset("it_IT").connect(), "it_IT")

    def test_innermost_context_wins_over_outer_env(self):
        def inner():
            context = {"lang": "ja_JP"}  # noqa: F841 - read out of the frame
            return _get_lang(inspect.currentframe())

        recordset = _Recordset("de_DE")  # noqa: F841 - outer frame env, must not win
        self.assertEqual(inner(), "ja_JP")

    def test_default_lang_short_circuits_failure(self):
        self.assertEqual(_get_lang(inspect.currentframe(), "en_GB"), "en_GB")

    def test_search_is_depth_bounded(self):
        def nest(depth):
            if depth:
                return nest(depth - 1)
            return _get_lang(inspect.currentframe())

        context = {"lang": "fr_FR"}  # noqa: F841 - deliberately out of reach
        with self.assertLogs("odoo.tools.translate", level=logging.WARNING):
            self.assertEqual(nest(_LANG_FRAME_SEARCH_DEPTH + 2), "")

    def test_reachable_env_without_lang_is_not_a_warning(self):
        with self.assertLogs("odoo.tools.translate", level=logging.DEBUG) as logs:
            self.assertEqual(_Recordset(None).render(_PlainEngine()), "")
        self.assertEqual([record.levelno for record in logs.records], [logging.DEBUG])

    def test_no_reachable_env_warns(self):
        with self.assertLogs("odoo.tools.translate", level=logging.DEBUG) as logs:
            self.assertEqual(_PlainEngine().build_message(), "")
        self.assertEqual([record.levelno for record in logs.records], [logging.WARNING])

    # A frame local is matched by name, so the walk meets objects that merely
    # happen to be called `context` or `kwargs`. Interrogating one must not
    # raise: `.get` on a non-mapping is an AttributeError, which propagated out
    # of every `_()` call underneath such a frame.

    def test_assert_raises_context_local_is_not_a_context(self):
        # The shape that broke in practice: `as context` binds an
        # _AssertRaisesContext, and any _() below it walked through this frame.
        def inner():
            with self.assertRaises(ValueError) as context:  # noqa: F841
                raise ValueError("boom")
            return _get_lang(inspect.currentframe())

        context = {"lang": "fr_FR"}  # noqa: F841 - reached past the stranger
        self.assertEqual(inner(), "fr_FR")

    def test_non_mapping_context_local_falls_through(self):
        context = object()  # noqa: F841 - a stranger sharing the name
        self.assertEqual(_get_lang(inspect.currentframe()), "")

    def test_non_mapping_kwargs_local_falls_through(self):
        kwargs = "not a mapping"  # noqa: F841 - read out of the frame under test
        self.assertEqual(_get_lang(inspect.currentframe()), "")

    def test_non_mapping_context_inside_kwargs_falls_through(self):
        kwargs = {"context": object()}  # noqa: F841 - read out of the frame
        self.assertEqual(_get_lang(inspect.currentframe()), "")

    def test_non_string_lang_is_ignored(self):
        context = {"lang": 5}  # noqa: F841 - read out of the frame under test
        self.assertEqual(_get_lang(inspect.currentframe()), "")

    def test_stranger_context_does_not_hide_an_outer_one(self):
        def inner():
            context = object()  # noqa: F841 - must not shadow the outer context
            return _get_lang(inspect.currentframe())

        context = {"lang": "fr_FR"}  # noqa: F841 - reached past the stranger
        self.assertEqual(inner(), "fr_FR")


if __name__ == "__main__":
    unittest.main()
