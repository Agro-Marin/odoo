import base64
import logging
import re

from odoo.tests import tagged
from odoo.tests.css import (
    DARK_SCOPE_RE,
    DARK_SELECTOR_RE,
    ROOT,
    flatten_opaque,
    is_mask,
    norm,
    parse,
    pick_dark,
    resolve,
    same_paint,
    settle,
    split_selector,
    unreachable,
    unscoped,
)

from . import lint_case

_logger = logging.getLogger(__name__)

INERT_IN_URI_RE = re.compile(r"(?:var|color-mix)(?:\(|%28)")


def measure(light_css, dark_css):
    light = settle(parse(light_css))
    dark = settle(parse(dark_css))

    light_root = {p: v for _, s, p, v in light if s == ROOT}
    dark_root = {p: v for _, s, p, v in dark if s == ROOT}
    attr_root = dict(light_root)
    attr_root.update(
        {p: v for _, s, p, v in light if DARK_SELECTOR_RE.fullmatch(s.strip())}
    )

    served = {(s, p): v for _, s, p, v in light}
    origin = {(s, p): f for f, s, p, _ in light}
    # a rule restated for a selector list restates each selector in it, as
    # the cascade applies it; later rules win, as they do in the cascade
    scoped = {}
    for _, selector, prop, value in light:
        parts = split_selector(selector)
        stripped = [unscoped(part) for part in parts]
        if parts and all(a != b for a, b in zip(parts, stripped, strict=True)):
            for key in (",".join(stripped), *stripped):
                scoped[(key, prop)] = value

    dark_scoped = set()
    for _, selector, prop, _value in dark:
        parts = split_selector(selector)
        stripped = [unscoped(part) for part in parts]
        if parts and all(a != b for a, b in zip(parts, stripped, strict=True)):
            dark_scoped.update((key, prop) for key in (",".join(stripped), *stripped))

    gap = []
    answered = 0
    for _, selector, prop, value in dark:
        key = (selector, prop)
        if key in dark_scoped:
            answered += 1
            continue
        if key not in served or served[key] == value:
            continue
        if unreachable(selector):
            continue
        if selector == ROOT:
            single, wanted = (
                attr_root.get(prop, served[key]),
                dark_root.get(prop, value),
            )
        else:
            single, wanted = scoped.get(key, served[key]), value
        single = pick_dark(resolve(single, attr_root))
        wanted = pick_dark(resolve(wanted, dark_root))
        if is_mask(prop):
            single, wanted = flatten_opaque(single), flatten_opaque(wanted)
        if same_paint(norm(single), norm(wanted)):
            answered += 1
        else:
            gap.append((origin[key], selector, prop))
    return gap, answered, len(light), len(dark)


