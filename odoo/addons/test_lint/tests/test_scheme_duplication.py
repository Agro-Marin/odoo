import base64
import logging
import re
from collections import Counter

from odoo import SUPERUSER_ID, api
from odoo.modules import Manifest
from odoo.modules.registry import Registry
from odoo.tests import tagged
from odoo.tests.common import get_db_name

from . import lint_case

_logger = logging.getLogger(__name__)

SOURCE_MARK_RE = re.compile(r"/\*\s*(/[^*]+?)\s*\*/")

VAR_RE = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,([^()]*(?:\([^()]*\)[^()]*)*))?\)")

DARK_SELECTOR_RE = re.compile(r':root\[data-color-scheme="?dark"?\]')

INERT_IN_URI_RE = re.compile(r"(?:var|color-mix)(?:\(|%28)")

DARK_SCOPE_RE = re.compile(r'(?:^|(?<= )):root\[data-color-scheme="?dark"?\] +')

_KEYWORDS = {
    "white": "#ffffff",
    "black": "#000000",
    "#000": "#000000",
    "#fff": "#ffffff",
}

SINGLE_BUNDLE_GAP_FLOOR = {
    "account": 5,
    "account_accountant": 3,
    "account_asset": 3,
    "account_edi_ubl_cii": 1,
    "account_reports": 23,
    "accountant_knowledge": 1,
    "ai": 1,
    "appointment": 2,
    "approval": 26,
    "base_automation": 1,
    "base_import": 1,
    "calendar": 2,
    "documents": 14,
    "documents_spreadsheet": 5,
    "event": 1,
    "geoengine": 48,
    "google_address_autocomplete": 1,
    "hr_gamification": 1,
    "hr_recruitment": 1,
    "hr_skills_slides": 1,
    "html_editor": 28,
    "im_livechat": 4,
    "knowledge": 4,
    "mail": 58,
    "mail_enterprise": 1,
    "mrp": 2,
    "mrp_workorder": 12,
    "onboarding": 1,
    "planning": 2,
    "product": 1,
    "project": 7,
    "sale": 11,
    "sign": 4,
    "spreadsheet": 1,
    "spreadsheet_dashboard": 2,
    "stock": 1,
    "stock_barcode": 9,
    "survey": 1,
    "web": 136,
    "web_cohort": 4,
    "web_enterprise": 3,
    "web_gantt": 15,
    "web_grid": 2,
    "web_map": 2,
    "web_tour": 2,
    "website": 19,
    "website_sale": 1,
}


def parse(css):
    """``(source file, selector, property, value)`` in source order.

    String- and comment-aware. Naive brace counting is not enough: FontAwesome
    ships ``.fa-bracket-curly`` whose ``content`` is a literal ``{``, and one
    unbalanced brace desynchronises every selector after it -- which reads as
    1,943 differing declarations in a file that has none.
    """
    out, buf, stack, source = [], "", [], "?"
    index, end = 0, len(css)

    def flush():
        nonlocal buf
        declaration, buf = buf.strip(), ""
        if ":" in declaration and stack:
            prop, _, value = declaration.partition(":")
            out.append((source, " ".join(stack), prop.strip(), value.strip()))

    while index < end:
        char = css[index]
        if char == "/" and css[index + 1 : index + 2] == "*":
            close = css.find("*/", index + 2)
            close = end if close < 0 else close + 2
            mark = SOURCE_MARK_RE.fullmatch(css[index:close])
            if mark and not stack:
                source = mark.group(1)
            index = close
            continue
        if char in "\"'":
            close = index + 1
            while close < end and css[close] != char:
                close += 2 if css[close] == "\\" else 1
            buf += css[index : close + 1]
            index = close + 1
            continue
        if char == "{":
            stack.append(buf.strip())
            buf = ""
        elif char == "}":
            flush()
            if stack:
                stack.pop()
        elif char == ";":
            flush()
        else:
            buf += char
        index += 1
    return out


def split_selector(selector):
    """Split a selector list on its *top-level* commas.

    Splitting on every comma breaks inside a functional pseudo-class:
    ``:has(.a, .b)`` becomes two fragments, only the first of which still starts
    with the scope. Every caller below then decides the rule is not scoped, and a
    correct restatement is scored as unanswered -- 68 declarations in
    ``stock_barcode`` alone, every one of them on a ``:has()`` selector.
    """
    parts, depth, current = [], 0, ""
    for char in selector:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and not depth:
            parts.append(current)
            current = ""
        else:
            current += char
    parts.append(current)
    return [part.strip() for part in parts if part.strip()]


