import tempfile
import unittest
from pathlib import Path

import js_view_descriptor as gate


def _addon(tmp: Path, name: str) -> Path:
    module = tmp / name
    (module / "static" / "src").mkdir(parents=True)
    (module / "__manifest__.py").write_text("{'name': 'x'}", encoding="utf8")
    return module


def _view(
    module: Path, view_type: str, parser: str, model: str, controller: str
) -> None:
    src = module / "static" / "src"
    (src / "v_view.js").write_text(
        f'registry.category("views").add("{view_type}", {{ type: "{view_type}", '
        f"ArchParser: {view_type}Parser, Model: {view_type}Model, Controller: {view_type}Controller }});\n",
        encoding="utf8",
    )
    (src / "v_parser.js").write_text(parser, encoding="utf8")
    (src / "v_model.js").write_text(model, encoding="utf8")
    (src / "v_controller.js").write_text(controller, encoding="utf8")


BASES = """
export class ViewArchParser { parse() {} }
export class Model { hasData() { return true; } }
export class RelationalModel extends Model { hasData() { return false; } }
"""


class TestTheGateReadsTheChain(unittest.TestCase):
    def _audit(self, tmp):
        gate._FILES.clear()
        (tmp / "web" / "static" / "src").mkdir(parents=True)
        (tmp / "web" / "__manifest__.py").write_text("{}", encoding="utf8")
        (tmp / "web" / "static" / "src" / "bases.js").write_text(BASES, encoding="utf8")
        old = gate.SCAN_ROOTS
        gate.SCAN_ROOTS = (tmp,)
        try:
            return gate.audit((tmp,))
        finally:
            gate.SCAN_ROOTS = old
            gate._FILES.clear()

    def test_a_parser_without_the_base_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            _view(
                _addon(tmp, "a"),
                "alpha",
                "export class alphaParser { parse() {} }",
                "export class alphaModel extends RelationalModel {}",
                "export class alphaController extends Component { setup() { useModel(); } }",
            )
            _, parser_bad, sample_bad, unresolved, _studio = self._audit(tmp)
            self.assertEqual(len(parser_bad), 1, parser_bad)
            self.assertEqual(sample_bad, [])
            self.assertEqual(unresolved, [])

    def test_a_parser_reaching_the_base_through_an_ancestor_passes(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            _view(
                _addon(tmp, "b"),
                "beta",
                "export class kanbanParser extends ViewArchParser {}\nexport class betaParser extends kanbanParser {}",
                "export class betaModel extends RelationalModel {}",
                "export class betaController extends Component {}",
            )
            _, parser_bad, sample_bad, unresolved, _studio = self._audit(tmp)
            self.assertEqual((parser_bad, sample_bad, unresolved), ([], [], []))

    def test_sample_data_asked_with_no_hasData_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            _view(
                _addon(tmp, "c"),
                "gamma",
                "export class gammaParser extends ViewArchParser {}",
                "export class gammaModel extends Model {}",
                "export class gammaController extends Component { setup() { useModelWithSampleData(); } }",
            )
            _, parser_bad, sample_bad, _unresolved, _studio = self._audit(tmp)
            self.assertEqual(parser_bad, [])
            self.assertEqual(len(sample_bad), 1, sample_bad)
            self.assertIn("never overrides hasData()", sample_bad[0])

    def test_hasData_inherited_from_an_ancestor_passes(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            _view(
                _addon(tmp, "e"),
                "delta",
                "export class deltaParser extends ViewArchParser {}",
                "export class deltaModel extends RelationalModel {}",
                "export class deltaController extends Component { setup() { useModelWithSampleData(); } }",
            )
            _, parser_bad, sample_bad, unresolved, _studio = self._audit(tmp)
            self.assertEqual((parser_bad, sample_bad, unresolved), ([], [], []))

    def test_an_unresolvable_controller_is_reported_not_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            _view(
                _addon(tmp, "f"),
                "eps",
                "export class epsParser extends ViewArchParser {}",
                "export class epsModel extends Model {}",
                "export class epsController extends Ghost {}",
            )
            _, _, _, unresolved, _studio = self._audit(tmp)
            self.assertEqual(len(unresolved), 1, unresolved)


class TestTheStudioHalf(unittest.TestCase):
    def _audit(self, tmp):
        gate._FILES.clear()
        (tmp / "web" / "static" / "src").mkdir(parents=True)
        (tmp / "web" / "__manifest__.py").write_text("{}", encoding="utf8")
        (tmp / "web" / "static" / "src" / "bases.js").write_text(BASES, encoding="utf8")
        old = gate.SCAN_ROOTS
        gate.SCAN_ROOTS = (tmp,)
        try:
            return gate.audit((tmp,))
        finally:
            gate.SCAN_ROOTS = old
            gate._FILES.clear()

    def test_a_type_with_no_editor_and_no_pin_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            _view(
                _addon(tmp, "a"),
                "zeta",
                "export class zetaParser extends ViewArchParser {}",
                "export class zetaModel extends Model {}",
                "export class zetaController extends Component {}",
            )
            *_, studio_bad = self._audit(tmp)
            self.assertEqual(len(studio_bad), 1, studio_bad)
            self.assertIn("no studio_editors entry", studio_bad[0])

    def test_an_editor_contributed_from_a_bridge_counts(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            _view(
                _addon(tmp, "a"),
                "zeta",
                "export class zetaParser extends ViewArchParser {}",
                "export class zetaModel extends Model {}",
                "export class zetaController extends Component {}",
            )
            bridge = _addon(tmp, "a_studio")
            (bridge / "static" / "src" / "editor.js").write_text(
                'registry.category("studio_editors").add("zeta", { label: "Z" });\n',
                encoding="utf8",
            )
            *_, studio_bad = self._audit(tmp)
            self.assertEqual(studio_bad, [])


class TestTheRealTreeIsReached(unittest.TestCase):
    def test_every_base_view_type_resolves(self):
        gate._FILES.clear()
        types, _, _, unresolved, _studio = gate.audit()
        self.assertGreaterEqual(len(types), 10)
        self.assertEqual(unresolved, [])
