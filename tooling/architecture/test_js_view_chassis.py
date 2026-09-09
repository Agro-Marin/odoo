import unittest
from pathlib import Path

import js_view_chassis


def _addon(tmp: Path, name: str) -> Path:
    module = tmp / name
    (module / "static" / "src").mkdir(parents=True)
    (module / "__manifest__.py").write_text("{'name': 'x'}", encoding="utf8")
    return module


def _view(module: Path, view_type: str, registration: str, template_body: str) -> None:
    src = module / "static" / "src"
    (src / "v_view.js").write_text(registration, encoding="utf8")
    (src / "v_controller.js").write_text(
        f"export class VController extends Component {{\n"
        f'    static template = "m.{view_type}";\n}}\n',
        encoding="utf8",
    )
    (src / "v_controller.xml").write_text(
        f'<templates><t t-name="m.{view_type}">{template_body}</t></templates>',
        encoding="utf8",
    )


DIRECT = """
const x = 1;
registry.category("views").add("{t}", {t}View);
const {t}View = {{ type: "{t}", Controller: VController }};
"""
ALIASED = """
const viewRegistry = registry.category("views");
const {t}View = {{ type: "{t}", Controller: VController }};
viewRegistry.add("{t}", {t}View);
"""
CAST = """
const {t}View = {{ type: "{t}", Controller: VController }};
registry.category("views").add("{t}", /** @type {{any}} */ ({t}View));
"""
VARIANT = """
const fancyView = {{ type: "{t}", Controller: VController }};
registry.category("views").add("fancy_{t}", fancyView);
"""


class TestTheScanSeesEveryRegistrationForm(unittest.TestCase):
    """The three forms that all exist in the tree, and one that must be ignored.

    A scan that saw only `registry.category("views").add(...)` missed form,
    graph, pivot and gantt -- this gate's own failure mode arriving in the
    resolver instead of in a template, where nothing would have reported it.
    """

    def _types(self, tmp: Path):
        return set(js_view_chassis.base_view_types((tmp,)))

    def test_a_direct_registration_is_seen(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            _view(_addon(tmp, "a"), "alpha", DIRECT.format(t="alpha"), "<ViewLayout/>")
            self.assertEqual(self._types(tmp), {"alpha"})

    def test_a_registration_through_a_local_alias_is_seen(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            _view(_addon(tmp, "b"), "beta", ALIASED.format(t="beta"), "<ViewLayout/>")
            self.assertEqual(self._types(tmp), {"beta"})

    def test_a_registration_behind_a_type_cast_is_seen(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            _view(_addon(tmp, "c"), "gamma", CAST.format(t="gamma"), "<ViewLayout/>")
            self.assertEqual(self._types(tmp), {"gamma"})

    def test_a_js_class_variant_is_not_a_base_view_type(self):
        # It registers under another key and keeps the base's `type`; holding it
        # to the chassis would demand a control panel of every subtype.
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            _view(_addon(tmp, "e"), "delta", VARIANT.format(t="delta"), "<ViewLayout/>")
            self.assertEqual(self._types(tmp), set())


class TestTheVerdict(unittest.TestCase):
    def _audit(self, tmp: Path):
        return js_view_chassis.audit((tmp,))

    def test_a_template_mounting_ViewLayout_passes(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            _view(
                _addon(tmp, "a"),
                "alpha",
                DIRECT.format(t="alpha"),
                '<ViewLayout t-props="chassis.props"/>',
            )
            _, takes, handrolled, unresolved = self._audit(tmp)
            self.assertEqual((takes, handrolled, unresolved), (["alpha"], [], []))

    def test_a_template_hand_rolling_Layout_is_reported(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            _view(
                _addon(tmp, "a"),
                "alpha",
                DIRECT.format(t="alpha"),
                "<Layout><SearchBar/></Layout>",
            )
            _, takes, handrolled, _ = self._audit(tmp)
            self.assertEqual((takes, handrolled), ([], ["alpha"]))

    def test_an_unreachable_template_is_reported_not_skipped(self):
        # The whole point: a resolver that quietly reached no template would
        # hide exactly the defect this gate looks for.
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            module = _addon(tmp, "a")
            _view(module, "alpha", DIRECT.format(t="alpha"), "<ViewLayout/>")
            (module / "static" / "src" / "v_controller.xml").unlink()
            _, takes, handrolled, unresolved = self._audit(tmp)
            self.assertEqual((takes, handrolled), ([], []))
            self.assertEqual(len(unresolved), 1)
            self.assertIn("alpha", unresolved[0])


class TestTheRealTree(unittest.TestCase):
    def test_the_gate_is_green(self):
        self.assertEqual(js_view_chassis.main(["--check"]), 0)

    def test_every_pinned_type_is_a_real_view_type(self):
        types = set(js_view_chassis.base_view_types())
        unknown = sorted(set(js_view_chassis.PINNED_HANDROLLED) - types)
        self.assertEqual(unknown, [], "pinned names that are not view types")

    def test_the_pin_is_not_hiding_a_converted_type(self):
        _, takes, _, _ = js_view_chassis.audit()
        overlap = sorted(set(takes) & set(js_view_chassis.PINNED_HANDROLLED))
        self.assertEqual(overlap, [], "pinned as hand-rolled but takes ViewLayout")

    def test_it_refuses_a_tree_with_no_view_types(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            original = js_view_chassis.SCAN_ROOTS
            js_view_chassis.SCAN_ROOTS = (Path(d),)
            try:
                self.assertEqual(js_view_chassis.main([]), 2)
            finally:
                js_view_chassis.SCAN_ROOTS = original