def is_root(selector):
    return ":root" in split_selector(selector)


def unreachable(selector):
    """Whether nothing in the back office can match *selector*.

    Bootstrap ships its own colour-mode block behind ``[data-bs-theme="dark"]``,
    about 56 declarations, in every bundle that carries it. The back office
    never sets that attribute -- it answers ``data-color-scheme`` -- so those
    declarations cannot apply here, and counting them puts work in the floor
    that no amount of migration can remove.

    Nor should anyone make them apply. Bootstrap derives its dark set through
    ``tint-color()``/``shade-color()``, which this fork inverts, and 53 of the
    54 tokens it names disagree with the palette the dark bundle actually
    serves. Setting ``data-bs-theme`` in the back office would lay Bootstrap's
    stock dark greys over this one. It is live on the *frontend*, where
    ``database_manager.js`` follows the OS with it and Bootstrap's own values
    are the right answer.

    Only when every comma-separated part is behind the attribute:
    ``.navbar-dark,.navbar[data-bs-theme=dark]`` is reachable through its first
    half.
    """
    parts = split_selector(selector)
    return bool(parts) and all("[data-bs-theme=" in part for part in parts)


ROOT = "\x00:root"


def settle(declarations):
    """Drop root-level custom properties a later rule supersedes.

    Every rule naming ``:root`` scores the same, so the last declaration of a
    name is the one in effect. Counting the earlier ones reports a token as
    still differing when what resolves does not.
    """
    keep, order = {}, []
    for source, selector, prop, value in declarations:
        key = (
            (ROOT, prop)
            if prop.startswith("--") and is_root(selector)
            else (selector, prop)
        )
        if key not in keep:
            order.append(key)
        keep[key] = (source, value)
    return [(keep[key][0], key[0], key[1], keep[key][1]) for key in order]


def resolve(value, scope, depth=0):
    """Substitute `var()` against *scope* until it stops changing."""
    if depth > 12:
        return value

    def substitute(match):
        name, fallback = match.group(1), match.group(2)
        if name in scope:
            return resolve(scope[name], scope, depth + 1)
        return (
            resolve(fallback.strip(), scope, depth + 1) if fallback else match.group(0)
        )

    substituted = VAR_RE.sub(substitute, value)
    return value if substituted == value else resolve(substituted, scope, depth + 1)


def pick_dark(value):
    """Reduce every ``light-dark(light, dark)`` in *value* to its dark half.

    Both bundles carry the declaration, but each compiles the *light* half from
    the palette it was built with -- so the dark bundle says
    ``light-dark(#22D3EE, #22D3EE)`` where the light one says
    ``light-dark(#06B6D4, #22D3EE)``. Compared as text they differ; served, they
    do not, because a single stylesheet has one copy and the attribute picks the
    same half in both. Only that half is the answer being measured.
    """
    while True:
        start = value.lower().find("light-dark(")
        if start < 0:
            return value
        depth, index = 0, start + len("light-dark(") - 1
        while index < len(value):
            if value[index] == "(":
                depth += 1
            elif value[index] == ")":
                depth -= 1
                if not depth:
                    break
            index += 1
        inner = value[start + len("light-dark(") : index]
        halves = split_selector(inner)
        if len(halves) != 2:
            return value
        value = value[:start] + pick_dark(halves[1]) + value[index + 1 :]


def norm(value):
    """Compare as colour, not as text: `white` is `#ffffff`, `rgba(…,1)` is `rgb(…)`."""
    value = re.sub(r"\s+", " ", (value or "").strip().lower())
    value = _KEYWORDS.get(value, value)
    if re.fullmatch(r"#[0-9a-f]{3}", value):
        value = "#" + "".join(char * 2 for char in value[1:])
    match = re.fullmatch(r"rgba?\(([^()]*)\)", value)
    if match:
        parts = [part for part in re.split(r"[,\s/]+", match.group(1)) if part]
        if all(re.fullmatch(r"[\d.]+%?", part) for part in parts):
            parts = [f"{float(part.rstrip('%')):g}" for part in parts]
            if len(parts) == 4 and parts[3] == "1":
                parts = parts[:3]
            value = "rgb(" + ",".join(parts) + ")"
    return value


