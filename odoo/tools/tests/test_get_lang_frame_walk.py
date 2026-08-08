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
    """Helper object with no ``env``, like the report module's WeasyPrint engine."""

    def build_message(self):
        return _get_lang(inspect.currentframe())


class _Recordset:
    """Model-like caller that carries the environment the helper runs under."""

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


if __name__ == "__main__":
    unittest.main()