@tagged("post_install", "-at_install")
class TestSchemeDuplication(lint_case.LintCase):
    def _measure(self, env):
        return measure(
            self._css(env, "web.assets_web"), self._css(env, "web.assets_web_dark")
        )

    @staticmethod
    def _css(env, bundle):
        assets = env["ir.qweb"]._get_asset_bundle(bundle, css=True, js=False)
        return base64.b64decode(assets.css().datas).decode("utf-8", "replace")

    def test_no_svg_data_uri_reads_a_custom_property(self):
        offenders = []
        with self.superuser_env() as env:
            for bundle in ("web.assets_web", "web.assets_web_dark"):
                for source, selector, prop, value in parse(self._css(env, bundle)):
                    if "svg+xml" not in value:
                        continue
                    inert = INERT_IN_URI_RE.search(value)
                    if inert:
                        offenders.append(
                            f"{bundle} {source} {selector} {prop}: {inert.group(0)}"
                        )

        self.assertFalse(
            offenders,
            f"{len(offenders)} SVG data URI(s) name a custom property, which "
            f"cannot resolve there -- the icon will not be drawn. Keep the "
            f"variable the URI reads a colour, and restate the pair under the "
            f"scheme scope if it has to answer both:\n  " + "\n  ".join(offenders),
        )

    def test_the_light_bundle_answers_the_dark_scheme_alone(self):
        with self.superuser_env() as env:
            gap, answered, light, dark = self._measure(env)

        self.assertGreater(
            min(light, dark),
            12000,
            f"assets_web compiled {light} declarations and assets_web_dark "
            f"{dark}. Something did not compile -- the comparison below is "
            f"being made against a partial bundle and passes for the wrong "
            f"reason.",
        )
        self.assertGreater(
            answered,
            1000,
            f"only {answered} declarations were answered under the attribute, so "
            f"the bundles did not carry the dark scope they should",
        )
        core = lint_case.core_module_names()
        offenders = sorted(
            f"{source} {selector} {prop}"
            for source, selector, prop in gap
            if source.strip("/").split("/")[0] in core
        )
        _logger.info(
            "assets_web %s declarations, assets_web_dark %s: %s answered under "
            "the attribute, %s outside this repository still differ",
            light,
            dark,
            answered,
            len(gap) - len(offenders),
        )
        self.assertFalse(
            offenders,
            f'{len(offenders)} declaration(s) resolve differently under `data-color-scheme="dark"` '
            f"in the light bundle from what the dark bundle serves. Answer the "
            f"scheme with a token, or restate the declaration in the module's "
            f"backend-only scheme rules (coding_guidelines §5.5):\n  "
            + "\n  ".join(offenders),
        )

    def test_a_restatement_for_a_selector_list_answers_each_selector(self):
        light = (
            "/* /a/x.scss */.a{--c:#fff}.b{--c:#fff}"
            ':root[data-color-scheme="dark"] .a,:root[data-color-scheme="dark"] .b'
            "{--c:#000}"
        )
        dark = "/* /a/x.scss */.a{--c:#000}.b{--c:#000}"
        gap, answered, _light, _dark = measure(light, dark)
        self.assertEqual(gap, [])
        self.assertEqual(answered, 2)

    def test_the_measurement_survives_a_brace_in_a_string(self):
        css = (
            '/* /a/x.scss */.fa-bracket-curly::before{content:"{"}'
            "/* /b/y.scss */.after{color:red}"
        )
        self.assertEqual(
            parse(css),
            [
                ("/a/x.scss", ".fa-bracket-curly::before", "content", '"{"'),
                ("/b/y.scss", ".after", "color", "red"),
            ],
        )

    def test_only_the_dark_half_of_light_dark_is_measured(self):
        self.assertEqual(
            pick_dark(
                "linear-gradient(light-dark(#fff, #000), light-dark(#eee, #111))"
            ),
            "linear-gradient(#000, #111)",
        )
        self.assertEqual(pick_dark("light-dark(a, light-dark(b, c))"), "c")
        self.assertEqual(pick_dark("#abc"), "#abc")

    def test_an_opaque_colour_inside_a_mask_is_not_a_scheme_difference(self):
        light = "linear-gradient(130deg, #000 55%, rgba(0, 0, 0, 0.8) 75%, #000 95%)"
        dark = light.replace("#000 ", "#E2E8F0 ")
        self.assertNotEqual(norm(light), norm(dark))
        self.assertEqual(norm(flatten_opaque(light)), norm(flatten_opaque(dark)))

        self.assertNotEqual(
            norm(flatten_opaque("linear-gradient(rgba(0, 0, 0, 0.8), #000)")),
            norm(flatten_opaque("linear-gradient(rgba(0, 0, 0, 0.4), #000)")),
        )
        self.assertEqual(flatten_opaque("var(--o-text)"), "var(--o-text)")

        self.assertTrue(is_mask("mask-image"))
        self.assertTrue(is_mask("-webkit-mask"))
        self.assertFalse(is_mask("mask-size"))
        self.assertFalse(is_mask("background-image"))

    def test_a_comma_inside_has_is_not_a_selector_boundary(self):
        selector = ':root[data-color-scheme="dark"] .a:has(.b, .c) .d, .e'
        self.assertEqual(
            split_selector(selector),
            [':root[data-color-scheme="dark"] .a:has(.b, .c) .d', ".e"],
        )

    def test_a_rule_scoped_to_the_attribute_answers_the_scheme(self):
        self.assertEqual(
            DARK_SCOPE_RE.sub("", ':root[data-color-scheme="dark"] .bg-primary-light'),
            ".bg-primary-light",
        )
        self.assertEqual(
            DARK_SCOPE_RE.sub("", ".bg-primary-light"), ".bg-primary-light"
        )
        self.assertEqual(
            DARK_SCOPE_RE.sub("", ':root[data-color-scheme="dark"]'),
            ':root[data-color-scheme="dark"]',
        )

    def test_the_attribute_alone_scopes_the_root(self):
        gap, answered, _, _ = measure(
            ':root{color-scheme:light}:root[data-color-scheme="dark"]{color-scheme:dark}',
            ":root{color-scheme:dark}",
        )
        self.assertEqual((gap, answered), ([], 1))

    def test_bootstraps_own_colour_mode_is_not_counted(self):
        self.assertTrue(unreachable('[data-bs-theme="dark"]'))
        self.assertTrue(unreachable("[data-bs-theme=dark] .card"))
        self.assertFalse(unreachable(".navbar-dark,.navbar[data-bs-theme=dark]"))
        self.assertFalse(unreachable(":root"))

    def test_the_attribute_reading_is_what_is_compared(self):
        light = settle(
            parse(
                "/* /a/x.scss */:root{--o-bg:#fff;--other:1px}"
                '/* /a/x.scss */:root[data-color-scheme="dark"]{--o-bg:#000}'
            )
        )
        self.assertEqual(
            {p: v for _, s, p, v in light if s == ROOT},
            {"--o-bg": "#fff", "--other": "1px"},
        )
        self.assertTrue(DARK_SELECTOR_RE.fullmatch(':root[data-color-scheme="dark"]'))
        self.assertEqual(
            norm(resolve("var(--o-bg)", {"--o-bg": "black"})), "rgb(0,0,0)"
        )

    def test_a_colour_is_compared_by_what_it_paints(self):
        self.assertEqual(
            norm("color-mix(in srgb, #3a3a3c 50%, #48484a)"), norm("rgb(65, 65, 67)")
        )
        self.assertEqual(
            norm("rgb(from #f5f5f7 r g b / 0.2)"), norm("rgba(245, 245, 247, .2)")
        )
        self.assertEqual(
            norm("1px solid hsla(0, 0%, 100%, .08)"),
            norm("1px solid rgba(255,255,255,0.08)"),
        )
        self.assertEqual(
            norm("hsl(240, 4.347826087%, 19.0196078431%)"), norm("rgb(46, 46, 51)")
        )
        self.assertEqual(
            norm("color-mix(in srgb, #0071e3 10%, transparent)"),
            norm("rgba(0, 113, 227, 0.1)"),
        )
        self.assertEqual(norm("hsl(from #0071e3 h s calc(l - 10%))"), norm("#0058b0"))
        self.assertEqual(
            norm("rgba(0, 0, 0, calc(0.055 * 2))"), norm("rgba(0, 0, 0, 0.11)")
        )
        self.assertTrue(
            same_paint(norm("1px solid #ed0d00"), norm("1px solid #ec0d00"))
        )
        self.assertFalse(
            same_paint(norm("1px solid #ee0d00"), norm("1px solid #ec0d00"))
        )
        self.assertFalse(
            same_paint(norm("2px solid #ec0d00"), norm("1px solid #ec0d00"))
        )
        self.assertNotEqual(norm("rgba(245,245,247,.11)"), norm("rgba(245,245,247,.2)"))
        unresolved = "color-mix(in srgb, var(--x) 50%, #000)"
        self.assertEqual(norm(unresolved), unresolved)
        self.assertEqual(norm("white-space"), "white-space")
        self.assertEqual(norm("0 .5rem 1rem"), norm("0 0.5rem 1rem"))
        self.assertEqual(norm("rgba(48, 48, 48, 0)"), norm("transparent"))
        self.assertEqual(
            norm("color-mix(in srgb, purple 50%, white)"), norm("rgb(192,128,192)")
        )
        self.assertEqual(
            resolve(
                "var(--x, hsl(from var(--y, #000) h s calc(l + 20)))", {"--y": "#fff"}
            ),
            "hsl(from #fff h s calc(l + 20))",
        )