def measure(light_css, dark_css):
    """``(gap, answered, light count, dark count)`` for two compiled bundles.

    Module level and taking CSS rather than an environment, so anything that
    wants this number -- the test, a one-off script while migrating a file --
    runs the *same* comparison. A second copy of it silently stopped counting
    the scoped-rule technique the moment that was added, and reported a change
    that works as zero progress.
    """
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
    scoped = {}
    for _, selector, prop, value in light:
        parts = split_selector(selector)
        stripped = [DARK_SCOPE_RE.sub("", part) for part in parts]
        if parts and all(a != b for a, b in zip(parts, stripped, strict=True)):
            scoped[(",".join(stripped), prop)] = value

    dark_scoped = set()
    for _, selector, prop, _value in dark:
        parts = split_selector(selector)
        stripped = [DARK_SCOPE_RE.sub("", part) for part in parts]
        if parts and all(a != b for a, b in zip(parts, stripped, strict=True)):
            dark_scoped.add((",".join(stripped), prop))

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
        if norm(single) == norm(wanted):
            answered += 1
        else:
            gap.append((origin[key], selector, prop))
    return gap, answered, len(light), len(dark)


@tagged("post_install", "-at_install")
class TestSchemeDuplication(lint_case.LintCase):
    """How much a single stylesheet would still get wrong.

    Two schemes are already published from one file and both publication paths
    agree; the question this answers is how much *consumes* them. Set
    ``data-color-scheme="dark"`` on the light bundle and compare what each
    declaration resolves to against what the dark bundle serves: whatever
    disagrees is the reason ``web.assets_web_dark`` cannot be deleted.

    Not "declarations that differ". Most of those are the mechanism working --
    the token layer's own ``:root`` differs from the dark bundle's by design,
    and the attribute answers it. Counting them scored the entire token layer
    as work remaining and the first phase of real work as zero progress.
    """

    def _measure(self, env):
        return measure(
            self._css(env, "web.assets_web"), self._css(env, "web.assets_web_dark")
        )

    @staticmethod
    def _css(env, bundle):
        assets = env["ir.qweb"]._get_asset_bundle(bundle, css=True, js=False)
        return base64.b64decode(assets.css().datas).decode("utf-8", "replace")

    def test_no_svg_data_uri_reads_a_custom_property(self):
        """A token inside an SVG data URI is inert, and nothing else says so.

        The URI is not CSS, so a ``var()`` or ``color-mix()`` written into one
        neither resolves nor errors: the bundle compiles and the icon is simply
        not drawn. Both times a Bootstrap variable was moved onto a token and
        turned out to feed an icon -- ``$component-active-color`` into the
        indeterminate checkbox, ``$navbar-dark-color`` into the toggler -- the
        compile was clean and the CSS diff was the only witness.
        """
        offenders = []
        with Registry(get_db_name()).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
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

    def test_the_single_bundle_gap_does_not_grow(self):
        with Registry(get_db_name()).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            gap, answered, light, dark = self._measure(env)

        self.assertGreater(
            min(light, dark),
            12000,
            f"assets_web compiled {light} declarations and assets_web_dark "
            f"{dark}. Something did not compile -- every floor below is being "
            f"measured against a partial bundle and will pass for the wrong "
            f"reason.",
        )
        _logger.info(
            "assets_web %s declarations, assets_web_dark %s: %s declarations would "
            "still be wrong under one stylesheet, %s the attribute already answers",
            light,
            dark,
            len(gap),
            answered,
        )
        by_module = Counter(source.strip("/").split("/")[0] for source, _, _ in gap)
        _logger.info("worst modules: %s", by_module.most_common(8))
        by_file = Counter(source for source, _, _ in gap)
        _logger.info("worst files: %s", by_file.most_common(6))

        offenders = []
        for module, count in sorted(by_module.items()):
            floor = SINGLE_BUNDLE_GAP_FLOOR.get(module)
            if floor is None:
                offenders.append(f"{module}: {count}, in a module that had none")
            elif count > floor:
                offenders.append(f"{module}: {count}, floor is {floor}")
        under = sorted(
            f"{module} {by_module.get(module, 0)}/{floor}"
            for module, floor in SINGLE_BUNDLE_GAP_FLOOR.items()
            if module in by_module and by_module[module] < floor
        )
        if under:
            _logger.info("under the floor on this install: %s", ", ".join(under))
        unreachable = sorted(set(SINGLE_BUNDLE_GAP_FLOOR) - set(by_module))
        _logger.info(
            "%s of %s floors were exercised on this install; %s were not: %s",
            len(SINGLE_BUNDLE_GAP_FLOOR) - len(unreachable),
            len(SINGLE_BUNDLE_GAP_FLOOR),
            len(unreachable),
            ", ".join(unreachable),
        )
        self.assertFalse(
            offenders,
            f"{len(offenders)} module(s) put more between this fork and a single "
            f"stylesheet than the committed floor. A declaration counted here is "
            f'one a light bundle under `data-color-scheme="dark"` resolves '
            f"differently from what the dark bundle serves:\n  "
            + "\n  ".join(offenders),
        )

    def test_every_floor_names_a_module_that_exists(self):
        """A floor for a module that is gone can never come down.

        It is also invisible: the gate only reports a module whose count is
        *above* its floor, so an entry naming nothing at all sits there
        indefinitely, adding to the 47 and to the impression of coverage. This
        is install-independent -- it asks the addons path, not the registry --
        so it holds on the narrowest database as well as the broadest.
        """
        known = {manifest.name for manifest in Manifest.all_addon_manifests()}
        self.assertFalse(
            sorted(set(SINGLE_BUNDLE_GAP_FLOOR) - known),
            "these floors name a module that is not on the addons path",
        )

    def test_the_measurement_survives_a_brace_in_a_string(self):
        """The defect that made the first version of this report nonsense.

        FontAwesome ships ``.fa-bracket-curly``, whose ``content`` is a literal
        ``{``. Counted naively it desynchronises every selector after it, and
        the file reads as 1,943 differing declarations while having none.
        """
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
        """A `light-dark()` compiles its light half from the compiling palette.

        So the two bundles carry the same declaration with different *light*
        halves, and comparing them as text says they disagree about a colour
        neither of them serves under the attribute.
        """
        self.assertEqual(
            pick_dark(
                "linear-gradient(light-dark(#fff, #000), light-dark(#eee, #111))"
            ),
            "linear-gradient(#000, #111)",
        )
        self.assertEqual(pick_dark("light-dark(a, light-dark(b, c))"), "c")
        self.assertEqual(pick_dark("#abc"), "#abc")

    def test_a_comma_inside_has_is_not_a_selector_boundary(self):
        """The defect that made 68 correct restatements read as unanswered.

        `stock_barcode` builds every one of its rules on
        `:has(.a, .b)`. Split on every comma, the second fragment no longer
        starts with the scope, `all(a != b)` is false, and the rule is not
        recognised as scoped -- so the plain rule it answers stays in the gap and
        the file reads as the single largest offender in the fork.
        """
        selector = ':root[data-color-scheme="dark"] .a:has(.b, .c) .d, .e'
        self.assertEqual(
            split_selector(selector),
            [':root[data-color-scheme="dark"] .a:has(.b, .c) .d', ".e"],
        )

    def test_a_rule_scoped_to_the_attribute_answers_the_scheme(self):
        """The third technique, after the token and `light-dark()`.

        Some values cannot become either: `color-contrast()` has no CSS form
        this palette can use, and a mixin that measures its argument with
        `alpha()` cannot take a `var()`. Restating the rule under the attribute
        as an ancestor is what is left, and it costs the same bytes the dark
        bundle spends on it today -- in one file rather than two.
        """
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

    def test_bootstraps_own_colour_mode_is_not_counted(self):
        """It cannot apply in the back office, and must not be made to."""
        self.assertTrue(unreachable('[data-bs-theme="dark"]'))
        self.assertTrue(unreachable("[data-bs-theme=dark] .card"))
        self.assertFalse(unreachable(".navbar-dark,.navbar[data-bs-theme=dark]"))
        self.assertFalse(unreachable(":root"))

    def test_the_attribute_reading_is_what_is_compared(self):
        """A root custom property is answered by the dark block, not by its own
        light declaration -- which is the whole point of publishing both."""
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
        self.assertEqual(norm(resolve("var(--o-bg)", {"--o-bg": "black"})), "#000000")
