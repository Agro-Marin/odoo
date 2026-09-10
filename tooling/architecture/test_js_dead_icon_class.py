import tempfile
import unittest
from pathlib import Path

import js_dead_icon_class as gate


def _tree(tmp: Path) -> Path:
    css = tmp / "web" / "static" / "src" / "libs" / "fa" / "fontawesome.css"
    css.parent.mkdir(parents=True)
    css.write_text(".fa-magnifying-glass {}\n.fa-search {}\n", encoding="utf8")
    (tmp / "room" / "static" / "src").mkdir(parents=True)
    (tmp / "room" / "static" / "src" / "room.xml").write_text(
        '<i class="fa-solid fa-room-only"/>', encoding="utf8"
    )
    (tmp / "room" / "static" / "tests").mkdir(parents=True)
    return tmp


def _test(tmp: Path, body: str) -> None:
    (tmp / "room" / "static" / "tests" / "room.test.js").write_text(
        body, encoding="utf8"
    )


class TestDeadIconClasses(unittest.TestCase):
    def _dead(self, tmp: Path):
        declared = gate.declared_icons((tmp,), tmp / "web" / "static" / "src" / "libs")
        return gate.dead_icons((tmp,), declared)

    def test_a_renamed_icon_the_test_still_names_is_dead(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = _tree(Path(d))
            _test(tmp, 'expect(".fa-calendar-times-o").toHaveCount(1);\n')
            self.assertEqual(
                self._dead(tmp),
                {"fa-calendar-times-o": ["room/static/tests/room.test.js"]},
            )

    def test_an_alias_the_stylesheet_declares_is_not(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = _tree(Path(d))
            _test(tmp, 'await click(".fa-search");\n')
            self.assertEqual(self._dead(tmp), {})

    def test_an_icon_a_source_template_writes_is_not(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = _tree(Path(d))
            _test(tmp, 'expect(".fa-room-only").toHaveCount(1);\n')
            self.assertEqual(self._dead(tmp), {})

    def test_a_class_named_only_in_a_comment_is_not(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = _tree(Path(d))
            _test(tmp, "// this used to read `.fa-stop-danger`, which never existed\n")
            self.assertEqual(self._dead(tmp), {})

    def test_size_and_style_classes_are_not_icons(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = _tree(Path(d))
            _test(tmp, 'expect(".fa-solid.fa-2x.fa-spin").toHaveCount(1);\n')
            self.assertEqual(self._dead(tmp), {})


class TestTheRealTreeIsReached(unittest.TestCase):
    def test_the_stylesheet_is_read(self):
        self.assertGreater(len(gate.declared_icons()), 1000)
