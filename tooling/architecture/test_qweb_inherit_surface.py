import tempfile
import unittest
from pathlib import Path

import qweb_inherit_surface as gate


def _xml(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"<templates>{body}</templates>", encoding="utf8")


class TestInheritorsOfWebViewTemplates(unittest.TestCase):
    def test_an_inheritor_of_a_web_views_template_is_a_row(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            web = tmp / "web" / "static" / "src" / "views"
            _xml(web / "list" / "list_controller.xml", '<t t-name="web.ListView"/>')
            _xml(
                tmp / "sign" / "static" / "src" / "x.xml",
                '<t t-inherit="web.ListView" t-inherit-mode="extension"/>',
            )
            owned = gate.owned_templates(web)
            rows = gate.inheritors((("enterprise", tmp),), owned)
            self.assertEqual(
                rows, {("web.ListView", "sign/static/src/x.xml"): "enterprise"}
            )

    def test_an_inheritor_of_something_else_is_not(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            web = tmp / "web" / "static" / "src" / "views"
            _xml(web / "list" / "list_controller.xml", '<t t-name="web.ListView"/>')
            _xml(
                tmp / "sign" / "static" / "src" / "x.xml",
                '<t t-inherit="web.SearchBar" t-inherit-mode="extension"/>',
            )
            self.assertEqual(
                gate.inheritors((("enterprise", tmp),), gate.owned_templates(web)),
                {},
            )

    def test_a_test_template_is_neither_owned_nor_an_inheritor(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            web = tmp / "web" / "static" / "src" / "views"
            _xml(web / "list" / "list_controller.xml", '<t t-name="web.ListView"/>')
            _xml(
                tmp / "sign" / "static" / "tests" / "x.xml",
                '<t t-inherit="web.ListView"/>',
            )
            self.assertEqual(
                gate.inheritors((("enterprise", tmp),), gate.owned_templates(web)),
                {},
            )

    def test_the_pin_round_trips(self):
        with tempfile.TemporaryDirectory() as d:
            pin = Path(d) / "pin.txt"
            rows = {("web.ListView", "sign/static/src/x.xml"): "enterprise"}
            gate.write_pinned(rows, pin)
            self.assertEqual(gate.load_pinned(pin), rows)


class TestTheRealTreeIsReached(unittest.TestCase):
    def test_the_three_blocked_controller_templates_have_inheritors(self):
        rows = gate.inheritors()
        targets = {t for t, _ in rows}
        self.assertLessEqual(
            {"web.ListView", "web.KanbanView", "web.CalendarController"}, targets
        )
